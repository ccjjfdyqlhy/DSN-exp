# apps/dsn_study/api/voice.py
# 语音子系统控制 API —— 让运维/前端能查看与启停 TTS 资源。
#
#   GET  /api/voice/status  语音状态（是否可用 / profile / 资源池快照）
#   POST /api/voice/start   启动 TTS 服务（托管模式；后台线程执行，立即返回）
#   POST /api/voice/stop    停止 TTS 服务（adopt 模式下不会杀外部进程）

from __future__ import annotations

import logging
import threading

from flask import Blueprint, jsonify, request, g

logger = logging.getLogger("VoiceAPI")

voice_bp = Blueprint("voice_api", __name__)

_voice = None
_auth_manager = None


def init_voice_api(voice, auth_manager):
    global _voice, _auth_manager
    _voice = voice
    _auth_manager = auth_manager


@voice_bp.before_request
def _require_auth():
    if not _auth_manager:
        return jsonify({"error": "Auth unavailable"}), 503
    user = _auth_manager.authenticate(request)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    g.user = user


@voice_bp.route("/api/voice/status", methods=["GET"])
def voice_status():
    """语音子系统状态。"""
    if _voice is None:
        return jsonify({"enabled": False, "reason": "语音子系统未初始化"}), 200
    return jsonify(_voice.status())


@voice_bp.route("/api/voice/start", methods=["POST"])
def voice_start():
    """启动 TTS 服务（后台线程；加载权重耗时分钟级，立即返回 running）。"""
    if _voice is None:
        return jsonify({"error": "语音子系统未初始化"}), 503
    if not _voice.available:
        return jsonify({"error": "语音不可用", "reason": _voice.disabled_reason}), 400

    def _run():
        try:
            _voice.warmup()
        except Exception as e:
            logger.warning("TTS 启动失败: %s", e)

    threading.Thread(target=_run, daemon=True, name="tts-start").start()
    return jsonify({"status": "starting"}), 202


@voice_bp.route("/api/voice/stop", methods=["POST"])
def voice_stop():
    """停止 TTS 服务（adopt 模式下不杀外部进程）。"""
    if _voice is None:
        return jsonify({"error": "语音子系统未初始化"}), 503
    from apps.dsn_study.models.resource_setup import TTS_RESOURCE, get_study_pool
    pool = get_study_pool()
    if pool is None:
        return jsonify({"error": "资源池未初始化"}), 503
    ok = pool.stop_resource(TTS_RESOURCE)
    return jsonify({"stopped": bool(ok)}), 200
