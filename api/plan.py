
# plan_api.py
# 计划系统 REST API — Flask Blueprint

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


def _get_engine():
    return PlanEngine(PlanStore(_db)) if _db else None


@plan_bp.route("/api/plan/goals", methods=["GET"])
def list_goals():
    uid = g.user.get("uid", 0) if g.user else 0
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401
    engine = _get_engine()
    if not engine:
        return jsonify({"error": "Plan system unavailable"}), 503
    goals = engine._store.list_goals(uid)
    return jsonify({
        "goals": [{"goal_id": g.goal_id, "title": g.title, "description": g.description,
                    "deadline": g.deadline, "status": g.status, "progress": g.progress,
                    "phases": len(g.phases)} for g in goals]
    })


@plan_bp.route("/api/plan/goals", methods=["POST"])
def create_goal():
    uid = g.user.get("uid", 0) if g.user else 0
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


@plan_bp.route("/api/plan/today", methods=["GET"])
def today_plan():
    uid = g.user.get("uid", 0) if g.user else 0
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401
    engine = _get_engine()
    if not engine:
        return jsonify({"error": "Plan system unavailable"}), 503
    from datetime import date
    today = date.today().isoformat()
    summary = engine.daily_summary(uid, today)
    return jsonify(summary)


@plan_bp.route("/api/plan/check", methods=["POST"])
def check_off():
    uid = g.user.get("uid", 0) if g.user else 0
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    task_id = data.get("task_id", "")
    if not task_id:
        return jsonify({"error": "Missing task_id"}), 400
    engine = _get_engine()
    if not engine:
        return jsonify({"error": "Plan system unavailable"}), 503
    engine.check_off(task_id)
    return jsonify({"success": True})
