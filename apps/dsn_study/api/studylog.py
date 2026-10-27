# apps/dsn_study/api/studylog.py
# 学习日志 REST API（dsn_study 功能补齐阶段 4，tracking-lite 的对外入口）。
#
#   POST /api/studylog/session   记录一段学习时间 {subject, minutes, note?}
#   POST /api/studylog/note      记录一条自由文本日志 {text}
#   GET  /api/studylog/sessions  学习时段列表 ?since=&until=&limit=
#   GET  /api/studylog/report    每日报告 ?date=YYYY-MM-DD（打卡+时段+计划聚合）

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request, g

logger = logging.getLogger("StudyLogAPI")

studylog_bp = Blueprint("studylog_api", __name__)

_studylog = None
_auth_manager = None


def init_studylog_api(studylog, auth_manager):
    global _studylog, _auth_manager
    _studylog = studylog
    _auth_manager = auth_manager


@studylog_bp.before_request
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


@studylog_bp.route("/api/studylog/session", methods=["POST"])
def record_session():
    if _studylog is None:
        return jsonify({"error": "StudyLog unavailable"}), 503
    uid = _uid()
    data = request.get_json(silent=True) or {}
    subject = (data.get("subject") or "").strip() or "未分类"
    try:
        minutes = float(data.get("minutes", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "minutes 需为数字"}), 400
    if minutes <= 0 or minutes > 24 * 60:
        return jsonify({"error": "minutes 需在 (0, 1440] 内"}), 400
    note = (data.get("note") or "").strip()
    event_id = _studylog.record_session(uid, subject, minutes, note=note)
    return jsonify({"success": True, "event_id": event_id}), 201


@studylog_bp.route("/api/studylog/note", methods=["POST"])
def record_note():
    if _studylog is None:
        return jsonify({"error": "StudyLog unavailable"}), 503
    uid = _uid()
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "缺少 text"}), 400
    event_id = _studylog.record_note(uid, text)
    return jsonify({"success": True, "event_id": event_id}), 201


@studylog_bp.route("/api/studylog/sessions", methods=["GET"])
def list_sessions():
    if _studylog is None:
        return jsonify({"error": "StudyLog unavailable"}), 503
    uid = _uid()
    since = request.args.get("since", "")
    until = request.args.get("until", "")
    try:
        limit = max(1, min(200, int(request.args.get("limit", 50))))
    except Exception:
        limit = 50
    sessions = _studylog.sessions(uid, since=since, until=until, limit=limit)
    return jsonify({"success": True, "sessions": sessions, "count": len(sessions)})


@studylog_bp.route("/api/studylog/report", methods=["GET"])
def daily_report():
    if _studylog is None:
        return jsonify({"error": "StudyLog unavailable"}), 503
    uid = _uid()
    day = request.args.get("date") or None
    try:
        report = _studylog.daily_report(uid, day)
    except Exception:
        logger.exception("生成每日报告失败 uid=%d", uid)
        return jsonify({"error": "Internal error"}), 500
    return jsonify(report)
