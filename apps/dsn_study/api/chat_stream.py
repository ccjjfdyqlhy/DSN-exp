# apps/dsn_study/api/chat_stream.py
# 流式对话 API — CLI（apps/dsn/CLI）兼容层。
#
# dsn_study 引擎（StudyEngine.chat_audio）是非流式一次成型；CLI 走的是
# /api/chat/stream_send 的 SSE 协议（与 apps/dsn/api/app.py 同形）。
# 本蓝图把一次成型的结果包装成 CLI 认识的最小事件序列：
#   text_ready → line(带 TTS 音频) → completed → [DONE]
#
# 语音输入：/api/asr/passthrough 由 api/asr.py 提供（FunASR sidecar），
# 本蓝图只负责 /api/chat/stream_send。

from __future__ import annotations

import json
import logging

from flask import Blueprint, Response, g, jsonify, request

logger = logging.getLogger("ChatStream")

chat_stream_bp = Blueprint("chat_stream_api", __name__)

_auth_manager = None
_engine_getter = None


def init_chat_stream_api(auth_manager, engine_getter):
    global _auth_manager, _engine_getter
    _auth_manager = auth_manager
    _engine_getter = engine_getter


@chat_stream_bp.before_request
def _require_auth():
    if not _auth_manager:
        return jsonify({"error": "Auth unavailable"}), 503
    user = _auth_manager.authenticate(request)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    g.user = user


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@chat_stream_bp.route("/api/chat/stream_send", methods=["POST"])
def stream_send():
    engine = _engine_getter() if _engine_getter else None
    if engine is None:
        return jsonify({"error": "Engine not ready"}), 503

    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    image = (data.get("image_data") or data.get("image") or "").strip()
    if not message and not image:
        return jsonify({"error": "Missing message"}), 400

    tts_enabled = bool(data.get("tts_enabled", True))
    user_id = g.user.get("uid", 0) or 1

    def generate():
        try:
            if tts_enabled:
                # chat_audio = chat + TTS 合成（TTS 失败自动降级纯文本）
                result = engine.chat_audio(message, user_id=user_id, image=image or None)
                reply = result.get("reply", "")
                audio = result.get("audio_b64") or ""
                tts_error = result.get("tts_error", "")
            else:
                reply = engine.chat(message, user_id=user_id, image=image or None)
                audio, tts_error = "", ""
        except Exception as e:  # noqa: BLE001
            logger.exception("流式对话处理失败")
            yield _sse({"status": "tool_error", "tool": "chat", "error": str(e)})
            yield _sse({"status": "completed"})
            yield "data: [DONE]\n\n"
            return

        if reply:
            yield _sse({"status": "text_ready", "reply": reply, "chat_id": None})
        if audio:
            yield _sse({"status": "line", "index": 0, "total": 1,
                        "text": reply, "audio_b64": audio})
        if tts_error:
            yield _sse({"status": "tool_error", "tool": "tts", "error": tts_error})
        yield _sse({"status": "completed"})
        yield "data: [DONE]\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
