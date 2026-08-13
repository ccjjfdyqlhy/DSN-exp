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

# pyncm 搜索类型常量
SEARCH_TYPE: dict[str, int] = {
    "song": 1, "album": 10, "artist": 100, "playlist": 1000,
    "user": 1002, "mv": 1004, "lyrics": 1006, "dj": 1009, "video": 1014,
}

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

_SESSION_FILE = ".pyncm_session"


class NCMApi:
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.timeout = self.config.get("timeout", 30)
        self.default_quality = self.config.get("default_quality", DEFAULT_QUALITY)
        self._uid = self.config.get("default_user_id", 1)

        # pyncm session 管理
        self._session_loaded = False
        self._try_restore_session()

        logger.info("NCMApi 初始化 (default_uid=%d)", self._uid)

    # ── 工作区音乐目录（按用户隔离）──

    @staticmethod
    def _get_music_dir(uid: int) -> Path:
        """返回 workspace/<user>/music/ 目录，自动创建"""
        try:
            from apps.dsn.utils.workspace import get_workspace_manager
            wm = get_workspace_manager()
            return wm.user_music_dir(uid=uid)
        except Exception:
            # 回退：项目内目录
            p = Path(__file__).resolve().parent.parent / "music"
            p.mkdir(parents=True, exist_ok=True)
            return p

    # ================================================================
    # Session 管理
    # ================================================================

    def _session_path(self, uid: int = None) -> Path:
        return self._get_music_dir(uid or self._uid) / _SESSION_FILE

    def _try_restore_session(self):
        """尝试从文件恢复 pyncm 登录态，或通过 MUSIC_U 环境变量登录"""
        session_path = self._session_path()
        if session_path.exists():
            try:
                from apps.dsn.pyncm import loadSessionFromString, setCurrentSession
                data = session_path.read_text().strip()
                if data:
                    setCurrentSession(loadSessionFromString(data))
                    from apps.dsn.pyncm import apis
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
                from apps.dsn.config import Config
                music_u = getattr(Config, "NCM_MUSIC_U", "") or ""
            except Exception:
                logger.warning("Get operation failed", exc_info=True)
        if not music_u:
            music_u = self.config.get("music_u", "")
        if music_u:
            self._login_by_cookie(music_u)
            return

        logger.warning("未配置 MUSIC_U，NCM 功能可能受限。设置 NCM_MUSIC_U 环境变量或配置文件中的 music_u")

    def _login_by_cookie(self, music_u: str, uid: int = None):
        """用 MUSIC_U cookie 登录并保存 session"""
        uid = uid or self._uid
        try:
            from apps.dsn.pyncm import apis, dumpSessionAsString, getCurrentSession, setCurrentSession
            r = apis.login.loginViaCookie(MUSIC_U=music_u)
            if r.get("code") == 200:
                r2 = apis.login.getCurrentLoginStatus()
                if r2.get("code") == 200 and r2.get("account"):
                    session_path = self._session_path(uid)
                    session_path.parent.mkdir(parents=True, exist_ok=True)
                    session_path.write_text(dumpSessionAsString(getCurrentSession()))
                    self._session_loaded = True
                    logger.info("MUSIC_U 登录成功，session 已保存到 %s", session_path)
                    return
            logger.warning("MUSIC_U 登录失败: %s", r)
        except Exception as e:
            logger.error("MUSIC_U 登录异常: %s", e)

    def _ensure_logged_in(self) -> bool:
        """确保已登录，未登录时打日志但继续（只读操作可用）"""
        if self._session_loaded:
            return True
        self._try_restore_session()
        return self._session_loaded

    def _save_session(self, uid: int = None):
        """持久化当前登录态"""
        try:
            from apps.dsn.pyncm import dumpSessionAsString, getCurrentSession
            p = self._session_path(uid)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(dumpSessionAsString(getCurrentSession()))
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

    def login(self, music_u: str, user_id: int = 0) -> dict:
        """
        用 MUSIC_U Cookie 登录网易云音乐。

        :param music_u: 从浏览器 Cookie 获取的 MUSIC_U 值
        :param user_id: 用户 ID，默认自动取当前用户
        """
        if not music_u or not music_u.strip():
            return {"success": False, "error": "MUSIC_U 不能为空"}
        music_u = music_u.strip()
        uid = user_id or self._uid
        logger.info("login: 通过 MUSIC_U 登录 (uid=%d)", uid)

        from apps.dsn.pyncm import apis, dumpSessionAsString, getCurrentSession, setCurrentSession
        try:
            r = apis.login.loginViaCookie(MUSIC_U=music_u)
            if r.get("code") != 200:
                return {"success": False, "error": f"登录失败: {r.get('message', '未知错误')}"}
            r2 = apis.login.getCurrentLoginStatus()
            if r2.get("code") != 200 or not r2.get("account"):
                return {"success": False, "error": "登录验证失败"}
            session_path = self._session_path(uid)
            session_path.parent.mkdir(parents=True, exist_ok=True)
            session_path.write_text(dumpSessionAsString(getCurrentSession()))
            self._session_loaded = True
            nickname = r2.get("profile", {}).get("nickname", "?")
            logger.info("登录成功: %s (uid=%d)", nickname, uid)
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
        user_id: int = 0,
    ) -> dict:
        """
        搜索歌曲，返回歌曲列表（含元数据）。

        :param keyword: 搜索关键词（歌名/歌手/专辑）
        :param page: 页数，默认 1
        :param num: 每页数量，默认 5
        :param quality: 音质
        :param auto_download: 是否自动下载第一首
        :param user_id: 用户 ID，默认当前用户
        """
        if not keyword or not keyword.strip():
            return {"success": False, "error": "关键词不能为空"}

        uid = user_id or self._uid
        kw = keyword.strip()
        logger.info("搜索歌曲: keyword=%s page=%d num=%d uid=%d", kw, page, num, uid)

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
                    music_dir = self._get_music_dir(uid)
                    dl = self._download_song_file(song_meta.get("name", songs[0].get("name", "unknown")),
                                                  song_meta.get("artist", ""),
                                                  song_meta.get("url", ""),
                                                  song_meta.get("ext", ".mp3"),
                                                  music_dir)
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
        user_id: int = 0,
    ) -> dict:
        """
        获取歌曲播放链接。

        :param song_id: 歌曲 ID
        :param keyword: 搜索关键词（当 song_id=0 时用 keyword 搜索取第 choose 首）
        :param choose: 选择搜索结果第几首
        :param quality: 音质 1-9
        :param download: 是否下载到本地
        :param user_id: 用户 ID，默认当前用户
        """
        uid = user_id or self._uid
        q = quality or self.default_quality
        song_id = int(song_id) if song_id else 0

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
            music_dir = self._get_music_dir(uid)
            dl = self._download_song_file(song.get("name", "unknown"),
                                          song.get("artist", ""),
                                          song["url"],
                                          song.get("ext", ".mp3"),
                                          music_dir)
            ret["downloaded"] = dl

        logger.info("获取歌曲链接: id=%d name=%s has_url=%s uid=%d",
                     song.get("id", 0), song.get("name", "?"), has_url, uid)
        return ret

    def get_lyrics(
        self,
        song_id: int,
        save: bool = True,
        user_id: int = 0,
    ) -> dict:
        """
        获取歌词。

        :param song_id: 歌曲 ID
        :param save: 是否保存歌词到本地文件
        :param user_id: 用户 ID，默认当前用户
        """
        uid = user_id or self._uid
        logger.info("获取歌词: id=%d save=%s uid=%d", song_id, save, uid)
        self._ensure_logged_in()

        try:
            from apps.dsn.pyncm import apis
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
            music_dir = self._get_music_dir(uid)
            saved = self._save_lyrics(song_id, lrc_str, plain, music_dir)
            result["saved_to"] = saved

        return result

    def music_control(self, action: str, value: str = None, user_id: int = 0) -> dict:
        """
        控制音乐播放器。后端维护共享状态，minimal.py 轮询消费。

        :param action: play(传filename) / pause / resume / stop / next / prev / volume(传0.0~1.0) / status / list
        :param value: play 时传文件名，volume 时传 0.0~1.0，其余留空
        :param user_id: 用户 ID，默认当前用户
        """
        from apps.dsn.api.music_state import get_status, enqueue_control

        uid = user_id or self._uid
        logger.info("music_control: action=%s value=%s uid=%d", action, value, uid)

        if action == "status":
            return get_status(consume=False)

        if action == "list":
            music_dir = self._get_music_dir(uid)
            files = []
            try:
                for f in sorted(music_dir.iterdir()):
                    if f.is_file() and f.suffix.lower() in (".mp3", ".flac", ".wav", ".ogg", ".m4a", ".aac", ".wma"):
                        files.append({"filename": f.name, "size": f.stat().st_size})
            except FileNotFoundError:
                pass
            return {"success": True, "files": files, "total": len(files), "state": get_status(consume=False)}

        return enqueue_control(action, value)

    def list_downloaded(self, user_id: int = 0) -> dict:
        """列出已下载的歌曲和歌词文件"""
        uid = user_id or self._uid
        music_dir = self._get_music_dir(uid)
        songs = []
        lyrics = []
        try:
            for f in sorted(music_dir.iterdir()):
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
        except FileNotFoundError:
            pass  # 目录尚未创建，没有文件
        except Exception as e:
            logger.error("列出已下载文件失败: %s", e)
            return {"success": False, "error": str(e)}

        logger.info("已下载: %d 首歌, %d 份歌词 (uid=%d, dir=%s)",
                     len(songs), len(lyrics), uid, music_dir)
        return {
            "success": True,
            "songs": songs,
            "lyrics": lyrics,
            "total_songs": len(songs),
            "total_lyrics": len(lyrics),
        }

    # ================================================================
    # 新增 pyncm 工具方法
    # ================================================================

    def search(
        self,
        keyword: str,
        search_type: str = "song",
        page: int = 1,
        num: int = 10,
    ) -> dict:
        """
        通用搜索（歌曲/专辑/歌手/歌单/用户/MV/歌词/DJ/视频）。

        :param keyword: 搜索关键词
        :param search_type: 类型: song / album / artist / playlist / user / mv / lyrics / dj / video
        :param page: 页数，默认 1
        :param num: 每页数量，默认 10
        """
        if not keyword or not keyword.strip():
            return {"success": False, "error": "关键词不能为空"}
        stype = SEARCH_TYPE.get(search_type, SEARCH_TYPE["song"])
        self._ensure_logged_in()
        try:
            from apps.dsn.pyncm import apis
            raw = apis.cloudsearch.getSearchResult(
                keyword.strip(), stype=stype, limit=num, offset=(page - 1) * num
            )
        except Exception as e:
            logger.error("搜索异常: %s", e)
            return {"success": False, "error": f"搜索失败: {e}"}

        if raw.get("code") != 200:
            return {"success": False, "error": raw.get("message", "搜索失败")}

        result = raw.get("result", {})
        items = []
        if search_type == "song":
            for s in result.get("songs", []):
                items.append(self._normalize_song(s))
        elif search_type == "album":
            for a in result.get("albums", []):
                items.append(self._normalize_album(a))
        elif search_type == "artist":
            for a in result.get("artists", []):
                items.append(self._normalize_artist(a))
        elif search_type == "playlist":
            for p in result.get("playlists", []):
                items.append(self._normalize_playlist(p))
        elif search_type == "user":
            for u in result.get("users", []):
                items.append(self._normalize_user(u))
        elif search_type == "mv":
            for m in result.get("mvs", []):
                items.append(self._normalize_mv(m))
        elif search_type == "video":
            for v in result.get("videos", []):
                items.append(self._normalize_video(v))
        elif search_type == "dj":
            for d in result.get("djRadios", []):
                items.append(self._normalize_dj(d))
        elif search_type == "lyrics":
            for lr in result.get("lyrics", []):
                items.append({"id": lr.get("id", 0), "name": lr.get("name", "")})

        return {
            "success": True,
            "type": search_type,
            "items": items,
            "total": len(items),
            "page": page,
            "has_more": result.get("hasMore", False),
        }

    def get_album(self, album_id: int) -> dict:
        """获取专辑详情（含曲目列表）。

        :param album_id: 专辑 ID
        """
        self._ensure_logged_in()
        try:
            from apps.dsn.pyncm import apis
            raw = apis.album.getAlbumInfo(str(album_id))
        except Exception as e:
            return {"success": False, "error": f"获取专辑失败: {e}"}
        if raw.get("code") != 200:
            return {"success": False, "error": raw.get("message", "获取专辑失败")}
        album = raw.get("album", {}) or {}
        songs = [self._normalize_song(s) for s in album.get("songs", [])]
        return {
            "success": True,
            "album": self._normalize_album(album),
            "songs": songs,
            "total_songs": len(songs),
        }

    def get_artist(self, artist_id: int) -> dict:
        """获取歌手详情。

        :param artist_id: 歌手 ID
        """
        self._ensure_logged_in()
        try:
            from apps.dsn.pyncm import apis
            raw = apis.artist.getArtistDetails(str(artist_id))
        except Exception as e:
            return {"success": False, "error": f"获取歌手信息失败: {e}"}
        if raw.get("code") != 200:
            return {"success": False, "error": raw.get("message", "获取歌手信息失败")}
        data = raw.get("data", {}) or {}
        return {
            "success": True,
            "artist": self._normalize_artist(data),
        }

    def get_artist_albums(self, artist_id: int, page: int = 1, num: int = 50) -> dict:
        """获取歌手的专辑列表。

        :param artist_id: 歌手 ID
        :param page: 页数，默认 1
        :param num: 每页数量，默认 50
        """
        self._ensure_logged_in()
        try:
            from apps.dsn.pyncm import apis
            raw = apis.artist.getArtistAlbums(str(artist_id), offset=(page - 1) * num, limit=num)
        except Exception as e:
            return {"success": False, "error": f"获取专辑列表失败: {e}"}
        if raw.get("code") != 200:
            return {"success": False, "error": raw.get("message", "获取专辑列表失败")}
        albums = [self._normalize_album(a) for a in (raw.get("hotAlbums", []) or raw.get("albums", []))]
        return {
            "success": True,
            "albums": albums,
            "total": len(albums),
        }

    def get_artist_tracks(
        self, artist_id: int, page: int = 1, num: int = 50, order: str = "hot"
    ) -> dict:
        """获取歌手的热门/最新歌曲。

        :param artist_id: 歌手 ID
        :param page: 页数，默认 1
        :param num: 每页数量，默认 50
        :param order: 'hot' 热门 / 'time' 最新，默认 hot
        """
        self._ensure_logged_in()
        try:
            from apps.dsn.pyncm import apis
            raw = apis.artist.getArtistTracks(str(artist_id), offset=(page - 1) * num, limit=num, order=order)
        except Exception as e:
            return {"success": False, "error": f"获取歌曲列表失败: {e}"}
        if raw.get("code") != 200:
            return {"success": False, "error": raw.get("message", "获取歌曲列表失败")}
        songs = [self._normalize_song(s) for s in (raw.get("songs", []) or raw.get("hotSongs", []))]
        return {
            "success": True,
            "songs": songs,
            "total": len(songs),
            "order": order,
        }

    def get_playlist(self, playlist_id: int) -> dict:
        """获取歌单详情。

        :param playlist_id: 歌单 ID
        """
        self._ensure_logged_in()
        try:
            from apps.dsn.pyncm import apis
            raw = apis.playlist.getPlaylistInfo(str(playlist_id))
        except Exception as e:
            return {"success": False, "error": f"获取歌单失败: {e}"}
        if raw.get("code") != 200:
            return {"success": False, "error": raw.get("message", "获取歌单失败")}
        pl = raw.get("playlist", {}) or {}
        return {
            "success": True,
            "playlist": self._normalize_playlist(pl),
        }

    def get_playlist_tracks(
        self, playlist_id: int, offset: int = 0, limit: int = 200
    ) -> dict:
        """获取歌单内的所有歌曲。

        :param playlist_id: 歌单 ID
        :param offset: 偏移，默认 0
        :param limit: 获取数量，默认 200
        """
        self._ensure_logged_in()
        try:
            from apps.dsn.pyncm import apis
            raw = apis.playlist.getPlaylistAllTracks(str(playlist_id), offset=offset, limit=limit)
        except Exception as e:
            return {"success": False, "error": f"获取歌单歌曲失败: {e}"}
        if raw.get("code") != 200:
            return {"success": False, "error": raw.get("message", "获取歌单歌曲失败")}
        songs = [self._normalize_song(s) for s in (raw.get("songs", []))]
        return {
            "success": True,
            "songs": songs,
            "total": len(songs),
        }

    def create_playlist(self, name: str, private: bool = False) -> dict:
        """创建新歌单。

        :param name: 歌单名称
        :param private: 是否设为隐私歌单，默认 false
        """
        self._ensure_logged_in()
        try:
            from apps.dsn.pyncm import apis
            raw = apis.playlist.setCreatePlaylist(name, privacy=private)
        except Exception as e:
            return {"success": False, "error": f"创建歌单失败: {e}"}
        if raw.get("code") != 200:
            return {"success": False, "error": raw.get("message", "创建歌单失败")}
        pl = raw.get("playlist", {}) or {}
        return {
            "success": True,
            "playlist": {"id": pl.get("id", 0), "name": pl.get("name", name)},
        }

    def add_to_playlist(self, playlist_id: int, track_ids: list) -> dict:
        """向歌单添加歌曲。

        :param playlist_id: 歌单 ID
        :param track_ids: 歌曲 ID 列表
        """
        self._ensure_logged_in()
        try:
            from apps.dsn.pyncm import apis
            raw = apis.playlist.setManipulatePlaylistTracks(track_ids, str(playlist_id), op="add")
        except Exception as e:
            return {"success": False, "error": f"添加歌曲失败: {e}"}
        if raw.get("code") != 200:
            return {"success": False, "error": raw.get("message", "添加歌曲失败")}
        return {
            "success": True,
            "playlist_id": playlist_id,
            "track_ids": track_ids,
            "count": len(track_ids),
        }

    def remove_from_playlist(self, playlist_id: int, track_ids: list) -> dict:
        """从歌单移除歌曲。

        :param playlist_id: 歌单 ID
        :param track_ids: 歌曲 ID 列表
        """
        self._ensure_logged_in()
        try:
            from apps.dsn.pyncm import apis
            raw = apis.playlist.setManipulatePlaylistTracks(track_ids, str(playlist_id), op="del")
        except Exception as e:
            return {"success": False, "error": f"移除歌曲失败: {e}"}
        if raw.get("code") != 200:
            return {"success": False, "error": raw.get("message", "移除歌曲失败")}
        return {
            "success": True,
            "playlist_id": playlist_id,
            "track_ids": track_ids,
        }

    def get_user_playlists(self, user_id: int = 0, page: int = 1, num: int = 50) -> dict:
        """获取用户的歌单列表。

        :param user_id: 用户 ID，默认当前登录用户
        :param page: 页数，默认 1
        :param num: 每页数量，默认 50
        """
        uid = user_id or self._uid
        self._ensure_logged_in()
        try:
            from apps.dsn.pyncm import apis
            raw = apis.user.getUserPlaylists(uid, offset=(page - 1) * num, limit=num)
        except Exception as e:
            return {"success": False, "error": f"获取用户歌单失败: {e}"}
        if raw.get("code") != 200:
            return {"success": False, "error": raw.get("message", "获取用户歌单失败")}
        playlists = [self._normalize_playlist(p) for p in (raw.get("playlist", []))]
        return {
            "success": True,
            "playlists": playlists,
            "total": len(playlists),
            "uid": uid,
        }

    def get_daily_recommend(self) -> dict:
        """获取每日推荐歌曲。"""
        self._ensure_logged_in()
        try:
            from apps.dsn.pyncm import apis
            raw = apis.user.getDailyRecommend()
        except Exception as e:
            return {"success": False, "error": f"获取每日推荐失败: {e}"}
        if raw.get("code") != 200:
            return {"success": False, "error": raw.get("message", "获取每日推荐失败")}
        songs = [self._normalize_song(s) for s in (raw.get("data", []) or raw.get("recommend", []))]
        return {
            "success": True,
            "songs": songs,
            "total": len(songs),
            "date": time.strftime("%Y-%m-%d"),
        }

    def get_user_detail(self, user_id: int = 0) -> dict:
        """获取用户资料详情。

        :param user_id: 用户 ID，默认当前登录用户
        """
        uid = user_id or self._uid
        self._ensure_logged_in()
        try:
            from apps.dsn.pyncm import apis
            raw = apis.user.getUserDetail(uid)
        except Exception as e:
            return {"success": False, "error": f"获取用户信息失败: {e}"}
        if raw.get("code") != 200:
            return {"success": False, "error": raw.get("message", "获取用户信息失败")}
        profile = raw.get("profile", {}) or {}
        return {
            "success": True,
            "user": self._normalize_user(profile),
        }

    def like_track(self, track_id: int, like: bool = True) -> dict:
        """喜欢/取消喜欢歌曲。

        :param track_id: 歌曲 ID
        :param like: true=喜欢，false=取消喜欢，默认 true
        """
        self._ensure_logged_in()
        try:
            from apps.dsn.pyncm import apis
            raw = apis.track.setLikeTrack(track_id, like=like, userid=self._uid)
        except Exception as e:
            return {"success": False, "error": f"操作失败: {e}"}
        if raw.get("code") != 200:
            return {"success": False, "error": raw.get("message", "操作失败")}
        return {
            "success": True,
            "track_id": track_id,
            "liked": like,
        }

    def get_track_comments(self, track_id: int, page: int = 1, num: int = 20) -> dict:
        """获取歌曲评论。

        :param track_id: 歌曲 ID
        :param page: 页数，默认 1
        :param num: 每页数量，默认 20
        """
        self._ensure_logged_in()
        try:
            from apps.dsn.pyncm import apis
            raw = apis.track.getTrackComments(track_id, offset=(page - 1) * num, limit=num)
        except Exception as e:
            return {"success": False, "error": f"获取评论失败: {e}"}
        if raw.get("code") != 200:
            return {"success": False, "error": raw.get("message", "获取评论失败")}
        comments = []
        for c in raw.get("comments", []):
            comments.append({
                "id": c.get("commentId", 0),
                "user": c.get("user", {}).get("nickname", "?"),
                "content": c.get("content", ""),
                "liked_count": c.get("likedCount", 0),
                "time": c.get("time", 0),
                "time_str": time.strftime("%Y-%m-%d %H:%M", time.localtime(c.get("time", 0) / 1000)) if c.get("time") else "",
            })
        return {
            "success": True,
            "comments": comments,
            "total": raw.get("total", len(comments)),
            "hot_comments": [{
                "id": c.get("commentId", 0),
                "user": c.get("user", {}).get("nickname", "?"),
                "content": c.get("content", ""),
                "liked_count": c.get("likedCount", 0),
            } for c in raw.get("hotComments", [])],
        }

    def get_personal_fm(self, limit: int = 3) -> dict:
        """获取私人 FM 推荐歌曲。

        :param limit: 获取数量，默认 3
        """
        self._ensure_logged_in()
        try:
            from apps.dsn.pyncm.apis.miniprograms import radio
            raw = radio.getMoreRadioContent(limit=limit)
        except Exception as e:
            return {"success": False, "error": f"获取私人 FM 失败: {e}"}
        if raw.get("code") != 200:
            return {"success": False, "error": raw.get("message", "获取私人 FM 失败")}
        songs = [self._normalize_song(s) for s in (raw.get("data", []))]
        return {
            "success": True,
            "songs": songs,
            "total": len(songs),
        }

    def skip_fm_track(self, track_id: int) -> dict:
        """跳过私人 FM 当前歌曲。

        :param track_id: 要跳过的歌曲 ID
        """
        self._ensure_logged_in()
        try:
            from apps.dsn.pyncm.apis.miniprograms import radio
            raw = radio.setSkipRadioContent(track_id)
        except Exception as e:
            return {"success": False, "error": f"跳过失败: {e}"}
        return {"success": raw.get("code") == 200, "track_id": track_id}

    def like_fm_track(self, track_id: int, like: bool = True) -> dict:
        """喜欢/取消喜欢私人 FM 歌曲。

        :param track_id: 歌曲 ID
        :param like: true=喜欢，false=取消喜欢，默认 true
        """
        self._ensure_logged_in()
        try:
            from apps.dsn.pyncm.apis.miniprograms import radio
            raw = radio.setLikeRadioContent(track_id, like=like)
        except Exception as e:
            return {"success": False, "error": f"操作失败: {e}"}
        return {"success": raw.get("code") == 200, "track_id": track_id, "liked": like}

    def get_mv(self, mv_id: int, resolution: int = 1080) -> dict:
        """获取 MV 详情和播放地址。

        :param mv_id: MV ID
        :param resolution: 分辨率 240/480/720/1080，默认 1080
        """
        self._ensure_logged_in()
        try:
            from apps.dsn.pyncm import apis
            detail_raw = apis.video.getMVDetail(str(mv_id))
            url_raw = apis.video.getMVResource(str(mv_id), res=resolution)
        except Exception as e:
            return {"success": False, "error": f"获取 MV 失败: {e}"}
        if detail_raw.get("code") != 200:
            return {"success": False, "error": detail_raw.get("message", "获取 MV 详情失败")}
        data = detail_raw.get("data", {}) or {}
        mv_url = url_raw.get("data", {}) or {}
        return {
            "success": True,
            "mv": self._normalize_mv(data),
            "url": mv_url.get("url", ""),
            "resolution": resolution,
        }

    def daily_signin(self, type: str = "mobile") -> dict:
        """每日签到。

        :param type: 'mobile' 手机端(+4经验) / 'web' 网页端(+1经验)，默认 mobile
        """
        self._ensure_logged_in()
        dtype = 0 if type == "mobile" else 1
        try:
            from apps.dsn.pyncm import apis
            raw = apis.user.setSignin(dtype=dtype)
        except Exception as e:
            return {"success": False, "error": f"签到失败: {e}"}
        if raw.get("code") != 200:
            return {"success": False, "error": raw.get("message", "签到失败")}
        return {
            "success": True,
            "type": type,
        }

    def login_logout(self) -> dict:
        """退出当前网易云音乐登录。"""
        self._ensure_logged_in()
        try:
            from apps.dsn.pyncm import apis
            raw = apis.login.loginLogout()
        except Exception as e:
            return {"success": False, "error": f"退出登录失败: {e}"}
        if raw.get("code") != 200:
            return {"success": False, "error": raw.get("message", "退出登录失败")}
        # 删除本地 session 文件
        for p in [self._session_path(), self._session_path(self._uid)]:
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                logger.warning("Operation failed", exc_info=True)
        self._session_loaded = False
        return {"success": True}

    # ── 标准化辅助 ──




        # normalize album dict into standard format
    def _normalize_album(self, album: dict) -> dict:
        return {
            "id": album.get("id", 0),
            "name": album.get("name", "未知专辑"),
            "artist": album.get("artist", {}).get("name", "") or album.get("company", ""),
            "publish_time": album.get("publishTime", 0),
            "size": album.get("size", 0),
            "cover": album.get("picUrl", album.get("coverImgUrl", "")),
        }




        # normalize artist dict into standard format
    def _normalize_artist(self, artist: dict) -> dict:
        return {
            "id": artist.get("id", 0),
            "name": artist.get("name", "未知歌手"),
            "alias": ", ".join(artist.get("alias", []) or []),
            "pic_url": artist.get("picUrl", artist.get("img1v1Url", "")),
            "music_size": artist.get("musicSize", 0),
            "album_size": artist.get("albumSize", 0),
            "mv_size": artist.get("mvSize", 0),
            "brief_desc": artist.get("briefDesc", ""),
        }




        # normalize playlist dict into standard format
    def _normalize_playlist(self, pl: dict) -> dict:
        return {
            "id": pl.get("id", 0),
            "name": pl.get("name", "未知歌单"),
            "creator": pl.get("creator", {}).get("nickname", ""),
            "track_count": pl.get("trackCount", pl.get("total", 0)),
            "play_count": pl.get("playCount", 0),
            "cover": pl.get("coverImgUrl", ""),
            "description": (pl.get("description", "") or "")[:200],
            "tags": pl.get("tags", []),
        }




        # normalize user dict into standard format
    def _normalize_user(self, user: dict) -> dict:
        return {
            "id": user.get("userId", user.get("id", 0)),
            "nickname": user.get("nickname", "?"),
            "avatar": user.get("avatarUrl", ""),
            "signature": (user.get("signature", "") or "")[:200],
            "level": user.get("level", 0),
            "gender": {0: "未知", 1: "男", 2: "女"}.get(user.get("gender", 0), "未知"),
        }




        # normalize mv dict into standard format
    def _normalize_mv(self, mv: dict) -> dict:
        return {
            "id": mv.get("id", mv.get("mvId", 0)),
            "name": mv.get("name", mv.get("mvName", "未知 MV")),
            "artist": mv.get("artistName", mv.get("artist", {}).get("name", "")),
            "duration": mv.get("duration", mv.get("dt", 0)) // 1000,
            "cover": mv.get("cover", mv.get("imgurl", mv.get("picUrl", ""))),
            "play_count": mv.get("playCount", 0),
            "brief_desc": (mv.get("desc", "") or "")[:200],
        }




        # normalize video dict into standard format
    def _normalize_video(self, video: dict) -> dict:
        return {
            "id": video.get("vid", video.get("id", 0)),
            "title": video.get("title", "未知视频"),
            "creator": video.get("creator", [{}])[0].get("userName", "") if video.get("creator") else "",
            "duration": video.get("durationms", 0) // 1000,
            "cover": video.get("coverUrl", ""),
        }




        # normalize dj radio dict into standard format
    def _normalize_dj(self, dj: dict) -> dict:
        return {
            "id": dj.get("id", 0),
            "name": dj.get("name", "未知电台"),
            "dj": dj.get("dj", {}).get("nickname", ""),
            "category": dj.get("category", ""),
            "desc": (dj.get("desc", "") or "")[:200],
            "cover": dj.get("picUrl", ""),
        }

    # ================================================================
    # pyncm API 调用（内部）
    # ================================================================

    def _do_search(self, keyword: str, page: int, num: int) -> list[dict] | None:
        """搜索歌曲，返回标准化列表"""
        self._ensure_logged_in()
        try:
            from apps.dsn.pyncm import apis
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
            from apps.dsn.pyncm import apis
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




        # normalize a raw song dict into a standard format
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

    def _download_song_file(self, name: str, artist: str, url: str,
                            ext: str, music_dir: Path) -> dict:
        """下载歌曲文件到指定目录"""
        if not url:
            return {"success": False, "error": "无可用的播放链接"}

        music_dir.mkdir(parents=True, exist_ok=True)
        safe_name = self._safe_filename(f"{artist} - {name}" if artist else name)
        filepath = music_dir / f"{safe_name}{ext}"

        if filepath.exists():
            logger.info("歌曲已存在，跳过下载: %s", filepath.name)
            return {"success": True, "path": str(filepath), "filename": filepath.name,
                    "existed": True, "size": filepath.stat().st_size}

        logger.info("开始下载: %s", filepath.name)
        try:
            from apps.dsn.pyncm.utils.downloader import Downloader
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




        # save lrc and plain lyrics to files
    def _save_lyrics(self, song_id: int, lrc_text: str, plain_text: str,
                     music_dir: Path) -> dict:
        music_dir.mkdir(parents=True, exist_ok=True)
        sid = str(song_id)
        lrc_path = music_dir / f"{sid}.lrc"
        txt_path = music_dir / f"{sid}.txt"
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


        # strip timestamp markers from lrc text
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


        # sanitize a string for use as a filename
            if ext in path:
                return ext
        return ".mp3"

    @staticmethod
    def _format_size(size: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):


        # format byte size into human-readable string
            if size < 1024:
                return f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}TB"
