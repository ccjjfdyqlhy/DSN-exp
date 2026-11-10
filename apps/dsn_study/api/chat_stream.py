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
        """流式对话（方案 D）：文本增量 + 逐句音频。

        事件：text_delta / line / text_ready / tool_error / completed。
        text_ready 在末尾补发一次完整文本，兼容只认它的旧客户端。
        """
        tts_err = ""
        try:
            if tts_enabled and hasattr(engine, "chat_stream_audio"):
                for ev in engine.chat_stream_audio(
                        message, user_id=user_id, image=image or None):
                    etype = ev.get("type")
                    if etype == "text_delta":
                        yield _sse({"status": "text_delta",
                                    "text": ev.get("text", "")})
                    elif etype == "audio":
                        yield _sse({"status": "line",
                                    "index": ev.get("index", 0),
                                    "total": None,
                                    "text": ev.get("text", ""),
                                    "audio_b64": ev.get("audio_b64", "")})
                    elif etype in ("tool_call", "tool_result"):
                        yield _sse({"status": etype,
                                    "name": ev.get("name", ""),
                                    "arguments": ev.get("arguments"),
                                    "success": ev.get("success")})
                    elif etype == "error":
                        if ev.get("scope") == "tts":
                            tts_err = ev.get("error", "")
                    elif etype == "done":
                        reply = ev.get("reply", "")
                        if reply:
                            yield _sse({"status": "text_ready",
                                        "reply": reply, "chat_id": None})
                        if ev.get("tts_error"):
                            tts_err = ev["tts_error"]
            else:
                if tts_enabled:
                    # 退化：一次性合成（无流式引擎时）
                    result = engine.chat_audio(message, user_id=user_id,
                                               image=image or None)
                    reply = result.get("reply", "")
                    audio = result.get("audio_b64") or ""
                    tts_err = result.get("tts_error", "")
                else:
                    reply = engine.chat(message, user_id=user_id,
                                        image=image or None)
                    audio, tts_err = "", ""
                if reply:
                    yield _sse({"status": "text_ready", "reply": reply,
                                "chat_id": None})
                if audio:
                    yield _sse({"status": "line", "index": 0, "total": 1,
                                "text": reply, "audio_b64": audio})
        except Exception as e:  # noqa: BLE001
            logger.exception("流式对话处理失败")
            yield _sse({"status": "tool_error", "tool": "chat", "error": str(e)})
        finally:
            if tts_err:
                yield _sse({"status": "tool_error", "tool": "tts",
                            "error": tts_err})
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
