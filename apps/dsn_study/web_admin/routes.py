# apps/dsn_study/web_admin/routes.py
# 管理面板路由（迁移计划阶段 8）—— 端点形状沿用 dsn，数据源全部换新基座。
#
# 认证（8.3）：infra/auth 的 APIKeyManager（密钥来自 WEB_ADMIN_API_KEY，
# 未配置时启动自动生成随机密钥并打日志）+ 可选 TOTP（WEB_ADMIN_TOTP_SECRET）。
# 通过方式：请求头 X-Admin-Token（+ 可选 X-Admin-TOTP），或 ?admin_token=。
#
# 配置写入（8.6）：/config/set、/config/undo **降级为只读 + 明确提示**
# （dsn 版直写 .env；study 的 Config 是导入期快照，写 env 不生效，
# 与其给一个"看起来成功"的假写入口，不如明说不支持）。

from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from pathlib import Path

from flask import Blueprint, jsonify, request, render_template, current_app

from infra.auth import APIKeyManager, TOTP

logger = logging.getLogger("StudyWebAdmin")

admin_bp = Blueprint("study_web_admin", __name__, url_prefix="/api/admin",
                     template_folder="templates")

# ── 模块级注入（boot 时 set） ──
_engine = None
_auth_manager = None
_api_keys: APIKeyManager | None = None
_totp: TOTP | None = None
_server_start = time.time()

#: 敏感配置项脱敏显示
_SENSITIVE_KEYS = {"OPENAI_API_KEY", "VISION_API_KEY", "WEB_ADMIN_API_KEY",
                   "WEB_ADMIN_TOTP_SECRET", "TOKEN", "SECRET", "PASSWORD",
                   "ASR_API_KEY", "MEMORY_EMBEDDING_API_KEY"}


def init_web_admin(engine, api_key: str = "", totp_secret: str = "") -> str:
    """注入依赖并装配认证。返回生效的面板密钥（供日志打印）。"""
    global _engine, _auth_manager, _api_keys, _totp
    _engine = engine
    _api_keys = APIKeyManager(prefix="adm", secret=totp_secret or "dsn-study-admin")
    if api_key:
        _api_keys.register(api_key, label="web-admin")
    else:
        api_key = _api_keys.generate(label="web-admin-auto")
        logger.warning("WEB_ADMIN_API_KEY 未配置，已自动生成面板密钥: %s", api_key)
    if totp_secret:
        _totp = TOTP()
    return api_key


def _check_auth() -> bool:
    if _api_keys is None:
        return False
    token = (request.headers.get("X-Admin-Token", "")
             or request.args.get("admin_token", ""))
    if not token or not _api_keys.verify(token):
        return False
    if _totp is not None:
        code = request.headers.get("X-Admin-TOTP", "")
        secret = os.environ.get("WEB_ADMIN_TOTP_SECRET", "")
        if not code or not secret or not _totp.verify(code, secret):
            return False
    return True


@admin_bp.before_request
def _require_auth():
    # 面板页面本身免认证（与 dsn 白名单 "/" 一致）：页面不含数据，
    # 数据面全部走需要密钥的 JSON API
    if request.method == "GET" and request.path in ("/api/admin/", "/api/admin"):
        return
    if not _check_auth():
        return jsonify({"error": "Unauthorized"}), 401


# ── 惰性访问器（对齐 dsn routes.py 的形态，但落在 dsn_study） ──

def EN():
    return _engine


def DB():
    return _engine.db_mgr if _engine else None


# ── 运行状态 ──

@admin_bp.route("/status", methods=["GET"])
def status():
    engine = EN()
    if engine is None:
        return jsonify({"error": "engine unavailable"}), 503
    data = {
        "uptime_seconds": round(time.time() - _server_start, 1),
        "app": "dsn_study",
        "session_id": engine.session_id,
        "tools": len(engine.skill_registry.list_active_tools()),
        "skills": len(engine.skill_registry._active_skills),
        "pipeline": engine.pipeline_runner is not None,
        "personality": engine.personality is not None,
        "topics_enabled": bool(engine.memory_system
                               and engine.memory_system._topics is not None),
        "memory": engine.memory_system is not None,
        "task_manager": engine.task_manager is not None,
        "voice": engine.voice is not None,
        "vision": engine.vision_coordinator is not None,
    }
    try:
        conn = DB()._get_connection()
        for table in ("questions", "tasks", "chat_rounds"):
            try:
                row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
                data[f"{table}_count"] = row["n"] if row else 0
            except Exception:   # noqa: BLE001
                data[f"{table}_count"] = None
    except Exception:   # noqa: BLE001
        pass
    return jsonify({"success": True, **data})


# ── 资源槽 / 模型状态（8.4：新基座数据源） ──

@admin_bp.route("/resources", methods=["GET"])
def resources():
    """infra ResourcePool：资源清单 + 池状态 + 插槽状态。"""
    try:
        from apps.dsn_study.models.resource_setup import get_study_pool
        pool = get_study_pool()
        if pool is None:
            return jsonify({"success": True, "resources": [], "note": "资源池未初始化"})
        return jsonify({
            "success": True,
            "resources": pool.list_resources(),
            "pool": pool.status(),
            "slots": pool.slot_status(),
        })
    except Exception as e:   # noqa: BLE001
        return jsonify({"success": False, "error": str(e)}), 500


@admin_bp.route("/models", methods=["GET"])
def models():
    """infra ModelOrchestrator 运行状态。"""
    try:
        from infra.orchestrator import ModelOrchestrator
        orch = ModelOrchestrator.get_instance()
        return jsonify({"success": True, "orchestrator": orch.status()})
    except Exception as e:   # noqa: BLE001
        return jsonify({"success": False, "error": str(e)}), 500


# ── 题库（验收项：面板能看题库） ──

@admin_bp.route("/questions", methods=["GET"])
def questions_stats():
    engine = EN()
    db = DB()
    if db is None:
        return jsonify({"error": "db unavailable"}), 503
    conn = db._get_connection()
    by_subject = [dict(r) for r in conn.execute(
        "SELECT s.name AS subject, COUNT(*) AS n FROM questions q"
        " LEFT JOIN subjects s ON s.subject_id = q.subject_id"
        " GROUP BY q.subject_id ORDER BY n DESC").fetchall()]
    by_difficulty = [dict(r) for r in conn.execute(
        "SELECT difficulty, COUNT(*) AS n FROM questions"
        " GROUP BY difficulty ORDER BY difficulty").fetchall()]
    # 错题本在 error_logs 表（questions 表无 is_error 列）
    try:
        errors = engine.question_store.get_total_errors(1)
    except Exception:   # noqa: BLE001
        errors = 0
    total = conn.execute("SELECT COUNT(*) AS n FROM questions").fetchone()
    recent = [dict(r) for r in conn.execute(
        "SELECT question_id, content, difficulty, created_at FROM questions"
        " ORDER BY question_id DESC LIMIT 10").fetchall()]
    return jsonify({
        "success": True,
        "total": total["n"] if total else 0,
        "by_subject": by_subject,
        "by_difficulty": by_difficulty,
        "errors": errors,
        "recent": recent,
    })


# ── 任务 / 提醒 ──

@admin_bp.route("/reminders", methods=["GET"])
def reminders():
    db = DB()
    if db is None:
        return jsonify({"error": "db unavailable"}), 503
    uid = request.args.get("uid", type=int)
    conn = db._get_connection()
    sql = ("SELECT task_id, task_type, user_id, status, scheduled_time,"
           " interval_seconds, created_at FROM tasks")
    args: list = []
    if uid:
        sql += " WHERE user_id = ?"
        args.append(uid)
    sql += " ORDER BY created_at DESC LIMIT 100"
    try:
        rows = [dict(r) for r in conn.execute(sql, tuple(args)).fetchall()]
    except Exception:   # noqa: BLE001 - tasks 表未建（TaskManager 关闭）
        rows = []
    notifs = []
    try:
        notifs = [dict(r) for r in conn.execute(
            "SELECT notification_id, task_id, user_id, delivered, dismissed,"
            " created_at FROM task_notifications ORDER BY notification_id"
            " DESC LIMIT 50").fetchall()]
    except Exception:   # noqa: BLE001
        pass
    return jsonify({"success": True, "tasks": rows, "notifications": notifs})


@admin_bp.route("/reminder/cancel", methods=["POST"])
def reminder_cancel():
    """取消任务（对齐 dsn：task_id 前缀匹配）。"""
    engine = EN()
    if engine is None or engine.task_manager is None:
        return jsonify({"success": False, "error": "TaskManager 未启用"}), 503
    data = request.get_json(silent=True) or {}
    task_id = str(data.get("task_id", "")).strip()
    if not task_id:
        return jsonify({"error": "缺少 task_id"}), 400
    tm = engine.task_manager
    target = None
    for tid in list(tm._tasks.keys()) if hasattr(tm, "_tasks") else []:
        if tid.startswith(task_id):
            target = tid
            break
    if target is None:
        return jsonify({"success": False, "error": "任务不存在"}), 404
    ok = tm.cancel_task(target) if hasattr(tm, "cancel_task") else False
    return jsonify({"success": bool(ok), "task_id": target})


@admin_bp.route("/reminder/skip", methods=["POST"])
def reminder_skip():
    engine = EN()
    if engine is None or engine.task_manager is None:
        return jsonify({"success": False, "error": "TaskManager 未启用"}), 503
    data = request.get_json(silent=True) or {}
    task_id = str(data.get("task_id", "")).strip()
    if not task_id:
        return jsonify({"error": "缺少 task_id"}), 400
    try:
        engine.task_manager.skip_task(task_id)
        return jsonify({"success": True})
    except Exception as e:   # noqa: BLE001
        return jsonify({"success": False, "error": str(e)}), 500


# ── 插件 / 技能 ──

@admin_bp.route("/plugins", methods=["GET"])
def plugins():
    """技能清单（dsn 的 plugin_manager → study 的技能注册表）。"""
    engine = EN()
    if engine is None:
        return jsonify({"error": "engine unavailable"}), 503
    reg = engine.skill_registry
    items = []
    for key, spec in reg._tool_specs.items():
        items.append({
            "key": key,
            "skill": key.split(".")[0],
            "description": (spec or {}).get("description", ""),
        })
    diags = reg.diagnostics()
    return jsonify({
        "success": True,
        "plugins": sorted({i["skill"] for i in items}),
        "tools": items,
        "undispatchable": len(diags.get("reports", [])) and [
            r for r in diags["reports"] if r.get("issues")],
    })


# ── 记忆（chat_rounds 形态） ──

@admin_bp.route("/memory/users", methods=["GET"])
def memory_users():
    db = DB()
    conn = db._get_connection()
    rows = [dict(r) for r in conn.execute(
        "SELECT user_id, COUNT(*) AS rounds, MIN(created_at) AS first_round,"
        " MAX(created_at) AS last_round FROM chat_rounds"
        " GROUP BY user_id").fetchall()]
    memos = [dict(r) for r in conn.execute(
        "SELECT user_id, COUNT(*) AS n FROM memory_v2 WHERE type='memo'"
        " GROUP BY user_id").fetchall()]
    memo_map = {m["user_id"]: m["n"] for m in memos}
    for r in rows:
        r["memos"] = memo_map.get(r["user_id"], 0)
    return jsonify({"success": True, "users": rows})


@admin_bp.route("/memory/chats/<int:uid>", methods=["GET"])
def memory_chats(uid: int):
    """某用户的会话列表（chat_rounds 按 chat_id 聚合）。"""
    db = DB()
    conn = db._get_connection()
    rows = [dict(r) for r in conn.execute(
        "SELECT chat_id, COUNT(*) AS rounds, MAX(round_index) AS last_round,"
        " MIN(created_at) AS first_round, MAX(created_at) AS last_round"
        " FROM chat_rounds WHERE user_id = ? GROUP BY chat_id"
        " ORDER BY MAX(created_at) DESC", (uid,)).fetchall()]
    return jsonify({"success": True, "chats": rows})


@admin_bp.route("/memory/list/<int:uid>/<int:cid>", methods=["GET"])
def memory_list(uid: int, cid: int):
    """记忆明细：exp/memo（memory_v2）+ 原始轮次（chat_rounds，?rounds=1）。"""
    db = DB()
    conn = db._get_connection()
    mems = [dict(r) for r in conn.execute(
        "SELECT id, type, round, content, created_at FROM memory_v2"
        " WHERE user_id = ? AND chat_id = ? ORDER BY id DESC LIMIT 100",
        (uid, cid)).fetchall()]
    rounds = []
    if request.args.get("rounds"):
        rounds = [dict(r) for r in conn.execute(
            "SELECT round_index, user_msg, assistant_reply, created_at"
            " FROM chat_rounds WHERE user_id = ? AND chat_id = ?"
            " ORDER BY round_index DESC LIMIT 50", (uid, cid)).fetchall()]
    return jsonify({"success": True, "memories": mems, "rounds": rounds})


@admin_bp.route("/memory/query", methods=["POST"])
def memory_query():
    """关键词 + 时间范围记忆检索（走 MemorySystem.search）。"""
    engine = EN()
    data = request.get_json(silent=True) or {}
    keywords = [k.strip() for k in str(data.get("keywords", "")).split(",")
                if k.strip()]
    if not keywords:
        return jsonify({"error": "缺少 keywords"}), 400
    if engine is None or engine.memory_system is None:
        return jsonify({"success": False, "error": "记忆系统未启用"}), 503
    try:
        results = engine.memory_system.search(
            int(data.get("uid", 1)), keywords,
            limit=int(data.get("limit", 20)))
        return jsonify({"success": True, "results": results})
    except Exception as e:   # noqa: BLE001
        return jsonify({"success": False, "error": str(e)}), 500


@admin_bp.route("/memory/reindex", methods=["POST"])
def memory_reindex():
    """后台线程重建 embedding 索引。"""
    engine = EN()
    if engine is None or engine.memory_system is None:
        return jsonify({"success": False, "error": "记忆系统未启用"}), 503

    def _work():
        try:
            for _ in engine.memory_system.reindex_embeddings():
                pass
        except Exception:   # noqa: BLE001
            logger.warning("记忆重建失败", exc_info=True)

    threading.Thread(target=_work, daemon=True, name="admin-reindex").start()
    return jsonify({"success": True, "started": True})


# ── 话题（阶段 7 的 TopicManager） ──

@admin_bp.route("/memory/topics/<int:uid>", methods=["GET"])
def memory_topics(uid: int):
    engine = EN()
    topics = getattr(engine.memory_system, "_topics", None) \
        if engine and engine.memory_system else None
    if topics is None:
        return jsonify({"success": True, "topics": [],
                        "note": "话题系统未启用（TOPIC_ENABLED=false）"})
    chat_id = request.args.get("chat_id", type=int)
    items = topics.store.list_topics(uid, chat_id, status=None)
    return jsonify({"success": True, "topics": [
        {k: t.get(k) for k in ("topic_id", "chat_id", "title", "status",
                               "is_pinned", "summary", "last_active_at")}
        for t in items]})


@admin_bp.route("/memory/topics/<topic_id>/<action>", methods=["POST"])
def memory_topic_action(topic_id: str, action: str):
    """close / reopen / pin / unpin（对齐 dsn 形状）。"""
    engine = EN()
    topics = getattr(engine.memory_system, "_topics", None) \
        if engine and engine.memory_system else None
    if topics is None:
        return jsonify({"success": False, "error": "话题系统未启用"}), 503
    uid = request.args.get("uid", 1)
    try:
        if action == "close":
            ok = topics.close_topic(uid, 0, topic_id)
        elif action == "reopen":
            ok = topics.reopen_topic(topic_id)
        elif action == "pin":
            ok = topics.pin_topic(uid, 0, topic_id, True)
        elif action == "unpin":
            ok = topics.pin_topic(uid, 0, topic_id, False)
        else:
            return jsonify({"error": f"未知 action: {action}"}), 400
        return jsonify({"success": bool(ok)})
    except Exception as e:   # noqa: BLE001
        return jsonify({"success": False, "error": str(e)}), 500


# ── 人格（harness PEV3） ──

@admin_bp.route("/persona/list", methods=["GET"])
def persona_list():
    engine = EN()
    if engine is None or engine.personality is None:
        return jsonify({"success": True, "cards": [],
                        "note": "人格系统未启用"})
    cards = engine.personality.list_cards()
    return jsonify({"success": True, "cards": cards})


@admin_bp.route("/persona/status/<card_id>", methods=["GET"])
def persona_status(card_id: str):
    engine = EN()
    if engine is None or engine.personality is None:
        return jsonify({"success": False, "error": "人格系统未启用"}), 503
    uid = request.args.get("uid", 1)
    snapshot = engine.personality.get_personality_status(int(uid))
    card = engine.personality.get_card(card_id)
    return jsonify({
        "success": True,
        "card_id": card_id,
        "card": card.to_dict() if card and hasattr(card, "to_dict") else str(card),
        "snapshot": snapshot,
    })


# ── 配置（只读 + 明确不支持写入） ──

@admin_bp.route("/config", methods=["GET"])
def config_snapshot():
    from apps.dsn_study.config import Config
    items = {}
    for key in sorted(dir(Config)):
        if key.isupper() and not key.startswith("_"):
            val = getattr(Config, key)
            if any(s in key for s in _SENSITIVE_KEYS) and val:
                items[key] = "***"
            else:
                items[key] = str(val)
    return jsonify({"success": True, "config": items,
                    "writable": False,
                    "note": "dsn_study 的 Config 为导入期快照；面板只读，"
                            "修改请改 .env 后重启"})


@admin_bp.route("/config/set", methods=["POST"])
def config_set():
    return jsonify({"success": False, "error": "面板不支持写配置（Config 为"
                    " 导入期快照）。请修改 .env 后重启应用。"}), 501


@admin_bp.route("/config/undo", methods=["POST"])
def config_undo():
    return jsonify({"success": False, "error": "面板不支持写配置（无 .env"
                    " 备份可恢复）。请手工修改 .env。"}), 501


# ── 日志 ──

@admin_bp.route("/logs", methods=["GET"])
def logs():
    log_dir = Path(current_app.config.get("LOG_DIR", "logs"))
    log_file = log_dir / "dsn_study.log"
    if not log_file.is_file():
        return jsonify({"success": True, "logs": []})
    lines = log_file.read_text(encoding="utf-8", errors="replace"
                               ).splitlines()[-200:]
    return jsonify({"success": True, "logs": lines})


# ── 提示词 / 计划 / 打卡 ──

@admin_bp.route("/prompt", methods=["GET"])
def prompt_preview():
    engine = EN()
    uid = request.args.get("uid", 1)
    if engine is None or engine.prompt_builder is None:
        return jsonify({"error": "prompt builder unavailable"}), 503
    return jsonify({"success": True,
                    "prompt": engine.prompt_builder.build(uid=int(uid))})


@admin_bp.route("/plans", methods=["GET"])
def plans():
    engine = EN()
    if engine is None or engine.plan_engine is None:
        return jsonify({"error": "plan engine unavailable"}), 503
    uid = request.args.get("uid", 1)
    try:
        goals = engine.plan_engine._store.list_goals(int(uid))
        return jsonify({"success": True, "goals": [
            g.to_dict() if hasattr(g, "to_dict") else {
                "goal_id": getattr(g, "goal_id", None),
                "title": getattr(g, "title", ""),
                "status": getattr(g, "status", ""),
            } for g in goals]})
    except Exception as e:   # noqa: BLE001
        return jsonify({"success": False, "error": str(e)}), 500


@admin_bp.route("/plan/today", methods=["GET"])
def plan_today():
    engine = EN()
    uid = request.args.get("uid", 1)
    if engine is None or engine.plan_engine is None:
        return jsonify({"error": "plan engine unavailable"}), 503
    return jsonify({"success": True,
                    "summary": engine.plan_engine.daily_summary(int(uid))})


@admin_bp.route("/plan/check", methods=["POST"])
def plan_check():
    engine = EN()
    data = request.get_json(silent=True) or {}
    if engine is None or engine.plan_engine is None:
        return jsonify({"error": "plan engine unavailable"}), 503
    try:
        # PlanEngine.check_off(task_id, note) —— dsn 的 uid+action 形状不适用
        if data.get("action") == "skip":
            engine.plan_engine.skip_task(str(data.get("task_id", "")))
        else:
            engine.plan_engine.check_off(str(data.get("task_id", "")))
        return jsonify({"success": True})
    except Exception as e:   # noqa: BLE001
        return jsonify({"success": False, "error": str(e)}), 500


@admin_bp.route("/checkin/calendar", methods=["GET"])
def checkin_calendar():
    engine = EN()
    uid = request.args.get("uid", 1)
    year = request.args.get("year", type=int) or time.localtime().tm_year
    month = request.args.get("month", type=int) or time.localtime().tm_mon
    if engine is None or engine.checkin_store is None:
        return jsonify({"error": "checkin store unavailable"}), 503
    cal = engine.checkin_store.month_calendar(int(uid), year, month)
    streak = engine.checkin_store.compute_checkin_streak(int(uid))
    return jsonify({"success": True, "calendar": cal,
                    "streak": streak})


# ── 停机 ──

@admin_bp.route("/stop", methods=["POST"])
def stop_server():
    """延迟 0.5s 关服（对齐 dsn；受面板密钥保护）。"""
    logger.warning("管理面板触发停机")

    def _die():
        time.sleep(0.5)
        os._exit(0)

    threading.Thread(target=_die, daemon=True).start()
    return jsonify({"success": True, "message": "服务器将在 0.5s 后退出"})


# ── 面板页面 ──

@admin_bp.route("/", methods=["GET"])
def dashboard():
    """单页面板（?admin_token= 供 <a> 直接访问；数据面走 JSON API）。"""
    return render_template("dashboard.html")
