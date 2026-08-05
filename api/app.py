
# DSN-exp/app.py
# 精简版 — 仅保留路由 + 中间件，初始化逻辑移至 boot.py

import time
from flask import request, jsonify, g, Response, stream_with_context
from functools import wraps

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
script_engine = boot.script_engine
script_plugin = boot.script_plugin
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

    extra = result.get("extra", {})
    resp = {
        "reply": result["reply"], "chat_id": result["chat_id"],
        "audio": result.get("audio_b64"), "tts_error": result.get("tts_error"),
        "confirm_requested": extra.get("confirm_requested", False),
    }
    # ── v4 世界引擎状态 ──
    if extra.get("world_activated"):
        resp["world_activated"] = True
    if extra.get("narrative"):
        resp["narrative"] = extra["narrative"]
    if extra.get("pre_narrative"):
        resp["pre_narrative"] = extra["pre_narrative"]
    if extra.get("action_narratives"):
        resp["action_narratives"] = extra["action_narratives"]
    if extra.get("world_snapshot"):
        resp["world_snapshot"] = extra["world_snapshot"]
    return jsonify(resp)


@app.route("/api/chat/stream_send", methods=["POST"])
@login_required
def chat_stream_send():
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "Missing message"}), 400

    # ── 双模协同路径 ──
    coordinator = app.config.get("DUAL_COORDINATOR")
    if coordinator:
        user_id = g.user["uid"]
        chat_id = data.get("chat_id")
        if not chat_id:
            chat_id = db.create_chat(user_id, data.get("chat_name", "dual"))

        def dual_generate():
            yield from coordinator.process_stream(
                user_id=user_id,
                chat_id=chat_id,
                message=data["message"],
                nickname=g.user.get("nickname", "用户"),
                chat_name=data.get("chat_name", "dual"),
            )

        return Response(
            stream_with_context(dual_generate()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # ── 单模路径 (现有逻辑) ──
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

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/api/chat/interject", methods=["POST"])
@login_required
def chat_interject():
    """双模模式下，用户在 SSE 途中插话。"""
    coordinator = app.config.get("DUAL_COORDINATOR")
    if not coordinator:
        return jsonify({"error": "Dual mode not enabled"}), 404

    data = request.get_json()
    message = (data or {}).get("message", "").strip()
    chat_id = (data or {}).get("chat_id")
    if not message:
        return jsonify({"error": "Missing message"}), 400

    session = coordinator.get_active_session(g.user["uid"], chat_id)
    if not session:
        return jsonify({"error": "No active stream"}), 404

    session.interject_queue.put(message)
    return jsonify({"ok": True})


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
        res = asr_model.generate(
            input=audio_bytes,
            use_itn=True,
            batch_size_s=Config.ASR_BATCH_SIZE_SECONDS,
            language="zh",
        )
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
        res = asr_model.generate(
            input=audio_bytes,
            use_itn=True,
            batch_size_s=Config.ASR_BATCH_SIZE_SECONDS,
            language="zh",
        )
        recognized_text = res[0].get("text", "").strip() if res else ""
    except Exception as e:
        return jsonify({"error": "ASR processing failed"}), 500
    if not recognized_text:
        return jsonify({"reply": "", "chat_id": data.get("chat_id"), "filtered": True})

    # ── 双模协同路径 ──
    coordinator = app.config.get("DUAL_COORDINATOR")
    if coordinator:
        user_id = g.user["uid"]
        chat_id = data.get("chat_id")
        if not chat_id:
            chat_id = db.create_chat(user_id, data.get("chat_name", "dual"))

        def dual_generate():
            yield from coordinator.process_stream(
                user_id=user_id,
                chat_id=chat_id,
                message=recognized_text,
                nickname=g.user.get("nickname", "用户"),
                chat_name=data.get("chat_name", "dual"),
            )

        return Response(
            stream_with_context(dual_generate()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # ── 单模路径 (现有逻辑) ──
    message = f"你听到用户那边传来的声音：{recognized_text}"

    def generate():
        import asyncio
        _t0_gen = time.perf_counter()
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
                    app.logger.info("[SSE-FLUSH] StopAsyncIteration 收到, t=%.4f, 距生成器启动 %.1fs",
                                    time.perf_counter(), time.perf_counter() - _t0_gen)
                    break
        finally:
            app.logger.info("[SSE-FLUSH] finally: loop.close() 开始, t=%.4f", time.perf_counter())
            loop.close()
            app.logger.info("[SSE-FLUSH] finally: loop.close() 结束, t=%.4f", time.perf_counter())

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/api/sensing/event", methods=["POST"])
@login_required
def sensing_event():
    """闲置时感知上报：minimal.py 未进入录音时捕捉到的环境声音 → ASR → 存档。

    只做识别+存档，不触发 AI 回复（纯 JSON 返回）。用户身份由 API Key 区分。
    """
    if not app.config.get("SENSING_ENABLED", False):
        return jsonify({"error": "Sensing disabled"}), 403
    if not app.config.get("ASR_ENABLED", False):
        return jsonify({"error": "ASR disabled"}), 403
    data = request.get_json()
    if not data or "audio_b64" not in data:
        return jsonify({"error": "Missing audio_b64"}), 400

    audio_b64 = data.get("audio_b64", "")
    if not audio_b64:
        return jsonify({"error": "Empty audio"}), 400
    try:
        audio_bytes = __import__("base64").b64decode(audio_b64)
    except Exception:
        return jsonify({"error": "Invalid base64"}), 400
    if Config.DEBUG_ASR:
        _save_debug_audio(audio_bytes)
    audio_bytes = _convert_audio_to_wav(audio_bytes)

    # 服务端节流：cooldown 内重复上报则忽略（客户端也会自我节流）
    uid = g.user["uid"]
    cooldown = max(1, int(getattr(Config, "SENSING_COOLDOWN", 60)))
    last_ts = db.get_last_sensing_time(uid)
    if last_ts:
        try:
            from datetime import datetime
            last_dt = datetime.strptime(last_ts, "%Y-%m-%d %H:%M:%S")
            if (datetime.now() - last_dt).total_seconds() < cooldown:
                return jsonify({"success": True, "recorded": False,
                                "cooldown": True, "text": ""})
        except Exception:
            pass

    try:
        res = asr_model.generate(
            input=audio_bytes,
            use_itn=True,
            batch_size_s=Config.ASR_BATCH_SIZE_SECONDS,
            language="zh",
        )
        recognized_text = res[0].get("text", "").strip() if res else ""
    except Exception as e:
        return jsonify({"error": "ASR processing failed"}), 500

    # 丢弃无文本或过短（<3 字）的识别结果，不落盘（多为噪声/环境音误触发）
    if len(recognized_text) < 3:
        return jsonify({"success": True, "recorded": False, "text": ""})

    try:
        event_id = db.add_sensing_event(
            user_id=uid,
            text=recognized_text,
            source=data.get("source", "") or "sensing",
            rms_level=float(data.get("rms_level", 0.0) or 0.0),
            chat_id=data.get("chat_id"),
        )
    except Exception as e:
        return jsonify({"error": "Database error"}), 500
    return jsonify({"success": True, "recorded": True, "event_id": event_id,
                    "text": recognized_text})


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
        app.logger.warning("上传角色卡失败: %s", e)
        return jsonify({"error": "Invalid card data"}), 400


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
        app.logger.warning("蒸馏失败 %s: %s", card_id, e)
        return jsonify({"error": "Distillation failed"}), 500


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


# ── 世界状态 ──

@app.route("/api/world/state", methods=["GET"])
@login_required
def world_state():
    """返回当前世界状态快照（时间、天气、位置、近期事件）"""
    if not engine.world_engine:
        return jsonify({"error": "World engine not available"}), 503
    try:
        state = engine.world_engine.get_full_state()
        prompt = engine.world_engine.get_state_prompt()
        return jsonify({
            "state": state,
            "prompt": prompt,
            "activated": engine.world_engine.is_activated(),
            "interaction_count": engine.world_engine.interaction_count,
        })
    except Exception as e:
        app.logger.error("World state error: %s", e)
        return jsonify({"error": "Internal error"}), 500


# ── 命运引擎 ──

@app.route("/api/fate/roll", methods=["POST"])
@login_required
def fate_roll():
    """
    命运骰子投掷。
    
    请求体: {"expression": "1d20", "label": "说服检定", "advantage": false, "disadvantage": false}
    返回: {"expression": "1d20", "label": "...", "result": {"total": 15, "values": [15], "sides": 20, "count": 1, "crit_success": false, "crit_fail": false, "advantage": false, "disadvantage": false}}
    """
    if not engine.world_engine:
        return jsonify({"error": "World engine not available"}), 503
    try:
        data = request.get_json() or {}
        expr = data.get("expression", "1d20")
        label = data.get("label", "")
        advantage = data.get("advantage", False)
        disadvantage = data.get("disadvantage", False)

        # 解析表达式
        import re
        m = re.match(r'^(\d*)d(\d+)$', expr.strip().lower().replace(" ", ""))
        if m:
            count = int(m.group(1)) if m.group(1) else 1
            sides = int(m.group(2))
            result = engine.world_engine.fate_dice.roll(
                sides, count, label=label,
                advantage=advantage, disadvantage=disadvantage)
        else:
            # 骰池表达式: 2d6+1d4+3
            from world.fate import DicePool
            result = DicePool.from_expression(expr, label=label)

        return jsonify({
            "expression": expr,
            "label": label,
            "result": {
                "total": result.total,
                "values": result.values,
                "sides": result.sides,
                "count": result.count,
                "crit_success": result.crit_success,
                "crit_fail": result.crit_fail,
                "advantage": result.advantage,
                "disadvantage": result.disadvantage,
                "label": result.label,
            }
        })
    except Exception as e:
        app.logger.error("Fate roll error: %s", e)
        return jsonify({"error": "Internal error"}), 400


@app.route("/api/fate/table", methods=["POST"])
@login_required
def fate_table_roll():
    """
    概率表投掷。
    
    请求体: {"entries": [[0.4, "晴朗"], [0.3, "多云"], [0.2, "小雨"], [0.1, "雷暴"]], "label": "天气"}
    返回: {"label": "天气", "result": {"value": "晴朗", "probability": 0.4}}
    """
    from world.fate import ProbabilityTable
    try:
        data = request.get_json() or {}
        entries = data.get("entries", [])
        label = data.get("label", "")
        table = ProbabilityTable(entries, label=label)
        result = table.roll()
        return jsonify({
            "label": label,
            "result": {
                "value": result.value,
                "probability": result.probability,
                "index": result.index,
                "metadata": result.metadata,
            }
        })
    except Exception as e:
        app.logger.error("Fate table roll error: %s", e)
        return jsonify({"error": "Internal error"}), 400


# ── 直接运行 ──
if __name__ == "__main__":
    app.run(host=app.config["SERVER_HOST"], port=app.config["SERVER_PORT"], debug=False)
