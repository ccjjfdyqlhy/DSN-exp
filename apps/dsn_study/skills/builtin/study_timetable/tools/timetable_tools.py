# skills/builtin/study_timetable/tools/timetable_tools.py
# 学习时间表工具 — AI 通过原生 tool call 查看课程表、签到/签退、统计学习时长。

from __future__ import annotations

import logging
from datetime import date

logger = logging.getLogger("skill.study_timetable")


class StudyTimetableTool:
    """学习时间表。AI 通过 get_today/check_in/check_out/get_stats 等工具调用。"""

    def __init__(self):
        from apps.dsn_study.db.study_timetable import get_study_db, StudyTimetableStore
        db = get_study_db()
        if db:
            self._store = StudyTimetableStore(db)
            logger.info("StudyTimetableTool 已就绪")
        else:
            self._store = None
            logger.warning("StudyTimetableTool: study_db 未初始化")

    def _check(self):
        if self._store is None:
            raise RuntimeError("学习时间表不可用（study_db 未初始化）")

    def get_today(self, user_id: int = 0) -> dict:
        """查看今日时间表与当前进行中的自习。"""
        self._check()
        uid = user_id or 1
        slots = self._store.get_today_slots(uid)
        active = self._store.get_active_session(uid)
        return {
            "success": True,
            "today": date.today().isoformat(),
            "slots": [{"slot_id": s.slot_id, "start": s.start_time, "end": s.end_time,
                       "subject": s.subject, "activity": s.activity_type,
                       "enabled": s.enabled} for s in slots],
            "active_session": ({"session_id": active.session_id, "subject": active.subject,
                                "start": active.actual_start}
                               if active else None),
        }

    def check_in(self, subject: str = "自习", user_id: int = 0,
                 slot_id: str = "") -> dict:
        """开始一段自习（签到）。"""
        self._check()
        uid = user_id or 1
        session = self._store.check_in(uid, slot_id=slot_id, subject=subject)
        logger.info("学习签到: %s (uid=%d)", subject, uid)
        return {"success": True, "session_id": session.session_id,
                "subject": session.subject, "start": session.actual_start}

    def check_out(self, user_id: int = 0, note: str = "") -> dict:
        """结束当前自习（签退），自动累计时长。"""
        self._check()
        uid = user_id or 1
        session = self._store.check_out(uid, note=note)
        if not session:
            return {"success": False, "error": "当前没有进行中的自习"}
        logger.info("学习签退: %d 分钟 (uid=%d)", session.duration_min, uid)
        return {"success": True, "duration_min": session.duration_min,
                "subject": session.subject}

    def get_stats(self, user_id: int = 0, subject: str = "") -> dict:
        """查询今日/本周/分科学习统计。"""
        self._check()
        uid = user_id or 1
        today = date.today().isoformat()
        daily = self._store.get_daily_stats(uid, today)
        weekly = self._store.get_weekly_stats(uid)
        by_subject = self._store.get_subject_stats(uid, subject) if subject \
            else self._store.get_subject_stats(uid)
        return {
            "success": True,
            "date": today,
            "daily": daily,
            "weekly": weekly,
            "subjects": by_subject,
        }

    def generate_sessions(self, user_id: int = 0) -> dict:
        """按今日启用的时段生成自习任务（幂等）。"""
        self._check()
        uid = user_id or 1
        sessions = self._store.generate_today_sessions(uid)
        return {"success": True, "count": len(sessions),
                "sessions": [{"session_id": s.session_id, "subject": s.subject,
                              "planned_start": s.planned_start,
                              "planned_end": s.planned_end} for s in sessions]}
