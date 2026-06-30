
# plan_api.py
# 计划系统 REST API — Flask Blueprint
#
# 提供三层计划模型 (Goal → Phase → DailyTask) 的 CRUD 接口。
# DAILY_PLAN 类型的提醒任务到期时，TaskManager 会调用 PlanEngine.generate_daily_plan
# 生成当日待办，并通过心跳接口推送给用户。

from flask import Blueprint, request, jsonify, g

from db.plan_store import PlanStore, Goal, Phase, DailyTask
from db.plan_engine import PlanEngine

plan_bp = Blueprint("plan_api", __name__)

_db = None
_auth_manager = None


def init_plan_api(db, auth_manager):
    global _db, _auth_manager
    _db = db
    _auth_manager = auth_manager


@plan_bp.before_request
def _require_auth():
    """复用全局认证，确保 g.user 可用。"""
    if _auth_manager:
        g.user = _auth_manager.authenticate(request)
    else:
        g.user = {"uid": 0}


def _get_engine():
    return PlanEngine(PlanStore(_db)) if _db else None


def _uid() -> int:
    return g.user.get("uid", 0) if g.user else 0


# ── Goal ──

@plan_bp.route("/api/plan/goals", methods=["GET"])
def list_goals():
    uid = _uid()
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401
    engine = _get_engine()
    if not engine:
        return jsonify({"error": "Plan system unavailable"}), 503
    goals = engine._store.list_goals(uid)
    return jsonify({
        "goals": [{"goal_id": gl.goal_id, "title": gl.title, "description": gl.description,
                    "deadline": gl.deadline, "status": gl.status, "progress": gl.progress,
                    "phases": len(gl.phases)} for gl in goals]
    })


@plan_bp.route("/api/plan/goals", methods=["POST"])
def create_goal():
    uid = _uid()
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    title = data.get("title", "")
    if not title:
        return jsonify({"error": "Missing title"}), 400
    engine = _get_engine()
    if not engine:
        return jsonify({"error": "Plan system unavailable"}), 503
    goal = engine.create_goal(uid, title, data.get("description", ""), data.get("deadline", ""))
    return jsonify({"goal_id": goal.goal_id, "title": goal.title})


# ── Phase ──

@plan_bp.route("/api/plan/phases/<goal_id>", methods=["GET"])
def list_phases(goal_id):
    uid = _uid()
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401
    engine = _get_engine()
    if not engine:
        return jsonify({"error": "Plan system unavailable"}), 503
    phases = engine._store.list_phases(goal_id)
    return jsonify({
        "phases": [{"phase_id": p.phase_id, "title": p.title, "description": p.description,
                    "start_date": p.start_date, "end_date": p.end_date,
                    "status": p.status, "progress": p.progress} for p in phases]
    })


@plan_bp.route("/api/plan/phases", methods=["POST"])
def add_phase():
    uid = _uid()
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    goal_id = data.get("goal_id", "")
    title = data.get("title", "")
    if not goal_id or not title:
        return jsonify({"error": "Missing goal_id or title"}), 400
    engine = _get_engine()
    if not engine:
        return jsonify({"error": "Plan system unavailable"}), 503
    phase = engine.add_phase(
        goal_id, title, data.get("description", ""),
        data.get("start_date", ""), data.get("end_date", "")
    )
    return jsonify({"phase_id": phase.phase_id, "title": phase.title})


# ── Daily Plan ──

@plan_bp.route("/api/plan/today", methods=["GET"])
def today_plan():
    """返回今日待办摘要。若今日还没有生成计划，会自动生成。"""
    uid = _uid()
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401
    engine = _get_engine()
    if not engine:
        return jsonify({"error": "Plan system unavailable"}), 503
    from datetime import date
    today = date.today().isoformat()
    # 确保今日计划已生成
    engine.generate_daily_plan(uid, today)
    summary = engine.daily_summary(uid, today)
    return jsonify(summary)


@plan_bp.route("/api/plan/generate", methods=["POST"])
def generate_plan():
    """手动生成指定日期的计划（默认今天）。"""
    uid = _uid()
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    date_str = data.get("date", "")
    engine = _get_engine()
    if not engine:
        return jsonify({"error": "Plan system unavailable"}), 503
    tasks = engine.generate_daily_plan(uid, date_str)
    return jsonify({
        "date": date_str,
        "count": len(tasks),
        "tasks": [{"task_id": t.task_id, "title": t.title, "status": t.status,
                    "duration": t.duration_min, "priority": t.priority} for t in tasks],
    })


# ── 任务操作 ──

@plan_bp.route("/api/plan/check", methods=["POST"])
def check_off():
    """标记一个 daily task 为 done。"""
    uid = _uid()
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    task_id = data.get("task_id", "")
    if not task_id:
        return jsonify({"error": "Missing task_id"}), 400
    engine = _get_engine()
    if not engine:
        return jsonify({"error": "Plan system unavailable"}), 503
    engine.check_off(task_id, data.get("note", ""))
    return jsonify({"success": True})


@plan_bp.route("/api/plan/skip", methods=["POST"])
def skip_task():
    """跳过一个 daily task。"""
    uid = _uid()
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    task_id = data.get("task_id", "")
    if not task_id:
        return jsonify({"error": "Missing task_id"}), 400
    engine = _get_engine()
    if not engine:
        return jsonify({"error": "Plan system unavailable"}), 503
    engine.skip_task(task_id)
    return jsonify({"success": True})
