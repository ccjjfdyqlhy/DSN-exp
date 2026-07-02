# skills/builtin/ncm_music/tools/ncm_api.py
# NCMApi — 基于本地 pyncm 模块的网易云音乐 API 封装

from __future__ import annotations

import hashlib
import logging
import os
import re
import json
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger("NCMApi")

# pyncm 品质级别 → (level 字符串, 显示名)
PYNCM_QUALITY: dict[int, tuple[str, str]] = {
    1: ("standard", "标准 128kbps"),
    2: ("standard", "标准 128kbps"),
    3: ("exhigh",   "HQ 320kbps"),
    4: ("exhigh",   "HQ 320kbps"),
    5: ("lossless", "SQ 无损 FLAC"),
    6: ("lossless", "SQ 无损 FLAC"),
    7: ("hires",    "Hi-Res 高解析度"),
    8: ("hires",    "Hi-Res 高解析度"),
    9: ("hires",    "Hi-Res 高解析度"),
}

DEFAULT_QUALITY = 4

_THIS_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_MUSIC_DIR = _THIS_DIR / "music"
_SESSION_FILE = ".pyncm_session"


class NCMApi:
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.timeout = self.config.get("timeout", 30)
        self.default_quality = self.config.get("default_quality", DEFAULT_QUALITY)
        self._music_dir = Path(self.config.get("music_dir", str(_DEFAULT_MUSIC_DIR)))
        self._music_dir.mkdir(parents=True, exist_ok=True)

        # pyncm session 管理
        self._session_loaded = False
        self._try_restore_session()

        logger.info("NCMApi 初始化: music_dir=%s", self._music_dir)

    # ================================================================
    # Session 管理
    # ================================================================

    def _try_restore_session(self):
        """尝试从文件恢复 pyncm 登录态，或通过 MUSIC_U 环境变量登录"""
        session_path = self._music_dir / _SESSION_FILE
        if session_path.exists():
            try:
                from pyncm import loadSessionFromString, setCurrentSession
                data = session_path.read_text().strip()
                if data:
                    setCurrentSession(loadSessionFromString(data))
                    from pyncm import apis
                    r = apis.login.getCurrentLoginStatus()
                    if r.get("code") == 200 and r.get("account"):
                        self._session_loaded = True
                        logger.info("已从 %s 恢复登录态", session_path)
                        return
                    logger.warning("Session 已过期，将重新登录")
            except Exception as e:
                logger.warning("恢复 session 失败: %s", e)

        # 尝试从环境变量或 Config 登录
        music_u = os.environ.get("NCM_MUSIC_U", "") or ""
        if not music_u:
            try:
                from config import Config
                music_u = getattr(Config, "NCM_MUSIC_U", "") or ""
            except Exception:
                pass
        if not music_u:
            music_u = self.config.get("music_u", "")
        if music_u:
            self._login_by_cookie(music_u)
            return

        logger.warning("未配置 MUSIC_U，NCM 功能可能受限。设置 NCM_MUSIC_U 环境变量或配置文件中的 music_u")

    def _login_by_cookie(self, music_u: str):
        """用 MUSIC_U cookie 登录并保存 session"""
        try:
            from pyncm import apis, dumpSessionAsString, getCurrentSession, setCurrentSession
            r = apis.login.loginViaCookie(MUSIC_U=music_u)
            if r.get("code") == 200:
                r2 = apis.login.getCurrentLoginStatus()
                if r2.get("code") == 200 and r2.get("account"):
                    session_path = self._music_dir / _SESSION_FILE
                    session_path.write_text(dumpSessionAsString(getCurrentSession()))
                    self._session_loaded = True
                    logger.info("MUSIC_U 登录成功，session 已保存")
                    return
            logger.warning("MUSIC_U 登录失败: %s", r)
        except Exception as e:
            logger.error("MUSIC_U 登录异常: %s", e)

    def _ensure_logged_in(self) -> bool:
        """确保已登录，未登录时打日志但继续（只读操作可用）"""
        if self._session_loaded:
            return True
        # 二次尝试：可能是 session 文件被外部更新
        self._try_restore_session()
        return self._session_loaded

    def _save_session(self):
        """持久化当前登录态"""
        try:
            from pyncm import dumpSessionAsString, getCurrentSession
            session_path = self._music_dir / _SESSION_FILE
            session_path.write_text(dumpSessionAsString(getCurrentSession()))
        except Exception as e:
            logger.warning("保存 session 失败: %s", e)

    # ================================================================
    # 品质映射
    # ================================================================

    @staticmethod
    def _quality_to_pyncm(quality: int) -> tuple[str, str]:
        """将旧版 1-9 品质值映射为 pyncm 的 (level, 显示名)"""
        return PYNCM_QUALITY.get(quality, PYNCM_QUALITY[DEFAULT_QUALITY])

    # ================================================================
    # 公开工具方法
    # ================================================================

    def login(self, music_u: str) -> dict:
        """
        用 MUSIC_U Cookie 登录网易云音乐。

        :param music_u: 从浏览器 Cookie 获取的 MUSIC_U 值
        """
        if not music_u or not music_u.strip():
            return {"success": False, "error": "MUSIC_U 不能为空"}
        music_u = music_u.strip()
        logger.info("login: 通过 MUSIC_U 登录")

        from pyncm import apis, dumpSessionAsString, getCurrentSession, setCurrentSession
        try:
            r = apis.login.loginViaCookie(MUSIC_U=music_u)
            if r.get("code") != 200:
                return {"success": False, "error": f"登录失败: {r.get('message', '未知错误')}"}
            r2 = apis.login.getCurrentLoginStatus()
            if r2.get("code") != 200 or not r2.get("account"):
                return {"success": False, "error": "登录验证失败"}
            session_path = self._music_dir / _SESSION_FILE
            session_path.write_text(dumpSessionAsString(getCurrentSession()))
            self._session_loaded = True
            nickname = r2.get("profile", {}).get("nickname", "?")
            logger.info("登录成功: %s", nickname)
            return {"success": True, "nickname": nickname}
        except Exception as e:
            logger.error("登录异常: %s", e)
            return {"success": False, "error": f"登录异常: {e}"}

    def search_song(
        self,
        keyword: str,
        page: int = 1,
        num: int = 5,
        quality: int = None,
        auto_download: bool = False,
    ) -> dict:
        """
        搜索歌曲，返回歌曲列表（含元数据）。

        :param keyword: 搜索关键词（歌名/歌手/专辑）
        :param page: 页数，默认 1（pyncm 用 offset=(page-1)*num）
        :param num: 每页数量，默认 5
        :param quality: 音质
        :param auto_download: 是否自动下载第一首
        """
        if not keyword or not keyword.strip():
            return {"success": False, "error": "关键词不能为空"}

        kw = keyword.strip()
        logger.info("搜索歌曲: keyword=%s page=%d num=%d", kw, page, num)

        songs = self._do_search(kw, page, num)
        if songs is None:
            return {"success": False, "error": "搜索失败，请确认网络连接或登录态"}

        result = {
            "success": True,
            "songs": songs,
            "total": len(songs),
            "page": page,
        }

        if auto_download and songs:
            song_id = songs[0].get("id")
            if song_id:
                url_result = self._fetch_song_url(song_id, quality or self.default_quality)
                if url_result.get("success"):
                    song_meta = url_result.get("song", {})
                    dl = self._download_song_file(song_meta.get("name", songs[0].get("name", "unknown")),
                                                  song_meta.get("artist", ""),
                                                  song_meta.get("url", ""),
                                                  song_meta.get("ext", ".mp3"))
                    if dl["success"]:
                        result["downloaded"] = dl
                    else:
                        result["download_error"] = dl.get("error")
                    songs[0].update({k: song_meta.get(k) for k in ("url", "quality", "size") if song_meta.get(k)})

        logger.info("搜索完成: keyword=%s found=%d", kw, len(songs))
        return result

    def get_song_url(
        self,
        song_id: int = 0,
        keyword: str = "",
        choose: int = 1,
        quality: int = None,
        download: bool = False,
    ) -> dict:
        """
        获取歌曲播放链接。

        :param song_id: 歌曲 ID
        :param keyword: 搜索关键词（当 song_id=0 时用 keyword 搜索取第 choose 首）
        :param choose: 选择搜索结果第几首
        :param quality: 音质 1-9
        :param download: 是否下载到本地
        """
        q = quality or self.default_quality
        song_id = int(song_id) if song_id else 0

        # 如果没给 ID，用 keyword 搜索确定
        if not song_id and keyword:
            songs = self._do_search(keyword.strip(), 1, max(choose, 5))
            if not songs or choose > len(songs):
                return {"success": False, "error": f"未找到歌曲，或序号 {choose} 超出范围"}
            song_id = songs[choose - 1].get("id", 0)
            if not song_id:
                return {"success": False, "error": "搜索结果无有效歌曲 ID"}

        if not song_id:
            return {"success": False, "error": "至少需要 song_id 或 keyword 参数"}

        result = self._fetch_song_url(song_id, q)
        if not result.get("success"):
            return result

        song = result["song"]
        has_url = bool(song.get("url"))

        ret = {
            "success": True,
            "song": song,
            "has_playable_url": has_url,
        }

        if not has_url:
            ret["note"] = "该歌曲当前无可用播放链接（可能需 VIP 或版权限制）"

        if download and has_url:
            dl = self._download_song_file(song.get("name", "unknown"),
                                          song.get("artist", ""),
                                          song["url"],
                                          song.get("ext", ".mp3"))
            ret["downloaded"] = dl

        logger.info("获取歌曲链接: id=%d name=%s has_url=%s",
                     song.get("id", 0), song.get("name", "?"), has_url)
        return ret

    def get_lyrics(
        self,
        song_id: int,
        save: bool = True,
    ) -> dict:
        """
        获取歌词。

        :param song_id: 歌曲 ID
        :param save: 是否保存歌词到本地文件
        """
        logger.info("获取歌词: id=%d save=%s", song_id, save)
        self._ensure_logged_in()

        try:
            from pyncm import apis
            raw = apis.track.getTrackLyricsNew(song_id)
        except Exception as e:
            logger.error("获取歌词失败: %s", e)
            return {"success": False, "error": f"获取歌词失败: {e}"}

        if raw.get("code") != 200:
            return {"success": False, "error": raw.get("message", "获取歌词失败")}

        lrc_str = ""
        lrc_data = raw.get("lrc", {}) or {}
        if isinstance(lrc_data, dict):
            lrc_str = lrc_data.get("lyric", "")

        plain = self._strip_lrc_timestamps(lrc_str)

        result = {
            "success": True,
            "data": {
                "song_id": song_id,
                "lrc": lrc_str,
                "plain": plain,
                "line_count": len(plain.strip().split("\n")) if plain.strip() else 0,
            },
        }

        if save and plain.strip():
            saved = self._save_lyrics(song_id, lrc_str, plain)
            result["saved_to"] = saved

        return result

    def list_downloaded(self) -> dict:
        """列出已下载的歌曲和歌词文件"""
        songs = []
        lyrics = []
        try:
            for f in sorted(self._music_dir.iterdir()):
                if f.is_dir() or f.name == _SESSION_FILE:
                    continue
                info = {
                    "filename": f.name,
                    "size": f.stat().st_size,
                    "size_human": self._format_size(f.stat().st_size),
                }
                if f.suffix.lower() in (".mp3", ".flac", ".wav", ".ogg", ".m4a", ".aac", ".wma"):
                    songs.append(info)
                elif f.suffix.lower() in (".lrc", ".txt"):
                    lyrics.append(info)
        except Exception as e:
            logger.error("列出已下载文件失败: %s", e)
            return {"success": False, "error": str(e)}

        logger.info("已下载: %d 首歌, %d 份歌词", len(songs), len(lyrics))
        return {
            "success": True,
            "songs": songs,
            "lyrics": lyrics,
            "total_songs": len(songs),
            "total_lyrics": len(lyrics),
        }

    # ================================================================
    # pyncm API 调用
    # ================================================================

    def _do_search(self, keyword: str, page: int, num: int) -> list[dict] | None:
        """搜索歌曲，返回标准化列表"""
        self._ensure_logged_in()
        try:
            from pyncm import apis
            raw = apis.cloudsearch.getSearchResult(
                keyword, stype=apis.cloudsearch.SONG, limit=num, offset=(page - 1) * num
            )
        except Exception as e:
            logger.error("搜索异常: %s", e)
            return None

        if raw.get("code") != 200:
            logger.warning("搜索返回异常: code=%s", raw.get("code"))
            return None

        songs = raw.get("result", {}).get("songs", [])
        return [self._normalize_song(s) for s in songs]

    def _fetch_song_url(self, song_id: int, quality: int) -> dict:
        """获取单首歌曲的播放链接"""
        level, quality_name = self._quality_to_pyncm(quality)
        logger.info("获取音频URL: id=%d level=%s", song_id, level)

        self._ensure_logged_in()
        try:
            from pyncm import apis
            raw = apis.track.getTrackAudioV1([song_id], level=level)
        except Exception as e:
            logger.error("获取音频URL异常: %s", e)
            return {"success": False, "error": f"获取音频链接失败: {e}"}

        if raw.get("code") != 200:
            return {"success": False, "error": raw.get("message", "获取音频链接失败")}

        data = raw.get("data", [])
        if not data:
            return {"success": False, "error": "音频数据为空"}

        item = data[0]
        url = item.get("url", "") or ""

        # 若无 URL 且品质不是最低，尝试降级
        if not url and level != "standard":
            logger.info("无 %s 可用，降级至 standard", level)
            return self._fetch_song_url(song_id, 1)

        # 获取歌曲详情用于元数据
        song_meta = {}
        try:
            detail = apis.track.getTrackDetail([song_id])
            if detail.get("code") == 200:
                s = detail.get("songs", [{}])[0]
                artists = ", ".join(a.get("name", "") for a in s.get("ar", s.get("artists", [])))
                song_meta = {
                    "name": s.get("name", ""),
                    "artist": artists,
                    "album": (s.get("al", s.get("album", {})) or {}).get("name", ""),
                    "duration": s.get("dt", 0) // 1000,  # ms → s
                    "cover": (s.get("al", s.get("album", {})) or {}).get("picUrl", ""),
                    "id": song_id,
                }
        except Exception:
            song_meta = {"id": song_id, "name": "", "artist": "", "album": ""}

        ext = self._guess_ext(url) if url else ".mp3"
        return {
            "success": True,
            "song": {
                **song_meta,
                "url": url,
                "quality": quality_name,
                "ext": ext,
            },
        }

    # ================================================================
    # 数据标准化
    # ================================================================

    def _normalize_song(self, item: dict) -> dict:
        artists = ", ".join(a.get("name", "") for a in item.get("artists", item.get("ar", [])))
        album = (item.get("album", item.get("al", {})) or {})
        dur_ms = item.get("duration", item.get("dt", 0))
        return {
            "id": item.get("id", 0),
            "name": item.get("name", "未知"),
            "singer": artists,
            "album": album.get("name", "") if isinstance(album, dict) else str(album),
            "duration": dur_ms // 1000 if dur_ms else 0,
            "duration_str": f"{dur_ms // 60000}:{(dur_ms // 1000) % 60:02d}" if dur_ms else "",
            "cover": album.get("picUrl", "") if isinstance(album, dict) else "",
        }

    # ================================================================
    # 文件下载
    # ================================================================

    def _download_song_file(self, name: str, artist: str, url: str, ext: str) -> dict:
        """下载歌曲文件到本地 music 目录"""
        if not url:
            return {"success": False, "error": "无可用的播放链接"}

        safe_name = self._safe_filename(f"{artist} - {name}" if artist else name)
        filepath = self._music_dir / f"{safe_name}{ext}"

        if filepath.exists():
            logger.info("歌曲已存在，跳过下载: %s", filepath.name)
            return {"success": True, "path": str(filepath), "filename": filepath.name,
                    "existed": True, "size": filepath.stat().st_size}

        logger.info("开始下载: %s", filepath.name)
        try:
            from pyncm.utils.downloader import Downloader
            dl = Downloader(pool_size=4, timeout=self.timeout)
            dl.append(url, str(filepath))
            dl.wait()
        except Exception as e:
            logger.error("下载失败: %s", e)
            if filepath.exists():
                filepath.unlink()
            return {"success": False, "error": f"下载失败: {e}"}

        if filepath.exists():
            size = filepath.stat().st_size
            logger.info("下载完成: %s (%s)", filepath.name, self._format_size(size))
            return {"success": True, "path": str(filepath), "filename": filepath.name,
                    "size": size, "size_human": self._format_size(size)}

        return {"success": False, "error": "下载未完成"}

    def _save_lyrics(self, song_id: int, lrc_text: str, plain_text: str) -> dict:
        sid = str(song_id)
        lrc_path = self._music_dir / f"{sid}.lrc"
        txt_path = self._music_dir / f"{sid}.txt"
        try:
            lrc_path.write_text(lrc_text, encoding="utf-8")
            txt_path.write_text(plain_text, encoding="utf-8")
            logger.info("歌词已保存: %s, %s", lrc_path.name, txt_path.name)
            return {"lrc_path": str(lrc_path), "txt_path": str(txt_path)}
        except Exception as e:
            logger.error("保存歌词失败: %s", e)
            return {"error": str(e)}

    # ================================================================
    # 静态工具
    # ================================================================

    @staticmethod
    def _strip_lrc_timestamps(lrc_text: str) -> str:
        lines = []
        for line in lrc_text.strip().split("\n"):
            clean = re.sub(r"\[\d{2}:\d{2}(?:\.\d{2,3})?\]", "", line).strip()
            if clean and len(clean) > 1:
                lines.append(clean)
        return "\n".join(lines)

    @staticmethod
    def _safe_filename(name: str, max_len: int = 100) -> str:
        safe = re.sub(r'[\\/*?:"<>|]', "_", name)
        safe = safe.strip().strip(".")
        if len(safe) > max_len:
            safe = safe[:max_len].rstrip("_")
        return safe or "unknown"

    @staticmethod
    def _guess_ext(url: str) -> str:
        path = urlparse(url).path.lower()
        for ext in (".flac", ".mp3", ".ogg", ".m4a", ".aac", ".wav", ".wma"):
            if ext in path:
                return ext
        return ".mp3"

    @staticmethod
    def _format_size(size: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}TB"
