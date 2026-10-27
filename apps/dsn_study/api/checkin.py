# apps/dsn_study/api/checkin.py
# 打卡系统 REST API — 自 apps/dsn/api/checkin.py 移植（dsn_study 功能补齐阶段 4）。
#
# study 版为纯软件打卡：JSON {text?} 提交，无视频/音频媒体、无 ASR、无
# tracking 写入（dsn 原版经主摄像头录像 + 麦克风录音 + ASR 存档）。
# 语义保持：打卡日按"凌晨4点边界"归并；每天多次打卡，最早一次为有效打卡。
# 新增 /api/checkin/calendar（打卡日历视图数据）。

from __future__ import annotations

import logging
from datetime import datetime

from flask import Blueprint, jsonify, request, g

logger = logging.getLogger("Checkin")

checkin_bp = Blueprint("checkin_api", __name__)

_store = None
_auth_manager = None


def init_checkin_api(store=None, auth_manager=None):
    """注入依赖（boot.py 启动时调用）。store: CheckinStore。"""
    global _store, _auth_manager
    _store = store
    _auth_manager = auth_manager
    logger.info("Checkin API 已初始化")


@checkin_bp.before_request
def _require_auth():
    if not _auth_manager:
        return jsonify({"error": "Auth unavailable"}), 503
    user = _auth_manager.authenticate(request)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    g.user = user


def _uid() -> int:
    if g.user is None:
        return 0
    if isinstance(g.user, dict):
        return int(g.user.get("uid", 0) or 0)
    return int(getattr(g.user, "uid", 0) or 0)


@checkin_bp.route("/api/checkin/record", methods=["POST"])
def checkin_record():
    """接收一次打卡（纯文本）。请求: JSON {text?: string}。"""
    if _store is None:
        return jsonify({"error": "Database unavailable"}), 503
    uid = _uid()
    if not uid:
        return jsonify({"error": "无法识别用户"}), 401

    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()

    now = datetime.now()
    checkin_date = _store.checkin_date_for(now)
    checkin_time = now.strftime("%H:%M:%S")

    try:
        event_id = _store.add_checkin(
            user_id=uid,
            checkin_date=checkin_date,
            checkin_time=checkin_time,
            text=text,
        )
    except Exception as e:
        logger.error("写入打卡记录失败: %s", e)
        return jsonify({"error": "Database error"}), 500

    today = _store.get_today_checkin(uid, checkin_date)
    return jsonify({
        "success": True,
        "checkin_id": event_id,
        "checkin_date": checkin_date,
        "checkin_time": checkin_time,
        "text": text,
        "today_checkin_time": (today or {}).get("checkin_time", checkin_time),
        "streak": _store.compute_checkin_streak(uid),
    })


@checkin_bp.route("/api/checkin/status", methods=["GET"])
def checkin_status():
    """查询今日（4点边界）打卡状态：是否已打卡、今日最早打卡时间、累计/连续天数。"""
    if _store is None:
        return jsonify({"error": "Database unavailable"}), 503
    uid = _uid()
    now = datetime.now()
    checkin_date = _store.checkin_date_for(now)
    today = _store.get_today_checkin(uid, checkin_date)
    return jsonify({
        "success": True,
        "checked_in": today is not None,
        "checkin_date": checkin_date,
        "checkin_time": (today or {}).get("checkin_time", ""),
        "today_count": 0 if today is None else 1,
        "total_days": _store.count_checkin_days(uid),
        "streak": _store.compute_checkin_streak(uid),
    })


@checkin_bp.route("/api/checkin/history", methods=["GET"])
def checkin_history():
    """查询打卡历史（按时间倒序）。"""
    if _store is None:
        return jsonify({"error": "Database unavailable"}), 503
    uid = _uid()
    try:
        limit = max(1, min(100, int(request.args.get("limit", 30))))
    except Exception:
        limit = 30
    records = _store.query_checkins(uid, limit=limit)
    return jsonify({"success": True, "records": records, "count": len(records)})


@checkin_bp.route("/api/checkin/calendar", methods=["GET"])
def checkin_calendar():
    """打卡日历数据：GET ?month=YYYY-MM（缺省当月）。返回当月每日打卡状态与连续天数。"""
    if _store is None:
        return jsonify({"error": "Database unavailable"}), 503
    uid = _uid()
    now = datetime.now()
    month = request.args.get("month") or now.strftime("%Y-%m")
    try:
        year, mon = (int(x) for x in month.split("-"))
    except Exception:
        return jsonify({"error": "month 格式需为 YYYY-MM"}), 400
    days = _store.month_calendar(uid, year, mon)
    return jsonify({
        "success": True,
        "month": month,
        "days": days,
        "checked_count": sum(1 for v in days.values() if v),
        "streak": _store.compute_checkin_streak(uid),
        "total_days": _store.count_checkin_days(uid),
    })
