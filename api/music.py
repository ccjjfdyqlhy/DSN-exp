# api/music.py
# 音乐播放器 HTTP API — 文件服务 + 状态同步

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file, abort

from utils.workspace import get_workspace_manager
from .music_state import get_status, enqueue_control, update_state

logger = logging.getLogger("api.music")
music_bp = Blueprint("music", __name__)

AUDIO_EXTS = {".mp3", ".flac", ".wav", ".ogg", ".m4a", ".aac", ".wma"}


def _get_music_dir(uid: int) -> Path:
    wm = get_workspace_manager()
    return wm.user_music_dir(uid=uid)


def _format_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


@music_bp.route("/api/music/list", methods=["GET"])
def list_music():
    """列出用户 music/ 目录下的音频文件"""
    uid = request.args.get("uid", 1, type=int)
    music_dir = _get_music_dir(uid)
    files = []
    try:
        for f in sorted(music_dir.iterdir()):
            if f.is_file() and f.suffix.lower() in AUDIO_EXTS:
                files.append({
                    "filename": f.name,
                    "size": f.stat().st_size,
                    "size_human": _format_size(f.stat().st_size),
                })
    except FileNotFoundError:
        pass
    return jsonify({"success": True, "files": files, "total": len(files)})


@music_bp.route("/api/music/play/<path:filename>", methods=["GET"])
def serve_music(filename: str):
    """流式传输音频文件（支持 Range 头）"""
    uid = request.args.get("uid", 1, type=int)
    music_dir = _get_music_dir(uid)
    filepath = (music_dir / filename).resolve()
    if not str(filepath).startswith(str(music_dir.resolve())):
        abort(403, description="Path traversal denied")
    if not filepath.exists() or not filepath.is_file():
        abort(404, description="File not found")
    mime, _ = mimetypes.guess_type(str(filepath))
    return send_file(str(filepath), mimetype=mime or "audio/mpeg")


@music_bp.route("/api/music/status", methods=["GET"])
def get_playback_status():
    """返回当前播放状态 + 消费 pending_control（minimal.py 轮询用）"""
    consume = request.args.get("consume", "1") != "0"
    return jsonify(get_status(consume=consume))


@music_bp.route("/api/music/control", methods=["POST"])
def control_playback():
    """AI 调用：入队控制命令"""
    data = request.get_json(force=True) or {}
    action = data.get("action", "")
    value = data.get("value")
    if not action:
        return jsonify({"success": False, "error": "action is required"}), 400
    return jsonify(enqueue_control(action, value))


@music_bp.route("/api/music/state", methods=["POST"])
def report_state():
    """minimal.py 上报当前播放状态"""
    data = request.get_json(force=True) or {}
    update_state(data)
    return jsonify({"success": True})
