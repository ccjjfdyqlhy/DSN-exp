# api/study_timetable.py
# 学习时间表 REST API — Flask Blueprint
#
# 周时间表管理 + 学习签到/签退 + 学习统计

from flask import Blueprint, request, jsonify, g

from db.study_timetable import (
    StudyTimetableStore, TimetableSlot, StudySession,
    DAY_NAMES, get_study_db,
)
from datetime import date

study_bp = Blueprint("study_timetable_api", __name__)

_db = None
_auth_manager = None


def init_study_timetable_api(db, auth_manager):
    global _db, _auth_manager
    _db = db
    _auth_manager = auth_manager


@study_bp.before_request
def _require_auth():
    if _auth_manager:
        g.user = _auth_manager.authenticate(request)
    else:
        g.user = {"uid": 0}


def _uid() -> int:
    return g.user.get("uid", 0) if g.user else 0


def _store() -> StudyTimetableStore:
    return StudyTimetableStore(_db) if _db else None


# ══════════════════════════════════════════
# 周时间表管理
# ══════════════════════════════════════════

@study_bp.route("/api/study/timetable/slots", methods=["GET"])
def list_slots():
    """获取时间槽列表。可选 ?day=0..6 过滤星期"""
    uid = _uid()
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401
    store = _store()
    if not store:
        return jsonify({"error": "Study system unavailable"}), 503
    try:
        day = int(request.args.get("day", -1))
    except (ValueError, TypeError):
        day = -1
    slots = store.list_slots(uid, day if day >= 0 else None)
    return jsonify({
        "slots": [{
            "slot_id": s.slot_id,
            "day_of_week": s.day_of_week,
            "day_name": DAY_NAMES[s.day_of_week],
            "start_time": s.start_time,
            "end_time": s.end_time,
            "subject": s.subject,
            "activity_type": s.activity_type,
            "goal_id": s.goal_id,
            "kp_code": s.kp_code,
            "enabled": s.enabled,
        } for s in slots],
    })


@study_bp.route("/api/study/timetable/slots", methods=["POST"])
def create_slot():
    """创建时间槽"""
    uid = _uid()
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401
    store = _store()
    if not store:
        return jsonify({"error": "Study system unavailable"}), 503
    data = request.get_json(silent=True) or {}
    day = data.get("day_of_week")
    if day is None or not isinstance(day, int) or day < 0 or day > 6:
        return jsonify({"error": "Invalid day_of_week (0-6)"}), 400
    start = data.get("start_time", "")
    end = data.get("end_time", "")
    if not start or not end:
        return jsonify({"error": "Missing start_time or end_time"}), 400
    slot = TimetableSlot(
        user_id=uid,
        day_of_week=day,
        start_time=start,
        end_time=end,
        subject=data.get("subject", ""),
        activity_type=data.get("activity_type", "study"),
        goal_id=data.get("goal_id", ""),
        kp_code=data.get("kp_code", ""),
        enabled=data.get("enabled", True),
    )
    slot_id = store.create_slot(slot)
    return jsonify({"slot_id": slot_id, "success": True}), 201


@study_bp.route("/api/study/timetable/slots/<slot_id>", methods=["PUT"])
def update_slot(slot_id):
    uid = _uid()
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401
    store = _store()
    if not store:
        return jsonify({"error": "Study system unavailable"}), 503
    slot = store.get_slot(slot_id)
    if not slot or slot.user_id != uid:
        return jsonify({"error": "Not found"}), 404
    data = request.get_json(silent=True) or {}
    if "day_of_week" in data:
        slot.day_of_week = int(data["day_of_week"])
    if "start_time" in data:
        slot.start_time = data["start_time"]
    if "end_time" in data:
        slot.end_time = data["end_time"]
    if "subject" in data:
        slot.subject = data["subject"]
    if "activity_type" in data:
        slot.activity_type = data["activity_type"]
    if "enabled" in data:
        slot.enabled = bool(data["enabled"])
    store.update_slot(slot)
    return jsonify({"success": True})


@study_bp.route("/api/study/timetable/slots/<slot_id>", methods=["DELETE"])
def delete_slot(slot_id):
    uid = _uid()
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401
    store = _store()
    if not store:
        return jsonify({"error": "Study system unavailable"}), 503
    slot = store.get_slot(slot_id)
    if not slot or slot.user_id != uid:
        return jsonify({"error": "Not found"}), 404
    store.delete_slot(slot_id)
    return jsonify({"success": True})


@study_bp.route("/api/study/timetable/slots/<slot_id>/toggle", methods=["POST"])
def toggle_slot(slot_id):
    uid = _uid()
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401
    store = _store()
    if not store:
        return jsonify({"error": "Study system unavailable"}), 503
    slot = store.get_slot(slot_id)
    if not slot or slot.user_id != uid:
        return jsonify({"error": "Not found"}), 404
    data = request.get_json(silent=True) or {}
    enabled = data.get("enabled", not slot.enabled)
    store.toggle_slot(slot_id, enabled)
    return jsonify({"success": True, "enabled": enabled})


# ══════════════════════════════════════════
# 周时间表概览
# ══════════════════════════════════════════

@study_bp.route("/api/study/timetable/weekly", methods=["GET"])
def weekly_timetable():
    """一周时间表概览"""
    uid = _uid()
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401
    store = _store()
    if not store:
        return jsonify({"error": "Study system unavailable"}), 503
    all_slots = store.list_slots(uid)
    week = {i: [] for i in range(7)}
    for s in all_slots:
        if s.enabled:
            week[s.day_of_week].append({
                "slot_id": s.slot_id,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "subject": s.subject,
                "activity_type": s.activity_type,
            })
    return jsonify({
        "week": [
            {"day": i, "name": DAY_NAMES[i], "slots": week[i]}
            for i in range(7)
        ],
    })


# ══════════════════════════════════════════
# 学习签到/签退
# ══════════════════════════════════════════

@study_bp.route("/api/study/today", methods=["GET"])
def today_plan():
    """获取今日学习计划（从时间表生成）"""
    uid = _uid()
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401
    store = _store()
    if not store:
        return jsonify({"error": "Study system unavailable"}), 503
    today = date.today().isoformat()
    dow = date.today().weekday()
    sessions = store.generate_today_sessions(uid)
    active = store.get_active_session(uid)
    return jsonify({
        "date": today,
        "day_of_week": dow,
        "day_name": DAY_NAMES[dow],
        "sessions": [{
            "session_id": s.session_id,
            "slot_id": s.slot_id,
            "subject": s.subject,
            "activity_type": s.activity_type,
            "planned_start": s.planned_start,
            "planned_end": s.planned_end,
            "actual_start": s.actual_start,
            "actual_end": s.actual_end,
            "duration_min": s.duration_min,
            "status": s.status,
        } for s in sessions],
        "active_session": {
            "session_id": active.session_id,
            "subject": active.subject,
            "actual_start": active.actual_start,
            "duration_min": active.duration_min,
        } if active else None,
    })


@study_bp.route("/api/study/checkin", methods=["POST"])
def check_in():
    """开始学习"""
    uid = _uid()
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401
    store = _store()
    if not store:
        return jsonify({"error": "Study system unavailable"}), 503
    data = request.get_json(silent=True) or {}
    session = store.check_in(
        uid,
        slot_id=data.get("slot_id", ""),
        subject=data.get("subject", ""),
        activity_type=data.get("activity_type", "study"),
    )
    if not session:
        return jsonify({"error": "Check-in failed"}), 500
    return jsonify({
        "success": True,
        "session_id": session.session_id,
        "subject": session.subject,
        "actual_start": session.actual_start,
        "status": "active",
    })


@study_bp.route("/api/study/checkout", methods=["POST"])
def check_out():
    """结束学习"""
    uid = _uid()
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401
    store = _store()
    if not store:
        return jsonify({"error": "Study system unavailable"}), 503
    data = request.get_json(silent=True) or {}
    session = store.check_out(
        uid,
        session_id=data.get("session_id", ""),
        note=data.get("note", ""),
    )
    if not session:
        return jsonify({"error": "No active session to checkout"}), 404
    return jsonify({
        "success": True,
        "session_id": session.session_id,
        "subject": session.subject,
        "duration_min": session.duration_min,
        "status": "done",
    })


# ══════════════════════════════════════════
# 学习记录
# ══════════════════════════════════════════

@study_bp.route("/api/study/sessions", methods=["GET"])
def list_sessions():
    """查询学习记录。?date=YYYY-MM-DD"""
    uid = _uid()
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401
    store = _store()
    if not store:
        return jsonify({"error": "Study system unavailable"}), 503
    date_str = request.args.get("date", date.today().isoformat())
    sessions = store.get_sessions_by_date(uid, date_str)
    return jsonify({
        "date": date_str,
        "sessions": [{
            "session_id": s.session_id, "slot_id": s.slot_id,
            "subject": s.subject, "activity_type": s.activity_type,
            "planned_start": s.planned_start, "planned_end": s.planned_end,
            "actual_start": s.actual_start, "actual_end": s.actual_end,
            "duration_min": s.duration_min, "status": s.status, "note": s.note,
        } for s in sessions],
    })


# ══════════════════════════════════════════
# 学习统计
# ══════════════════════════════════════════

@study_bp.route("/api/study/stats/daily", methods=["GET"])
def daily_stats():
    """日统计。?date=YYYY-MM-DD"""
    uid = _uid()
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401
    store = _store()
    if not store:
        return jsonify({"error": "Study system unavailable"}), 503
    date_str = request.args.get("date", date.today().isoformat())
    stats = store.get_daily_stats(uid, date_str)
    return jsonify({"date": date_str, "stats": stats})


@study_bp.route("/api/study/stats/weekly", methods=["GET"])
def weekly_stats():
    """周统计。?start=YYYY-MM-DD (默认本周一)"""
    uid = _uid()
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401
    store = _store()
    if not store:
        return jsonify({"error": "Study system unavailable"}), 503
    start = request.args.get("start", "")
    stats = store.get_weekly_stats(uid, start)
    # 聚合
    total_planned = sum(s["planned_min"] or 0 for s in stats)
    total_actual = sum(s["actual_min"] or 0 for s in stats)
    total_done = sum(s["completed_slots"] or 0 for s in stats)
    total_slots = sum(s["total_slots"] or 0 for s in stats)
    return jsonify({
        "daily": stats,
        "summary": {
            "total_planned_min": total_planned,
            "total_actual_min": total_actual,
            "completed_slots": total_done,
            "total_slots": total_slots,
            "completion_rate": round(total_done / total_slots * 100, 1) if total_slots > 0 else 0,
            "adherence_rate": round(total_actual / total_planned * 100, 1) if total_planned > 0 else 0,
        },
    })


@study_bp.route("/api/study/stats/subjects", methods=["GET"])
def subject_stats():
    """各科目累计统计"""
    uid = _uid()
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401
    store = _store()
    if not store:
        return jsonify({"error": "Study system unavailable"}), 503
    subject = request.args.get("subject", "")
    stats = store.get_subject_stats(uid, subject)
    return jsonify(stats)
