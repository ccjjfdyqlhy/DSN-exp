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
import time
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


def _wav_seconds(data: bytes) -> float:
    """WAV 字节 → 秒数（按文件头里的真实采样率，不猜）。

    之前按 32kHz 硬算，而客户端送的是 16kHz → 日志里时长少一半。
    """
    try:
        import io
        import wave
        with wave.open(io.BytesIO(data)) as wf:
            return wf.getnframes() / float(wf.getframerate() or 1)
    except Exception:   # noqa: BLE001
        return 0.0


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

    t_asr = time.perf_counter()
    try:
        normalized = _asr.normalize_audio(audio_bytes)
        recognized_text, _segments, error = _asr.transcribe_with_error(normalized)
    except Exception:  # noqa: BLE001
        logger.exception("ASR 识别失败")
        return jsonify({"error": "ASR processing failed"}), 500
    logger.info("ASR 耗时 %.2fs (音频 %.1fs, 识别文本 %d 字)",
                time.perf_counter() - t_asr,
                _wav_seconds(audio_bytes),
                len(recognized_text or ""))

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
    # 识别文本**原样**进对话 —— 不加任何人工前缀。
    #
    # 此前是 f"你听到用户那边传来的声音：{recognized_text}"，那个前缀会流进
    # 下游的每一个模型：embedding（向量化的是带前缀的整句）、话题系统的语义
    # 判定、记忆落库、主模型。等于让人为的措辞污染了全链路语义。
    # "这一轮来自语音"这个信息由 ctx.is_asr_input 承载 —— 那是结构化标记，
    # 不该混进文本内容。
    message = recognized_text

    def generate():
        """流式语音链路（方案 D）。

        事件序列（与 CLI 的 SSE 解析器兼容）：
          text_delta   文本增量（前端/CLI 可即时显示）
          line         每句音频（index 递增，audio_b64）
          text_ready   完整文本（兼容旧客户端：它们只认这个）
          tool_error   TTS 失败（文本仍可用）
          completed    结束

        为什么保留 text_ready：CLI 的 ``_stream_chat`` 用 final_reply 覆盖式
        写法，只有收到 text_ready 才会打印整段回复。新事件是**增量**事件，
        旧客户端不认识也无害。
        """
        t_first_event = time.perf_counter()
        got_audio = False
        tts_err = ""
        text_ready_sent = False
        try:
            if tts_enabled and hasattr(engine, "chat_stream_audio"):
                for ev in engine.chat_stream_audio(
                        message, user_id=user_id, image=image,
                        is_asr_input=True):
                    etype = ev.get("type")
                    if etype == "text_delta":
                        yield _sse({"status": "text_delta",
                                    "text": ev.get("text", "")})
                    elif etype == "audio":
                        if not got_audio:
                            got_audio = True
                            logger.info("语音链路首段音频 %.2fs (index=%s)",
                                        time.perf_counter() - t_first_event,
                                        ev.get("index"))
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
                            text_ready_sent = True
                            yield _sse({"status": "text_ready",
                                        "reply": reply, "chat_id": None})
                        if ev.get("tts_error"):
                            tts_err = ev["tts_error"]
            else:
                # 退化路径：引擎不支持流式 → 走原来的整段链路
                if tts_enabled:
                    result = engine.chat_audio(message, user_id=user_id,
                                               image=image, is_asr_input=True)
                    reply = result.get("reply", "")
                    audio = result.get("audio_b64") or ""
                    tts_err = result.get("tts_error") or ""
                else:
                    reply = engine.chat(message, user_id=user_id, image=image,
                                        is_asr_input=True)
                    audio, tts_err = "", ""
                if reply:
                    text_ready_sent = True
                    yield _sse({"status": "text_ready", "reply": reply,
                                "chat_id": None})
                if audio:
                    yield _sse({"status": "line", "index": 0, "total": 1,
                                "text": reply, "audio_b64": audio})
        except Exception as e:  # noqa: BLE001
            logger.exception("语音上行对话处理失败")
            yield _sse({"status": "tool_error", "tool": "chat", "error": str(e)})
        finally:
            if tts_err:
                yield _sse({"status": "tool_error", "tool": "tts",
                            "error": tts_err})
            if not got_audio and tts_enabled:
                logger.warning("语音链路未产出任何音频（tts_err=%r）", tts_err)
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
