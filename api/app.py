
# DSN-exp/app.py
# 精简版 — 仅保留路由 + 中间件，初始化逻辑移至 boot.py

from flask import Flask, request, jsonify, g, Response, stream_with_context
from functools import wraps
from datetime import datetime

from config import Config
import boot

# ── 启动初始化 ──
app = boot.create_application()
db = boot.db
engine = boot.engine
task_manager = boot.task_manager
memory_system = boot.memory_system
summary_model = boot.summary_model
personality_v3 = boot.personality_v3
maint_system = boot.maint_system
_tts_process_model = boot._tts_process_model
filter_model = boot.filter_model
asr_model = boot.asr_model
tts_client = boot.tts_client
tts_profile_mgr = boot.tts_profile_mgr
prompt_engine = boot.prompt_engine
_impression_manager = boot._impression_manager
skill_registry = boot.skill_registry
skill_manager = boot.skill_manager
_personality_v2 = prompt_engine.personality_v2 if prompt_engine else None

# 模块级辅助函数
_process_image_input = boot._process_image_input
_save_debug_audio = boot._save_debug_audio
_convert_audio_to_wav = boot._convert_audio_to_wav
_synthesize_tts_lines = boot._synthesize_tts_lines
create_chat_client = boot.create_chat_client


# ── 认证装饰器 ──
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = app.config["AUTH_MANAGER"].authenticate(request)
        if not user:
            return jsonify({"error": "Unauthorized"}), 401
        g.user = user
        db.add_or_update_user(user["uid"], user.get("nickname", "用户"))
        return f(*args, **kwargs)
    return decorated_function


# ── 请求钩子 ──
@app.teardown_appcontext
def close_db_connection(exception=None):
    if db:
        db.close_connection()


# ── CORS ──
@app.after_request
def add_cors_headers(response):
    origin = request.headers.get("Origin", "")
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
    else:
        response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-DSN-API-Key"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    response.headers["Access-Control-Expose-Headers"] = "Content-Type, Cache-Control"
    response.headers["Access-Control-Max-Age"] = "3600"
    return response


@app.before_request
def check_maintenance():
    if request.path.startswith("/api/maintenance/"):
        return None
    ms = app.config.get("MAINTENANCE_SYSTEM")
    if ms is None:
        return None
    ms.record_user_request()
    if ms.state.state.value == "maint":
        return jsonify({"error": "服务器整理中，请稍后访问", "status": "maintenance", "retry_after": 120}), 503


@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        resp = jsonify({"ok": True})
        origin = request.headers.get("Origin", "")
        resp.headers["Access-Control-Allow-Origin"] = origin if origin else "*"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-DSN-API-Key"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        resp.headers["Access-Control-Expose-Headers"] = "Content-Type, Cache-Control"
        resp.headers["Access-Control-Max-Age"] = "3600"
        return resp, 200


# ═══════════════════════════════════════════════════
# API 路由
# ═══════════════════════════════════════════════════

# ── 聊天 ──

@app.route("/api/chat/send", methods=["POST"])
@login_required
def chat_send():
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "Missing message"}), 400
    try:
        result = engine.chat(
            message=data["message"], user_id=g.user["uid"],
            chat_id=data.get("chat_id"), chat_name=data.get("chat_name", "未命名"),
            model_type=data.get("model_type"), nickname=g.user.get("nickname", "用户"),
            tts_enabled=data.get("tts_enabled", True),
            is_asr_input=data.get("is_asr_input", False),
            image_data=data.get("image_data"),
        )
    except Exception as e:
        return jsonify({"error": "AI service error"}), 500
    if result.get("filtered"):
        return jsonify({"reply": "", "chat_id": result["chat_id"], "filtered": True})
    return jsonify({
        "reply": result["reply"], "chat_id": result["chat_id"],
        "audio": result.get("audio_b64"), "tts_error": result.get("tts_error"),
        "confirm_requested": result.get("extra", {}).get("confirm_requested", False),
    })


@app.route("/api/chat/stream_send", methods=["POST"])
@login_required
def chat_stream_send():
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "Missing message"}), 400

    def generate():
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            agen = engine.chat_stream(
                message=data["message"], user_id=g.user["uid"],
                chat_id=data.get("chat_id"), chat_name=data.get("chat_name", "未命名"),
                model_type=data.get("model_type"), nickname=g.user.get("nickname", "用户"),
                tts_enabled=data.get("tts_enabled", True),
                is_asr_input=data.get("is_asr_input", False),
                image_data=data.get("image_data"),
            ).__aiter__()
            while True:
                try:
                    yield loop.run_until_complete(agen.__anext__())
                except StopAsyncIteration:
                    break
        finally:
            loop.close()

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


@app.route("/api/chat/list", methods=["GET"])
@login_required
def chat_list():
    try:
        return jsonify({"chats": db.list_chats(g.user["uid"])})
    except Exception as e:
        return jsonify({"error": "Database error"}), 500


@app.route("/api/chat/<int:chat_id>", methods=["GET"])
@login_required
def chat_history(chat_id):
    try:
        return jsonify({"messages": db.get_chat_history(g.user["uid"], chat_id)})
    except Exception as e:
        return jsonify({"error": "Database error"}), 500


@app.route("/api/chat/<int:chat_id>", methods=["DELETE"])
@login_required
def chat_delete(chat_id):
    try:
        ok = db.delete_chat(g.user["uid"], chat_id)
        return jsonify({"success": ok}) if ok else (jsonify({"error": "Not found"}), 404)
    except Exception as e:
        return jsonify({"error": "Database error"}), 500


# ── ASR ──

@app.route("/api/asr/recognize", methods=["POST"])
@login_required
def asr_recognize():
    if not app.config.get("ASR_ENABLED", True):
        return jsonify({"error": "ASR disabled"}), 403
    if "audio" not in request.files:
        return jsonify({"error": "Missing audio file"}), 400
    audio_bytes = request.files["audio"].read()
    if Config.DEBUG_ASR:
        _save_debug_audio(audio_bytes)
    audio_bytes = _convert_audio_to_wav(audio_bytes)
    try:
        res = asr_model.generate(input=audio_bytes, use_itn=True, batch_size_s=60, language="zh")
        text = res[0].get("text", "").strip() if res else ""
        return jsonify({"text": text})
    except Exception as e:
        return jsonify({"error": "ASR processing failed"}), 500


_SENSING_PROMPT_CACHE = None


def get_sensing_prompt() -> str:
    global _SENSING_PROMPT_CACHE
    if _SENSING_PROMPT_CACHE is not None:
        return _SENSING_PROMPT_CACHE
    import re, os
    path = os.path.join(os.path.dirname(__file__), "..", "prompt", "prompts", "capabilities", "sensing.md")
    try:
        text = open(path, encoding="utf-8-sig").read()
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
        _SENSING_PROMPT_CACHE = m.group(2).strip() if m else text.strip()
    except Exception:
        _SENSING_PROMPT_CACHE = ""
    return _SENSING_PROMPT_CACHE


@app.route("/api/asr/passthrough", methods=["POST"])
@login_required
def asr_passthrough():
    if not app.config.get("ASR_ENABLED", False):
        return jsonify({"error": "ASR disabled"}), 403
    data = request.get_json()
    if not data or ("audio_b64" not in data and "audio" not in data):
        return jsonify({"error": "Missing audio"}), 400

    is_sensing = data.get("sensing", False) is True
    audio_b64 = data.get("audio_b64") or data.get("audio", "")
    try:
        audio_bytes = __import__("base64").b64decode(audio_b64)
    except Exception:
        return jsonify({"error": "Invalid base64"}), 400
    if Config.DEBUG_ASR:
        _save_debug_audio(audio_bytes)
    audio_bytes = _convert_audio_to_wav(audio_bytes)

    try:
        res = asr_model.generate(input=audio_bytes, use_itn=True, batch_size_s=60, language="zh")
        recognized_text = res[0].get("text", "").strip() if res else ""
    except Exception as e:
        return jsonify({"error": "ASR processing failed"}), 500
    if not recognized_text:
        return jsonify({"reply": "", "chat_id": data.get("chat_id"), "filtered": True})

    message = f"你听到用户那边传来的声音：{recognized_text}"

    def generate():
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            agen = engine.chat_stream(
                message=message, user_id=g.user["uid"],
                chat_id=data.get("chat_id"), chat_name=data.get("chat_name", "Psychoscope"),
                model_type=data.get("model_type"), nickname=g.user.get("nickname", "用户"),
                tts_enabled=data.get("tts_enabled", True), is_asr_input=True,
                image_data=data.get("image_data"),
                sensing_hint=get_sensing_prompt() if is_sensing else "",
            ).__aiter__()
            while True:
                try:
                    yield loop.run_until_complete(agen.__anext__())
                except StopAsyncIteration:
                    break
        finally:
            loop.close()

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


# ── 人格系统 V3 ──

@app.route("/api/v3/card/list", methods=["GET"])
@login_required
def v3_card_list():
    if not personality_v3:
        return jsonify({"error": "PersonalitySystemV3 not available"}), 503
    return jsonify({"cards": personality_v3.list_cards()})


@app.route("/api/v3/card/<card_id>", methods=["GET"])
@login_required
def v3_card_get(card_id):
    if not personality_v3:
        return jsonify({"error": "PersonalitySystemV3 not available"}), 503
    card = personality_v3.get_card(card_id)
    if not card:
        return jsonify({"error": "Card not found"}), 404
    return jsonify(card.to_dict())


@app.route("/api/v3/card/upload", methods=["POST"])
@login_required
def v3_card_upload():
    if not personality_v3:
        return jsonify({"error": "PersonalitySystemV3 not available"}), 503
    data = request.get_json()
    if not data or "yaml" not in data:
        return jsonify({"error": "Missing yaml content"}), 400
    try:
        from prompt.personality_v3 import CharacterCard
        card = CharacterCard.from_yaml_string(data["yaml"])
        return jsonify({"success": personality_v3.upload_card(card), "card_id": card.card_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/v3/card/<card_id>/distill", methods=["POST"])
@login_required
def v3_card_distill(card_id):
    if not personality_v3:
        return jsonify({"error": "PersonalitySystemV3 not available"}), 503
    try:
        d = personality_v3.distill(card_id)
        if not d:
            return jsonify({"error": "Distillation failed"}), 500
        return jsonify({"success": True, "distillation_id": d.distillation_id, "fingerprint": d.content_fingerprint})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/v3/card/<card_id>/distillation", methods=["GET"])
@login_required
def v3_card_distillation_get(card_id):
    if not personality_v3:
        return jsonify({"error": "PersonalitySystemV3 not available"}), 503
    d = personality_v3.get_distillation(card_id)
    if not d:
        return jsonify({"error": "Distillation not found"}), 404
    return jsonify(d.to_dict())


@app.route("/api/v3/user/bind", methods=["POST"])
@login_required
def v3_user_bind():
    if not personality_v3:
        return jsonify({"error": "PersonalitySystemV3 not available"}), 503
    data = request.get_json()
    card_id = data.get("card_id", "") if data else ""
    if not card_id:
        return jsonify({"error": "Missing card_id"}), 400
    return jsonify({"success": personality_v3.bind_user_card(g.user["uid"], card_id)})


# ── 人格系统 V2 (兼容) ──

@app.route("/api/personality/status", methods=["GET"])
@login_required
def personality_status():
    if personality_v3:
        return jsonify(personality_v3.get_personality_status(g.user["uid"]))
    if _personality_v2:
        return jsonify(_personality_v2.get_state(g.user["uid"]))
    return jsonify({"error": "Personality system not available"}), 503


@app.route("/api/personality/current", methods=["GET"])
@login_required
def personality_current():
    if personality_v3:
        return jsonify(personality_v3.get_personality_full(g.user["uid"]))
    if _personality_v2:
        return jsonify(_personality_v2.get_full_state(g.user["uid"]))
    return jsonify({"error": "Personality system not available"}), 503


@app.route("/api/personality/list", methods=["GET"])
@login_required
def personality_list():
    result = {"presets": []}
    if personality_v3:
        result["cards"] = personality_v3.list_cards()
    if _personality_v2:
        result["presets"] = _personality_v2.list_presets()
    return jsonify(result)


@app.route("/api/personality/switch", methods=["POST"])
@login_required
def personality_switch():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing data"}), 400
    if personality_v3 and "card_id" in data:
        return jsonify({"success": personality_v3.bind_user_card(g.user["uid"], data["card_id"]), "card_id": data["card_id"]})
    if _personality_v2 and "preset" in data:
        return jsonify(_personality_v2.switch_preset(g.user["uid"], data["preset"]))
    return jsonify({"error": "Missing preset or card_id"}), 400


# ── 用户印象 ──

@app.route("/api/impressions", methods=["GET"])
@login_required
def impression_list():
    uid = g.user["uid"]
    category = request.args.get("category")
    min_conf = float(request.args.get("min_confidence", 0.0))
    imps = _impression_manager.query(uid, category=category, min_confidence=min_conf)
    return jsonify({"impressions": imps, "count": len(imps), "summary": _impression_manager.summary(uid)})


@app.route("/api/impressions", methods=["POST"])
@login_required
def impression_add():
    uid = g.user["uid"]
    data = request.get_json()
    if not data or "content" not in data:
        return jsonify({"error": "Missing content"}), 400
    imp_id = _impression_manager.add(uid, data.get("category", "其他"), data["content"],
                                     data.get("confidence", 0.7), data.get("source", "declared"), data.get("evidence", ""))
    return jsonify({"impression_id": imp_id})


@app.route("/api/impressions/<int:impression_id>", methods=["DELETE"])
@login_required
def impression_delete(impression_id):
    return jsonify({"success": _impression_manager.delete(impression_id)})


@app.route("/api/impressions/suggest", methods=["GET"])
@login_required
def impression_suggest():
    uid = g.user["uid"]
    affinity_level = 0
    if _personality_v2:
        affinity_level = _personality_v2.get_state(uid).get("affinity", {}).get("level", 0)
    return jsonify({"suggest_ssp": _impression_manager.should_propose_ssp(uid, affinity_level),
                    "impression_count": _impression_manager.count(uid)})


# ── 直接运行 ──
if __name__ == "__main__":
    app.run(host=app.config["SERVER_HOST"], port=app.config["SERVER_PORT"], debug=False)
