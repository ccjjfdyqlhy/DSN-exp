# reminder_api.py
# 提醒任务 REST API — Flask Blueprint
# 供客户端 (minimal.py) 拉取/完成/取消提醒

from flask import Blueprint, request, jsonify, g
from datetime import datetime, timedelta
import json

from tasks import TaskType, TaskStatus

reminder_bp = Blueprint("reminder_api", __name__)

_db = None
_task_manager = None
_auth_manager = None


def init_reminder_api(db, task_manager, auth_manager):
    global _db, _task_manager, _auth_manager
    _db = db
    _task_manager = task_manager
    _auth_manager = auth_manager


@reminder_bp.before_request
def _require_auth():
    """复用全局认证"""
    if _auth_manager:
        user = _auth_manager.authenticate(request)
        g.user = user
    else:
        g.user = {"uid": 0}


@reminder_bp.route("/api/reminder/list")
def list_reminders():
    """返回当前用户的所有 PENDING 提醒任务"""
    uid = g.user.get("uid", 0) if g.user else 0
    if not uid:
        return jsonify({"reminders": []})

    conn = _db._get_connection()
    rows = conn.execute(
        "SELECT task_id, task_type, params, priority, scheduled_time, "
        "interval_seconds, skip_count, created_at FROM tasks "
        "WHERE user_id = ? AND task_type IN (?, ?, ?) AND status = ? "
        "ORDER BY scheduled_time ASC LIMIT 50",
        (uid, TaskType.REMINDER.value, TaskType.HABIT.value,
         TaskType.COUNTDOWN.value, TaskStatus.PENDING.value),
    ).fetchall()

    reminders = []
    cipher = _db._cipher
    for r in rows:
        try:
            params = json.loads(r["params"])
        except Exception:
            params = {}
        reminders.append({
            "task_id": r["task_id"],
            "task_type": r["task_type"],
            "text": params.get("text", ""),
            "scheduled_time": r["scheduled_time"],
            "interval_seconds": r["interval_seconds"] or 0,
            "priority": r["priority"],
            "skip_count": r["skip_count"],
            "created_at": r["created_at"],
        })

    return jsonify({"reminders": reminders})


@reminder_bp.route("/api/reminder/done", methods=["POST"])
def mark_done():
    """标记一条提醒为已完成"""
    uid = g.user.get("uid", 0) if g.user else 0
    data = request.get_json(silent=True) or {}
    task_id = data.get("task_id", "")

    if not task_id:
        return jsonify({"success": False, "error": "缺少 task_id"}), 400

    if _task_manager is None:
        return jsonify({"success": False, "error": "TaskManager 不可用"}), 500

    if task_id not in _task_manager.tasks:
        return jsonify({"success": False, "error": "任务不存在"}), 404

    task = _task_manager.tasks[task_id]
    if task.user_id != uid:
        return jsonify({"success": False, "error": "无权操作"}), 403

    # 标记完成
    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.now()
    _task_manager._save_task(task)

    text = task.params.get("text", "")

    # 周期性 HABIT: 自动创建下一个
    next_time = None
    if task.task_type == TaskType.HABIT and task.interval_seconds > 0:
        next_time = datetime.now() + timedelta(seconds=task.interval_seconds)
        new_id = _task_manager.create_task(
            task_type=TaskType.HABIT,
            user_id=uid,
            chat_id=task.chat_id,
            params={"text": text},
            priority=task.priority,
            scheduled_time=next_time,
            interval_seconds=task.interval_seconds,
        )

    return jsonify({
        "success": True,
        "action": "completed",
        "text": text,
        "task_type": task.task_type.value,
        "next_scheduled": next_time.isoformat() if next_time else None,
        "next_task_id": new_id if task.task_type == TaskType.HABIT and task.interval_seconds > 0 else None,
    })


@reminder_bp.route("/api/reminder/cancel", methods=["POST"])
def cancel_reminder():
    """取消一条提醒"""
    uid = g.user.get("uid", 0) if g.user else 0
    data = request.get_json(silent=True) or {}
    task_id = data.get("task_id", "")

    if not task_id:
        return jsonify({"success": False, "error": "缺少 task_id"}), 400

    if _task_manager is None:
        return jsonify({"success": False, "error": "TaskManager 不可用"}), 500

    if task_id not in _task_manager.tasks:
        return jsonify({"success": False, "error": "任务不存在"}), 404

    task = _task_manager.tasks[task_id]
    if task.user_id != uid:
        return jsonify({"success": False, "error": "无权操作"}), 403

    task.status = TaskStatus.CANCELLED
    task.completed_at = datetime.now()
    _task_manager._save_task(task)

    return jsonify({"success": True, "action": "cancelled", "text": task.params.get("text", "")})
