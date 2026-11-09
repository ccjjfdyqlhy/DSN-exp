# apps/dsn_study/api/asr.py
# 语音识别 API —— 两条路由，wire 契约与参考实现 apps/dsn/api/app.py:285-426
# **逐字段对齐**，使现有 DSN-CLI 客户端（apps/dsn/CLI/client.py:236-276）
# 不改一行代码即可对 dsn_study 使用。
#
#   POST /api/asr/recognize
#       multipart/form-data，字段 audio = 原始音频文件
#       200 {"text": "..."}
#       403 {"error": "ASR disabled"}
#       400 {"error": "Missing audio file"}
#       500 {"error": "ASR processing failed"}
#
#   POST /api/asr/passthrough
#       JSON {"audio_b64","chat_id","chat_name","sensing","tts_enabled",
#              "model_type","image_data"}
#       → SSE 流（事件语法与 api/chat_stream.py 一致：
#           text_ready → line(audio_b64) → completed → [DONE]）
#       → 若识别文本为空：**返回 JSON**（不是 SSE）
#           {"reply": "", "chat_id": <chat_id>, "filtered": true}
#       403 {"error": "ASR disabled"}
#       400 {"error": "Missing audio"}
#       400 {"error": "Invalid base64"}
#       500 {"error": "ASR processing failed"}
#
# 与参考实现的两点差异：
#   * 模型在独立 conda 环境的 sidecar 里（宿主 python 无 torch/funasr）；
#     路由层只负责取字节 → 归一化 → 调 ASRService。
#   * dsn 的 "sensing" 分支（空闲麦克风）dsn_study 未实现 —— 参数照收，
#     但不注入 sensing 提示词。

from __future__ import annotations

import base64
import json
import logging

from flask import Blueprint, Response, current_app, g, jsonify, request

logger = logging.getLogger("ASRAPI")

asr_bp = Blueprint("asr_api", __name__)

_asr = None
_auth_manager = None
_engine_getter = None


def init_asr_api(asr, auth_manager, engine_getter=None):
    """注入依赖（boot.py 启动时调用）。"""
    global _asr, _auth_manager, _engine_getter
    _asr = asr
    _auth_manager = auth_manager
    _engine_getter = engine_getter


@asr_bp.before_request
def _require_auth():
    if not _auth_manager:
        return jsonify({"error": "Auth unavailable"}), 503
    user = _auth_manager.authenticate(request)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    g.user = user


def _asr_enabled(default: bool) -> bool:
    """ASR 开关。默认值与参考实现一致：recognize 默认开、passthrough 默认关。"""
    try:
        return bool(current_app.config.get("ASR_ENABLED", default))
    except Exception:
        return default


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@asr_bp.route("/api/asr/recognize", methods=["POST"])
def asr_recognize():
    """multipart 上传音频 → 识别文本。"""
    if not _asr_enabled(True):
        return jsonify({"error": "ASR disabled"}), 403
    if "audio" not in request.files:
        return jsonify({"error": "Missing audio file"}), 400

    audio_bytes = request.files["audio"].read()
    if not audio_bytes:
        return jsonify({"error": "Missing audio file"}), 400

    if _asr is None:
        return jsonify({"error": "ASR processing failed"}), 500

    try:
        normalized = _asr.normalize_audio(audio_bytes)
        text, _segments, error = _asr.transcribe_with_error(normalized)
    except Exception:  # noqa: BLE001
        logger.exception("ASR 识别失败")
        return jsonify({"error": "ASR processing failed"}), 500

    if error:
        # sidecar 不可用/识别异常 → 500（与参考实现契约一致：
        # "处理失败" 与 "没听清" 是两回事）
        logger.warning("ASR 识别失败: %s", error)
        return jsonify({"error": "ASR processing failed"}), 500

    return jsonify({"text": text})


@asr_bp.route("/api/asr/passthrough", methods=["POST"])
def asr_passthrough():
    """CLI 语音上行入口：base64 音频 → 识别 → 走对话 → SSE 回流。"""
    if not _asr_enabled(False):
        return jsonify({"error": "ASR disabled"}), 403

    data = request.get_json(silent=True) or {}
    if not data or ("audio_b64" not in data and "audio" not in data):
        return jsonify({"error": "Missing audio"}), 400

    audio_b64 = data.get("audio_b64") or data.get("audio") or ""
    try:
        audio_bytes = base64.b64decode(audio_b64)
    except Exception:
        return jsonify({"error": "Invalid base64"}), 400
    if not audio_bytes:
        return jsonify({"error": "Missing audio"}), 400

    if _asr is None:
        return jsonify({"error": "ASR processing failed"}), 500

    try:
        normalized = _asr.normalize_audio(audio_bytes)
        recognized_text, _segments, error = _asr.transcribe_with_error(normalized)
    except Exception:  # noqa: BLE001
        logger.exception("ASR 识别失败")
        return jsonify({"error": "ASR processing failed"}), 500

    if error:
        logger.warning("ASR 识别失败: %s", error)
        return jsonify({"error": "ASR processing failed"}), 500

    if not recognized_text:
        # 空识别：返回 JSON（非 SSE）—— 与参考实现一致，CLI 侧据此静默跳过
        return jsonify({
            "reply": "",
            "chat_id": data.get("chat_id"),
            "filtered": True,
        })

    engine = _engine_getter() if _engine_getter else None
    if engine is None:
        return jsonify({"error": "Engine not ready"}), 503

    user_id = g.user.get("uid", 0) or 1
    tts_enabled = bool(data.get("tts_enabled", True))
    image = (data.get("image_data") or "").strip() or None
    # 与参考实现一致：识别文本包进一句固定前缀再进对话
    message = f"你听到用户那边传来的声音：{recognized_text}"

    def generate():
        try:
            if tts_enabled:
                result = engine.chat_audio(message, user_id=user_id, image=image,
                                           is_asr_input=True)
                reply = result.get("reply", "")
                audio = result.get("audio_b64") or ""
                tts_error = result.get("tts_error") or ""
            else:
                reply = engine.chat(message, user_id=user_id, image=image,
                                    is_asr_input=True)
                audio, tts_error = "", ""
        except Exception as e:  # noqa: BLE001
            logger.exception("语音上行对话处理失败")
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
