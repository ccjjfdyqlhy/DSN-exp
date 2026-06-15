# skills/builtin/ncm_music/tools/ncm_api.py
# NCMApi — 网易云音乐 API 封装 + 歌曲/歌词下载

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

import requests

logger = logging.getLogger("NCMApi")

API_BASE = "https://api.vkeys.cn"

QUALITY_NAMES: dict[int, str] = {
    1: "标准 64k",
    2: "标准 128k",
    3: "HQ 192k",
    4: "HQ 320k",
    5: "SQ 无损",
    6: "Hi-Res 高解析",
    7: "高清臻音 Spatial",
    8: "沉浸环绕声 Surround",
    9: "超清母带 Master",
}

DEFAULT_QUALITY = 4

_THIS_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_MUSIC_DIR = _THIS_DIR / "music"


class NCMApi:
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.base_url = self.config.get("api_base", API_BASE)
        self.timeout = self.config.get("timeout", 15)
        self.default_quality = self.config.get("default_quality", DEFAULT_QUALITY)
        self._music_dir = Path(self.config.get("music_dir", str(_DEFAULT_MUSIC_DIR)))
        self._music_dir.mkdir(parents=True, exist_ok=True)
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Referer": "https://music.163.com/",
        })
        logger.info("NCMApi 初始化: base_url=%s music_dir=%s", self.base_url, self._music_dir)

    # ================================================================
    # 公开工具方法
    # ================================================================

    def search_song(
        self,
        keyword: str,
        page: int = 1,
        num: int = 5,
        quality: int = None,
        auto_download: bool = False,
    ) -> dict:
        """
        搜索歌曲，返回歌曲列表（含元数据，不含播放链接，需用 get_song_url 获取）。

        :param keyword: 搜索关键词（歌名/歌手/专辑）
        :param page: 页数，默认 1
        :param num: 每页数量，默认 5
        :param quality: 音质（搜索时仅 metadata，实际下载音质在 get_song_url 中指定）
        :param auto_download: 是否自动获取第一首的播放链接
        :return: {"success": bool, "songs": [...], "total": int}
        """
        if not keyword or not keyword.strip():
            return {"success": False, "error": "关键词不能为空"}

        kw = keyword.strip()
        logger.info("搜索歌曲: keyword=%s page=%d num=%d", kw, page, num)

        songs = self._do_search(kw, page, num)

        if songs is None:
            return {"success": False, "error": "音乐服务连接失败或返回异常"}

        result = {
            "success": True,
            "songs": songs,
            "total": len(songs),
            "page": page,
        }

        if auto_download and songs:
            url_result = self._fetch_song_url_by_keyword(kw, choose=1, quality=quality or self.default_quality)
            if url_result.get("url"):
                song = songs[0]
                song["url"] = url_result["url"]
                song["quality"] = url_result.get("quality", song.get("quality", ""))
                song["size"] = url_result.get("size", "")
                dl = self._download_song_file(song)
                if dl["success"]:
                    result["downloaded"] = dl
                else:
                    result["download_error"] = dl.get("error")

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
        获取歌曲播放链接。优先用 keyword+choose，fallback 用 id。

        :param song_id: 歌曲 ID（用于标识，实际 API 用 keyword+choose 取链接）
        :param keyword: 搜索关键词（用于 word+choose 模式获取URL）
        :param choose: 选择第几首（1-indexed），默认 1
        :param quality: 音质 1-9
        :param download: 是否下载到本地
        :return: {"success": bool, "song": {...}, ...}
        """
        q = quality or self.default_quality

        if keyword:
            url_data = self._fetch_song_url_by_keyword(keyword, choose, q)
        elif song_id:
            url_data = self._fetch_song_url_by_keyword(str(song_id), 1, q)
        else:
            return {"success": False, "error": "至少需要 song_id 或 keyword 参数"}

        if not url_data or not url_data.get("id"):
            return {"success": False, "error": "获取歌曲信息失败，请确认歌曲存在"}

        song = url_data
        has_url = bool(song.get("url"))

        result = {
            "success": True,
            "song": song,
            "has_playable_url": has_url,
        }

        if not has_url:
            song["url"] = None
            result["note"] = "该歌曲当前无可播放链接（可能受版权保护或API限制）"

        if download and has_url:
            dl = self._download_song_file(song)
            result["downloaded"] = dl

        logger.info("获取歌曲链接: id=%d name=%s has_url=%s", song.get("id", 0), song.get("name", "?"), has_url)
        return result

    def get_lyrics(
        self,
        song_id: int,
        save: bool = False,
    ) -> dict:
        """
        获取歌词。

        :param song_id: 歌曲 ID
        :param save: 是否保存歌词到本地文件
        :return: {"success": bool, "data": {"lrc": str, "plain": str, "song_id": int}, ...}
        """
        logger.info("获取歌词: id=%d save=%s", song_id, save)
        try:
            params = {"id": song_id}
            resp = self._session.get(
                f"{self.base_url}/v2/music/netease/lyric",
                params=params, timeout=self.timeout
            )
            resp.raise_for_status()
            raw = resp.json()
        except requests.RequestException as e:
            logger.error("获取歌词网络错误: %s", e)
            return {"success": False, "error": f"歌词服务连接失败: {e}"}
        except json.JSONDecodeError:
            return {"success": False, "error": "歌词服务返回格式异常"}

        if raw.get("code") != 200:
            return {"success": False, "error": raw.get("message", "获取歌词失败")}

        lrc_data = raw.get("data", {})
        lrc_text = lrc_data.get("lrc", "")
        plain = self._strip_lrc_timestamps(lrc_text)

        result = {
            "success": True,
            "data": {
                "song_id": song_id,
                "lrc": lrc_text,
                "plain": plain,
                "line_count": len(plain.strip().split("\n")) if plain.strip() else 0,
            },
        }

        if save and plain.strip():
            saved = self._save_lyrics(song_id, lrc_text, plain)
            result["saved_to"] = saved

        return result

    def list_downloaded(self) -> dict:
        """列出已下载的歌曲和歌词文件"""
        songs = []
        lyrics = []
        try:
            for f in sorted(self._music_dir.iterdir()):
                if f.is_dir():
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
    # API 调用
    # ================================================================

    def _do_search(self, keyword: str, page: int, num: int) -> list[dict] | None:
        """搜索歌曲，返回标准化歌曲列表（仅元数据，无URL）"""
        try:
            params = {"word": keyword, "page": page, "num": num}
            resp = self._session.get(
                f"{self.base_url}/v2/music/netease",
                params=params, timeout=self.timeout
            )
            resp.raise_for_status()
            raw = resp.json()
        except requests.RequestException as e:
            logger.error("搜索网络错误: %s", e)
            return None
        except json.JSONDecodeError:
            return None

        if raw.get("code") != 200:
            logger.warning("搜索返回非200: code=%s msg=%s", raw.get("code"), raw.get("message"))
            return None

        data = raw.get("data")
        if isinstance(data, list):
            return [self._normalize_song(item) for item in data]
        if isinstance(data, dict) and "id" in data:
            return [self._normalize_song(data)]
        return []

    def _fetch_song_url_by_keyword(self, keyword: str, choose: int, quality: int) -> dict | None:
        """
        用 word+choose 模式获取带播放链接的单首歌曲。
        这是获取 URL 的主要方式（ID 查询不稳定）。
        """
        try:
            params = {"word": keyword, "choose": choose, "quality": quality}
            resp = self._session.get(
                f"{self.base_url}/v2/music/netease",
                params=params, timeout=self.timeout
            )
            resp.raise_for_status()
            raw = resp.json()
        except requests.RequestException as e:
            logger.error("获取URL网络错误: %s", e)
            return None
        except json.JSONDecodeError:
            return None

        if raw.get("code") != 200:
            logger.warning("获取URL返回非200: code=%s msg=%s", raw.get("code"), raw.get("message"))
            return None

        data = raw.get("data")
        if isinstance(data, dict):
            return self._normalize_song(data)
        if isinstance(data, list) and data:
            return self._normalize_song(data[0])
        return None

    # ================================================================
    # 数据标准化
    # ================================================================

    def _normalize_song(self, item: dict) -> dict:
        return {
            "id": item.get("id", 0),
            "name": item.get("song", item.get("name", "未知")),
            "singer": item.get("singer", item.get("artist", "")),
            "album": item.get("album", ""),
            "duration": item.get("interval", item.get("duration", "")),
            "cover": item.get("cover", ""),
            "quality": item.get("quality", ""),
            "size": item.get("size", ""),
            "kbps": item.get("kbps", ""),
            "url": item.get("url"),
            "link": item.get("link", ""),
            "release_time": item.get("time", ""),
        }

    # ================================================================
    # 文件下载
    # ================================================================

    def _download_song_file(self, song: dict) -> dict:
        """下载歌曲文件到本地 music 目录"""
        url = song.get("url")
        if not url:
            return {"success": False, "error": "无可用的播放链接"}

        name = song.get("name", "unknown")
        singer = song.get("singer", "")
        ext = self._guess_ext(url)
        safe_name = self._safe_filename(f"{singer} - {name}" if singer else name)
        filepath = self._music_dir / f"{safe_name}{ext}"

        if filepath.exists():
            logger.info("歌曲已存在，跳过下载: %s", filepath.name)
            return {"success": True, "path": str(filepath), "filename": filepath.name,
                    "existed": True, "size": filepath.stat().st_size}

        logger.info("开始下载: %s (%s)", safe_name, url[:60])
        try:
            resp = self._session.get(url, timeout=180, stream=True)
            resp.raise_for_status()
            downloaded = 0
            with open(filepath, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
            size_human = self._format_size(downloaded)
            logger.info("下载完成: %s (%s)", filepath.name, size_human)
            return {
                "success": True, "path": str(filepath), "filename": filepath.name,
                "size": downloaded, "size_human": size_human,
            }
        except requests.RequestException as e:
            logger.error("下载失败: %s", e)
            if filepath.exists():
                filepath.unlink()
            return {"success": False, "error": f"下载失败: {e}"}

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
            clean = re.sub(r'\[\d{2}:\d{2}(?:\.\d{2,3})?\]', '', line).strip()
            if clean and len(clean) > 1:
                lines.append(clean)
        return "\n".join(lines)

    @staticmethod
    def _safe_filename(name: str, max_len: int = 100) -> str:
        safe = re.sub(r'[\\/*?:"<>|]', '_', name)
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
