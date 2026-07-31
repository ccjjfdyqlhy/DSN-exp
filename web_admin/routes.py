from __future__ import annotations

import json
import os
import sys
import time
import re
import logging
import threading
from pathlib import Path
from datetime import datetime, date, timedelta
from io import StringIO

from flask import Blueprint, jsonify, request
from config import Config

logger = logging.getLogger("web_admin")

admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")

def _import_main_components():
    from api import app as app_module
    Config = app_module.Config
    flask_app = app_module.app
    auth_manager = flask_app.config.get("AUTH_MANAGER")
    db = app_module.db
    engine = getattr(app_module, 'engine', None)
    personality_v3 = getattr(app_module, 'personality_v3', None)
    maint_system = getattr(app_module, 'maint_system', None)
    plugin_manager = engine.plugin_manager if engine else None
    prompt_engine = engine.prompt_engine if engine else None
    return {
        "Config": Config,
        "flask_app": flask_app,
        "auth_manager": auth_manager,
        "db": db,
        "engine": engine,
        "personality_v3": personality_v3,
        "maint_system": maint_system,
        "plugin_manager": plugin_manager,
        "prompt_engine": prompt_engine,
    }

_cached_components: dict | None = None

def _get_components():
    global _cached_components
    if _cached_components is None:
        _cached_components = _import_main_components()
    return _cached_components

def _get(name):
    return _get_components().get(name)

def C():
    return _get("Config")

def AM():
    return _get("auth_manager")

def DB():
    return _get("db")

def EN():
    return _get("engine")

def PV3():
    return _get("personality_v3")

def MS():
    return _get("maint_system")

def PM():
    return _get("plugin_manager")

def PE():
    return _get("prompt_engine")

@admin_bp.route("/status", methods=["GET"])
def api_status():
    from main import _server_start_time
    data = {"uptime": None, "users": [], "stats": {}}
    if _server_start_time:
        delta = datetime.now() - _server_start_time
        data["uptime"] = delta.total_seconds()
    try:
        auth_manager = AM()
        if auth_manager:
            users = auth_manager.list_users()
            data["users"] = [
                {"uid": u["uid"], "display_name": u["display_name"],
                 "is_admin": u.get("is_admin", False)}
                for u in users
            ]
    except Exception:
        logger.warning("Operation failed", exc_info=True)
    try:
        db = DB()
        conn = db._get_connection()
        chats = conn.execute(
            "SELECT COUNT(*) FROM chats WHERE chat_name != '__steward__'"
        ).fetchone()[0]
        msgs = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        sessions = conn.execute(
            "SELECT COUNT(*) FROM auth_sessions WHERE revoked = 0 AND expires_at > datetime('now')"
        ).fetchone()[0]
        data["stats"] = {"chats": chats, "messages": msgs, "active_sessions": sessions}
    except Exception:
        logger.warning("Operation failed", exc_info=True)
    auth_manager = AM()
    if auth_manager and auth_manager.pairing.is_active():
        data["pairing_active"] = True
    Config = C()
    data["config_count"] = len([k for k in dir(Config) if not k.startswith("_") and not callable(getattr(Config, k))])
    return jsonify(data)

@admin_bp.route("/pairing/generate", methods=["POST"])
def api_pairing_generate():
    auth_manager = AM()
    if not auth_manager:
        return jsonify({"error": "AuthManager unavailable"}), 503
    if auth_manager.pairing.is_active():
        return jsonify({"error": "Active pairing code already exists"}), 400
    old_stdout = sys.stdout
    buf = StringIO()
    sys.stdout = buf
    try:
        from main import _cmd_newbind
        _cmd_newbind(auth_manager)
    finally:
        sys.stdout = old_stdout
    output = buf.getvalue()
    code = None
    for line in output.split("\n"):
        line = line.strip()
        if "配对码:" in line:
            code = line.split(":")[-1].strip()
    if not code:
        for part in output.split():
            if len(part) >= 4 and part.isalnum():
                code = part
                break
    return jsonify({"success": True, "code": code, "output": output})

@admin_bp.route("/pairing/status", methods=["GET"])
def api_pairing_status():
    auth_manager = AM()
    active = bool(auth_manager and auth_manager.pairing.is_active())
    return jsonify({"active": active})

@admin_bp.route("/users", methods=["GET"])
def api_users():
    auth_manager = AM()
    db = DB()
    if not auth_manager:
        return jsonify({"users": [], "error": "AuthManager unavailable"})
    users = auth_manager.list_users()
    result = []
    try:
        conn = db._get_connection()
        for u in users:
            row = conn.execute(
                "SELECT created_at FROM users WHERE uid = ?", (u["uid"],)
            ).fetchone()
            result.append({
                "uid": u["uid"],
                "display_name": u["display_name"],
                "is_admin": u.get("is_admin", False),
                "created_at": row["created_at"] if row else None,
            })
    except Exception:
        result = [{"uid": u["uid"], "display_name": u["display_name"],
                    "is_admin": u.get("is_admin", False)} for u in users]
    return jsonify({"users": result})

@admin_bp.route("/plugins", methods=["GET"])
def api_plugins():
    plugin_manager = PM()
    name = request.args.get("name")
    if not plugin_manager:
        return jsonify({"plugins": [], "error": "PluginManager unavailable"})
    if name:
        p = plugin_manager.get(name)
        if not p:
            return jsonify({"error": f"Plugin '{name}' not found"}), 404
        return jsonify({
            "name": p.name,
            "description": p.description,
            "version": p.version,
            "hooks": [h.value for h in p.hooks],
            "priority": p.priority,
            "enabled": plugin_manager.is_enabled(p.name),
        })
    plugins = plugin_manager.list_plugins()
    return jsonify({"plugins": [
        {"name": pl["name"], "enabled": pl["enabled"],
         "priority": pl["priority"], "hooks": pl["hooks"],
         "version": pl["version"]}
        for pl in plugins
    ]})

@admin_bp.route("/memory/users", methods=["GET"])
def api_memory_users():
    auth_manager = AM()
    db = DB()
    if not auth_manager or not db:
        return jsonify({"error": "System unavailable"}), 503
    users = auth_manager.list_users()
    conn = db._get_connection()
    result = []
    for u in users:
        uid = u["uid"]
        chat_row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM chats WHERE user_id = ? AND chat_name != '__steward__'",
            (uid,),
        ).fetchone()
        mem_row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM memory_v2 WHERE user_id = ? AND type = 'exp'",
            (uid,),
        ).fetchone()
        result.append({
            "uid": uid,
            "display_name": u["display_name"],
            "chats": chat_row["cnt"] if chat_row else 0,
            "memories": mem_row["cnt"] if mem_row else 0,
        })
    return jsonify({"users": result})

@admin_bp.route("/memory/chats/<int:uid>", methods=["GET"])
def api_memory_chats(uid):
    db = DB()
    if not db:
        return jsonify({"error": "DB unavailable"}), 503
    chats = db.list_chats(uid)
    if not chats:
        return jsonify({"chats": []})
    conn = db._get_connection()
    result = []
    for c in chats:
        cid = c["chat_id"]
        mem_row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM memory_v2 WHERE user_id = ? AND chat_id = ? AND type = 'exp'",
            (uid, cid),
        ).fetchone()
        result.append({
            "chat_id": cid,
            "chat_name": c["chat_name"],
            "message_count": c["message_count"],
            "created_at": c["created_at"],
            "memory_count": mem_row["cnt"] if mem_row else 0,
        })
    return jsonify({"chats": result})

@admin_bp.route("/memory/list/<int:uid>/<int:cid>", methods=["GET"])
def api_memory_list(uid, cid):
    db = DB()
    if not db:
        return jsonify({"error": "DB unavailable"}), 503
    round_str = request.args.get("round")
    conn = db._get_connection()
    row = conn.execute(
        "SELECT 1 FROM chats WHERE chat_id = ? AND user_id = ? AND chat_name != '__steward__'",
        (cid, uid),
    ).fetchone()
    if not row:
        return jsonify({"error": "Chat not found"}), 404
    from utils.crypto import MessageCipher
    cipher = db._cipher
    if round_str:
        try:
            target_round = int(round_str)
        except ValueError:
            return jsonify({"error": "Invalid round"}), 400
        rows = conn.execute(
            "SELECT id, round, content, created_at, type FROM memory_v2 "
            "WHERE user_id = ? AND chat_id = ? AND type = 'exp' AND round = ? "
            "ORDER BY id ASC",
            (uid, cid, target_round),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, round, content, created_at, type FROM memory_v2 "
            "WHERE user_id = ? AND chat_id = ? AND type = 'exp' "
            "ORDER BY round ASC, id ASC",
            (uid, cid),
        ).fetchall()
    entries = []
    for r in rows:
        content = cipher.decrypt(uid, r["content"] or "")
        entries.append({
            "id": r["id"],
            "round": r["round"],
            "content": content or "",
            "created_at": r["created_at"],
            "type": r["type"],
        })
    return jsonify({"entries": entries, "count": len(entries)})

@admin_bp.route("/memory/query", methods=["POST"])
def api_memory_query():
    db = DB()
    if not db:
        return jsonify({"error": "DB unavailable"}), 503
    data = request.get_json() or {}
    uid = data.get("uid")
    cid = data.get("cid")
    keywords = data.get("keywords", [])
    date_after = data.get("date_after")
    date_before = data.get("date_before")
    conn = db._get_connection()
    from utils.crypto import MessageCipher
    cipher = db._cipher
    sql = "SELECT id, round, content, created_at FROM memory_v2 WHERE user_id = ? AND chat_id = ?"
    params = [uid, cid]
    if date_after:
        sql += " AND created_at >= ?"
        params.append(date_after)
    if date_before:
        sql += " AND created_at < ?"
        params.append(date_before)
    sql += f" ORDER BY id DESC LIMIT {Config.MEMORY_QUERY_LIMIT}"
    rows = conn.execute(sql, params).fetchall()
    results = []
    for r in rows:
        content = cipher.decrypt(uid, r["content"] or "")
        if not content:
            continue
        if keywords and not any(kw.lower() in content.lower() for kw in keywords):
            continue
        results.append({
            "id": r["id"],
            "round": r["round"],
            "content": content,
            "created_at": r["created_at"],
        })
    return jsonify({"results": results, "count": len(results)})

@admin_bp.route("/memory/reindex", methods=["POST"])
def api_memory_reindex():
    data = request.get_json() or {}
    uid = data.get("uid")
    engine = EN()
    if not engine or not engine.memory_system:
        return jsonify({"error": "MemorySystem not initialized"}), 503
    ms = engine.memory_system
    if not ms._embedding_enabled:
        return jsonify({"error": "Embedding not enabled"}), 400
    def _run():
        try:
            for processed, total, preview, skipped in ms.reindex_embeddings(user_id=uid):
                pass
        except Exception:
            logger.warning("Operation failed", exc_info=True)
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify({"success": True, "message": "Reindex started"})

@admin_bp.route("/config", methods=["GET"])
def api_config_list():
    Config = C()
    from main import SENSITIVE_CONFIG_KEYS, READONLY_CONFIG_KEYS, _mask_value, _env_backup_count
    items = []
    for key in sorted(dir(Config)):
        if key.startswith("_"):
            continue
        val = getattr(Config, key, None)
        if callable(val):
            continue
        items.append({
            "key": key,
            "value": _mask_value(key, val),
            "raw_value": str(val) if key not in SENSITIVE_CONFIG_KEYS else None,
            "sensitive": key in SENSITIVE_CONFIG_KEYS,
            "readonly": key in READONLY_CONFIG_KEYS,
        })
    backups = _env_backup_count()
    return jsonify({"configs": items, "count": len(items), "backups": backups})

@admin_bp.route("/config/set", methods=["POST"])
def api_config_set():
    Config = C()
    data = request.get_json() or {}
    key = data.get("key", "").strip()
    value = data.get("value", "").strip()
    if not key:
        return jsonify({"error": "Missing key"}), 400
    if not hasattr(Config, key):
        return jsonify({"error": f"Config '{key}' does not exist"}), 404
    from main import READONLY_CONFIG_KEYS, SENSITIVE_CONFIG_KEYS
    if key in READONLY_CONFIG_KEYS:
        return jsonify({"error": f"'{key}' is read-only"}), 403
    current_val = getattr(Config, key)
    if callable(current_val):
        return jsonify({"error": f"'{key}' is not a config value"}), 400
    target_type = type(current_val)
    new_val = None
    if target_type is bool:
        lowered = value.lower()
        if lowered in ("true", "1", "yes"):
            new_val = True
        elif lowered in ("false", "0", "no"):
            new_val = False
    else:
        try:
            new_val = target_type(value)
        except (ValueError, TypeError):
            pass
    if new_val is None:
        return jsonify({"error": f"Type mismatch for '{key}', expected {target_type.__name__}"}), 400
    from main import _env_backup_rotate, _env_write, append_log
    _env_backup_rotate()
    _env_write(key, str(new_val))
    setattr(Config, key, new_val)
    append_log("system", "INFO", f"Config changed: {key} = {new_val} (was: {current_val})")
    return jsonify({"success": True, "key": key, "old_value": str(current_val), "new_value": str(new_val)})

@admin_bp.route("/config/undo", methods=["POST"])
def api_config_undo():
    Config = C()
    from main import _env_backup_count, _env_backup_restore
    count = _env_backup_count()
    if count == 0:
        return jsonify({"error": "No backups available"}), 400
    if _env_backup_restore():
        from dotenv import load_dotenv
        env_path = Path(__file__).parent.parent / ".env"
        load_dotenv(env_path, override=True)
        remaining = _env_backup_count()
        return jsonify({"success": True, "remaining_backups": remaining})
    return jsonify({"error": "Restore failed"}), 500

@admin_bp.route("/persona/list", methods=["GET"])
def api_persona_list():
    personality_v3 = PV3()
    if not personality_v3:
        return jsonify({"cards": []})
    cards = personality_v3.list_cards()
    result = []
    for c in cards:
        cid = c.get("card_id", "?")
        d = personality_v3.get_distillation(cid)
        card = personality_v3.get_card(cid)
        result.append({
            "card_id": cid,
            "display_name": c.get("display_name", c.get("name", "")),
            "version": c.get("version", ""),
            "author": c.get("author", ""),
            "distilled": d is not None,
            "distill_version": d.version if d else None,
            "experience_count": len(card.experiences) if card else 0,
        })
    return jsonify({"cards": result})

@admin_bp.route("/persona/status/<card_id>", methods=["GET"])
def api_persona_status(card_id):
    personality_v3 = PV3()
    if not personality_v3:
        return jsonify({"error": "PersonalitySystemV3 unavailable"}), 503
    card = personality_v3.get_card(card_id)
    d = personality_v3.get_distillation(card_id)
    if not card:
        return jsonify({"error": "Card not found"}), 404
    try:
        from prompt.personality_v3.traits import TRAIT_MAP
        _TRAIT_NAMES = {t.tid: t.name for t in TRAIT_MAP.values()}
    except ImportError:
        _TRAIT_NAMES = {}
    traits = {}
    if d:
        for tid, val in d.indicator_vector.items():
            traits[tid] = {"name": _TRAIT_NAMES.get(tid, tid), "value": val}

    evidence = {}
    try:
        ev_total = personality_v3._evidence.get_total(card_id)
        plast = personality_v3._evidence.get_plasticity(card_id)
        avg_p = sum(plast.values()) / len(plast) if plast else 0.0
        evidence = {
            "total": ev_total,
            "plasticity_avg": round(avg_p, 4),
            "maturity": round(1.0 - avg_p, 4),
        }
    except Exception:
        evidence = {}

    recent_events = personality_v3.get_recent_events(card_id=card_id, limit=10)

    return jsonify({
        "card_id": card_id,
        "display_name": card.display_name or card.name,
        "version": card.version,
        "description": card.description,
        "experience_count": len(card.experiences),
        "corpus_count": len(card.corpus),
        "distilled": d is not None,
        "distill_info": {
            "fingerprint": d.content_fingerprint[:30] if d else None,
            "version": d.version if d else None,
            "model": d.model_used if d else None,
            "created_at": d.created_at if d else None,
        } if d else None,
        "evidence": evidence,
        "recent_events": recent_events,
        "traits": traits,
    })

@admin_bp.route("/persona/distill/<card_id>", methods=["POST"])
def api_persona_distill(card_id):
    personality_v3 = PV3()
    if not personality_v3:
        return jsonify({"error": "PersonalitySystemV3 unavailable"}), 503
    card = personality_v3.get_card(card_id)
    if not card:
        return jsonify({"error": "Card not found"}), 404
    def _run():
        try:
            d = personality_v3.distill(card_id)
            if d:
                personality_v3.mark_distillation_done(card_id)
        except Exception:
            logger.warning("Operation failed", exc_info=True)
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify({"success": True, "message": f"Distillation started for {card_id}"})

@admin_bp.route("/logs", methods=["GET"])
def api_logs():
    from main import get_logs_snapshot
    logs = get_logs_snapshot()
    return jsonify({"logs": [
        {"time": l[0], "module": l[1], "level": l[2], "message": l[3]}
        for l in logs[-200:]
    ]})

@admin_bp.route("/reminders", methods=["GET"])
def api_reminders():
    engine = EN()
    db = DB()
    uid = request.args.get("uid", type=int)
    cid = request.args.get("cid", type=int)
    if not db:
        return jsonify({"reminders": []})
    conn = db._get_connection()
    where = []
    params = []
    if uid is not None:
        where.append("user_id = ?")
        params.append(uid)
    if cid is not None:
        where.append("chat_id = ?")
        params.append(cid)
    w = "WHERE " + " AND ".join(where) if where else ""
    rows = conn.execute(
        f"SELECT task_id, task_type, user_id, chat_id, priority, scheduled_time, "
        f"status, interval_seconds, skip_count, created_at FROM tasks {w} "
        f"ORDER BY priority DESC, scheduled_time ASC LIMIT ?",
        (*params, Config.REMINDER_LIST_LIMIT),
    ).fetchall()
    reminders = []
    for r in rows:
        reminders.append({
            "task_id": r["task_id"],
            "task_type": r["task_type"],
            "user_id": r["user_id"],
            "chat_id": r["chat_id"],
            "priority": r["priority"],
            "scheduled_time": r["scheduled_time"],
            "status": r["status"],
            "interval_seconds": r["interval_seconds"],
            "skip_count": r["skip_count"],
            "created_at": r["created_at"],
        })
    return jsonify({"reminders": reminders, "count": len(reminders)})

@admin_bp.route("/reminder/cancel", methods=["POST"])
def api_reminder_cancel():
    data = request.get_json() or {}
    tid = data.get("task_id", "")
    if not tid:
        return jsonify({"error": "Missing task_id"}), 400
    engine = EN()
    tm = engine.task_manager if engine else None
    if not tm:
        return jsonify({"error": "TaskManager unavailable"}), 503
    from tasks import TaskStatus
    matched = [k for k in tm.tasks if k.startswith(tid)]
    if len(matched) == 1:
        task = tm.tasks[matched[0]]
        task.status = TaskStatus.CANCELLED
        task.completed_at = datetime.now()
        tm._save_task(task)
        return jsonify({"success": True, "task_id": matched[0]})
    elif len(matched) > 1:
        return jsonify({"error": "Multiple matches", "matches": matched}), 400
    return jsonify({"error": "Task not found"}), 404

@admin_bp.route("/reminder/skip", methods=["POST"])
def api_reminder_skip():
    data = request.get_json() or {}
    tid = data.get("task_id", "")
    if not tid:
        return jsonify({"error": "Missing task_id"}), 400
    engine = EN()
    tm = engine.task_manager if engine else None
    if not tm:
        return jsonify({"error": "TaskManager unavailable"}), 503
    from tasks import TaskStatus, TaskType
    if tid in tm.tasks:
        task = tm.tasks[tid]
        if task.task_type == TaskType.HABIT:
            task.skip_count += 1
            task.status = TaskStatus.SKIPPED
            task.completed_at = datetime.now()
            tm._save_task(task)
            task.scheduled_time = datetime.now() + timedelta(seconds=task.interval_seconds)
            task.status = TaskStatus.PENDING
            task.result = None
            task.error = None
            tm._save_task(task)
            tm._schedule_reminder_task(task)
        else:
            task.status = TaskStatus.SKIPPED
            task.completed_at = datetime.now()
            tm._save_task(task)
        return jsonify({"success": True})
    return jsonify({"error": "Task not found"}), 404

@admin_bp.route("/hibernate/check", methods=["GET"])
def api_hibernate_check():
    maint_system = MS()
    if not maint_system:
        return jsonify({"error": "Maintenance system unavailable"}), 503
    from maintenance import config as mc
    state = maint_system.state.state.value
    strategy = mc.SCHEDULE_STRATEGY
    tracker = maint_system.tracker
    tm = tracker.minutes_since_last_request()
    window = None
    if strategy == "fixed":
        window = {"type": "fixed", "hour": mc.FIXED_HOUR}
    else:
        pred = tracker.best_idle_window(mc.PREDICTIVE_MIN_FREE_HOURS, mc.PREDICTIVE_MAX_HOUR)
        if pred:
            window = {"type": "predictive", "start": pred[0], "end": pred[1]}
    return jsonify({
        "state": state,
        "strategy": strategy,
        "minutes_since_last_request": tm,
        "request_count": tracker.request_count(),
        "window": window,
        "idle_timeout": mc.IDLE_TIMEOUT_MINUTES,
        "next_maint": getattr(maint_system, "_next_maint_at", None),
    })

@admin_bp.route("/hibernate/archive", methods=["POST"])
def api_hibernate_archive():
    maint_system = MS()
    if not maint_system:
        return jsonify({"error": "Maintenance system unavailable"}), 503
    data = request.get_json() or {}
    arg = data.get("time", "now")
    import re
    if arg.lower() == "now":
        if not maint_system.trigger_maintenance():
            return jsonify({"error": "Cannot start maintenance"}), 400
        return jsonify({"success": True, "message": "Maintenance started"})
    m = re.match(r'^(\d+)\s*(d|h|m)?$', arg, re.IGNORECASE)
    if not m:
        return jsonify({"error": f"Invalid time format: {arg}"}), 400
    amount = int(m.group(1))
    unit = (m.group(2) or 's').lower()
    multipliers = {'d': 86400, 'h': 3600, 'm': 60, 's': 1}
    seconds = amount * multipliers.get(unit, 1)
    target = datetime.now() + timedelta(seconds=seconds)
    maint_system._next_maint_at = target
    return jsonify({"success": True, "next_maintenance": target.isoformat()})

@admin_bp.route("/hibernate/sleep", methods=["POST"])
def api_hibernate_sleep():
    maint_system = MS()
    if not maint_system:
        return jsonify({"error": "Maintenance system unavailable"}), 503
    if not maint_system.trigger_standby():
        return jsonify({"error": "Cannot enter standby"}), 400
    return jsonify({"success": True, "message": "Entered standby mode"})

@admin_bp.route("/agents", methods=["GET"])
def api_agents():
    db = DB()
    if not db:
        return jsonify({"agents": []})
    conn = db._get_connection()
    rows = conn.execute(
        "SELECT u.uid, u.nickname, u.display_name, u.bound_to, "
        "bu.nickname as bound_nick, bu.display_name as bound_disp "
        "FROM users u LEFT JOIN users bu ON u.bound_to = bu.uid "
        "WHERE u.bound_to IS NOT NULL OR u.uid IN "
        "(SELECT bound_to FROM users WHERE bound_to IS NOT NULL) "
        "ORDER BY u.uid"
    ).fetchall()
    agents = []
    for r in rows:
        agents.append({
            "uid": r["uid"],
            "nickname": r["nickname"],
            "display_name": r["display_name"],
            "bound_to": r["bound_to"],
            "bound_name": r["bound_disp"] or r["bound_nick"],
        })
    return jsonify({"agents": agents})

@admin_bp.route("/agent/create", methods=["POST"])
def api_agent_create():
    db = DB()
    auth_manager = AM()
    data = request.get_json() or {}
    agent_name = data.get("name", "")
    bound_uid = data.get("uid", 1)
    if not agent_name:
        return jsonify({"error": "Missing agent name"}), 400
    if not db:
        return jsonify({"error": "DB unavailable"}), 503
    conn = db._get_connection()
    user = conn.execute("SELECT uid, nickname, display_name FROM users WHERE uid = ?",
                        (bound_uid,)).fetchone()
    if not user:
        return jsonify({"error": f"User {bound_uid} not found"}), 404
    existing = db.get_bound_agent(bound_uid)
    if existing:
        return jsonify({"error": f"User already bound to agent {existing}"}), 400
    agent_uid = db.create_agent(bound_uid, agent_name)
    result = {"agent_uid": agent_uid, "name": agent_name}
    if auth_manager and hasattr(auth_manager, "api_key"):
        try:
            raw_key, _ = auth_manager.api_key.create_key(
                uid=agent_uid, name=f"{agent_name}-agent",
                scopes="write", expires_days=365,
            )
            result["api_key"] = raw_key
        except Exception:
            logger.warning("Operation failed", exc_info=True)
    return jsonify({"success": True, "agent": result})

@admin_bp.route("/agent/bind", methods=["POST"])
def api_agent_bind():
    db = DB()
    data = request.get_json() or {}
    agent_uid = data.get("agent_uid")
    user_id = data.get("user_id")
    if not agent_uid or not user_id:
        return jsonify({"error": "Missing agent_uid or user_id"}), 400
    if not db:
        return jsonify({"error": "DB unavailable"}), 503
    conn = db._get_connection()
    agent = conn.execute("SELECT nickname FROM users WHERE uid = ?", (agent_uid,)).fetchone()
    user = conn.execute("SELECT nickname, display_name FROM users WHERE uid = ?", (user_id,)).fetchone()
    if not agent or not user:
        return jsonify({"error": "Agent or user not found"}), 404
    agent_bound = db.get_bound_user(agent_uid)
    user_bound = db.get_bound_agent(user_id)
    if agent_bound and agent_bound != user_id:
        return jsonify({"error": f"Agent already bound to uid={agent_bound}"}), 400
    if user_bound and user_bound != agent_uid:
        return jsonify({"error": f"User already bound to agent uid={user_bound}"}), 400
    db.bind_agent(user_id, agent_uid)
    return jsonify({"success": True})

@admin_bp.route("/agent/unbind", methods=["POST"])
def api_agent_unbind():
    db = DB()
    data = request.get_json() or {}
    agent_uid = data.get("agent_uid")
    if not agent_uid:
        return jsonify({"error": "Missing agent_uid"}), 400
    if not db:
        return jsonify({"error": "DB unavailable"}), 503
    conn = db._get_connection()
    agent = conn.execute("SELECT bound_to FROM users WHERE uid = ?", (agent_uid,)).fetchone()
    if not agent or not agent["bound_to"]:
        return jsonify({"error": "Agent not bound"}), 404
    conn.execute("UPDATE users SET bound_to = NULL WHERE uid = ?", (agent_uid,))
    conn.execute("UPDATE users SET bound_to = NULL WHERE uid = ?", (agent["bound_to"],))
    conn.commit()
    return jsonify({"success": True})

@admin_bp.route("/detail/chats", methods=["POST"])
def api_detail_chats():
    from models import toggle_detail_chats
    new_state = toggle_detail_chats()
    return jsonify({"success": True, "enabled": new_state})

@admin_bp.route("/detail/actions", methods=["POST"])
def api_detail_actions():
    from models import toggle_detail_actions
    new_state = toggle_detail_actions()
    return jsonify({"success": True, "enabled": new_state})

@admin_bp.route("/detail/status", methods=["GET"])
def api_detail_status():
    from models import DETAIL_CHATS, DETAIL_ACTIONS
    return jsonify({"detail_chats": DETAIL_CHATS, "detail_actions": DETAIL_ACTIONS})

@admin_bp.route("/timer/toggle", methods=["POST"])
def api_timer_toggle():
    from plugins.pipeline import toggle_timer
    enabled = toggle_timer()
    return jsonify({"success": True, "enabled": enabled})

@admin_bp.route("/stop", methods=["POST"])
def api_stop():
    from main import append_log
    append_log("system", "WARNING", "Web admin triggered shutdown")
    def _delayed_stop():
        time.sleep(0.5)
        os._exit(0)
    t = threading.Thread(target=_delayed_stop, daemon=True)
    t.start()
    return jsonify({"success": True, "message": "Server stopping..."})

@admin_bp.route("/prompt", methods=["GET"])
def api_prompt():
    prompt_engine = PE()
    uid = request.args.get("uid", 0, type=int)
    if not prompt_engine:
        return jsonify({"error": "PromptEngine unavailable"}), 503
    user_info = {"uid": uid, "nickname": f"User_{uid}"}
    try:
        prompt = prompt_engine.build_system_prompt(user_info)
    except Exception as e:
        logger.error("Failed to build system prompt: %s", e, exc_info=True)
        return jsonify({"error": "Internal error"}), 500
    return jsonify({"uid": uid, "prompt": prompt, "length": len(prompt) if prompt else 0})

@admin_bp.route("/plans", methods=["GET"])
def api_plans():
    db = DB()
    uid = request.args.get("uid", type=int)
    if not db:
        return jsonify({"plans": []})
    from db.plan_store import PlanStore
    store = PlanStore(db)
    goals = store.list_goals(uid or 0) if uid else []
    result = []
    for g in goals:
        phases_data = []
        if g.phases:
            for p in g.phases:
                phases_data.append({"title": p.title, "status": p.status, "position": p.position})
        result.append({
            "goal_id": g.goal_id,
            "title": g.title,
            "description": g.description,
            "status": g.status,
            "progress": g.progress,
            "phases": phases_data,
        })
    return jsonify({"plans": result})

@admin_bp.route("/plan/today", methods=["GET"])
def api_plan_today():
    db = DB()
    uid = request.args.get("uid", type=int)
    if not uid:
        return jsonify({"error": "Missing uid"}), 400
    if not db:
        return jsonify({"error": "DB unavailable"}), 503
    from db.plan_engine import PlanEngine
    from db.plan_store import PlanStore
    store = PlanStore(db)
    plan_engine = PlanEngine(store)
    today = date.today().isoformat()
    summary = plan_engine.daily_summary(uid, today)
    return jsonify(summary)

@admin_bp.route("/plan/check", methods=["POST"])
def api_plan_check():
    db = DB()
    data = request.get_json() or {}
    tid = data.get("task_id", "")
    note = data.get("note", "")
    if not tid:
        return jsonify({"error": "Missing task_id"}), 400
    if not db:
        return jsonify({"error": "DB unavailable"}), 503
    from db.plan_engine import PlanEngine
    from db.plan_store import PlanStore
    store = PlanStore(db)
    plan_engine = PlanEngine(store)
    plan_engine.check_off(tid, note)
    return jsonify({"success": True})

@admin_bp.route("/exports", methods=["POST"])
def api_export():
    db = DB()
    data = request.get_json() or {}
    sub = data.get("type", "")
    uid = data.get("uid")
    cid = data.get("cid")
    if not all([sub, uid, cid]):
        return jsonify({"error": "Missing type/uid/cid"}), 400
    from utils.crypto import MessageCipher
    cipher = db._cipher
    conn = db._get_connection()
    if sub in ("chats", "messages"):
        rows = conn.execute(
            "SELECT message_id, role, content, round_index, timestamp FROM messages "
            "WHERE chat_id = ? ORDER BY message_id ASC", (cid,)
        ).fetchall()
        if not rows:
            return jsonify({"error": "No messages"}), 404
        export = {
            "type": "chat_messages", "user_id": uid, "chat_id": cid,
            "exported_at": datetime.now().isoformat(),
            "messages": [{
                "message_id": r["message_id"], "role": r["role"],
                "content": cipher.decrypt(uid, r["content"] or ""),
                "round_index": r["round_index"], "timestamp": r["timestamp"],
            } for r in rows],
        }
    elif sub == "memories":
        rows = conn.execute(
            "SELECT id, round, content, created_at, type FROM memory_v2 "
            "WHERE user_id = ? AND chat_id = ? ORDER BY id ASC", (uid, cid)
        ).fetchall()
        if not rows:
            return jsonify({"error": "No memories"}), 404
        export = {
            "type": "memory_summaries", "user_id": uid, "chat_id": cid,
            "exported_at": datetime.now().isoformat(),
            "memories": [{
                "id": r["id"], "round": r["round"],
                "content": cipher.decrypt(uid, r["content"] or ""),
                "type": r["type"], "created_at": r["created_at"],
            } for r in rows],
        }
    else:
        return jsonify({"error": f"Unknown type: {sub}"}), 400
    return jsonify(export)

@admin_bp.route("/imports", methods=["POST"])
def api_import():
    db = DB()
    data = request.get_json() or {}
    sub = data.get("type", "")
    uid = data.get("uid")
    cid = data.get("cid")
    items = data.get("items", [])
    if not all([sub, uid, cid]) or not items:
        return jsonify({"error": "Missing fields"}), 400
    conn = db._get_connection()
    cipher = db._cipher
    count = 0
    if sub == "memories":
        for item in items:
            encrypted = cipher.encrypt(uid, item.get("content", ""))
            conn.execute(
                "INSERT INTO memory_v2 (user_id, chat_id, type, round, content, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (uid, cid, item.get("type", "exp"), item.get("round"), encrypted, item.get("created_at")),
            )
            count += 1
        conn.commit()
    elif sub in ("chats", "messages"):
        for item in items:
            encrypted = cipher.encrypt(uid, item.get("content", ""))
            conn.execute(
                "INSERT INTO messages (chat_id, role, content, round_index, timestamp) "
                "VALUES (?, ?, ?, ?, ?)",
                (cid, item.get("role", "user"), encrypted, item.get("round_index"), item.get("timestamp")),
            )
            count += 1
        conn.commit()
    else:
        return jsonify({"error": f"Unknown type: {sub}"}), 400
    return jsonify({"success": True, "imported": count})
