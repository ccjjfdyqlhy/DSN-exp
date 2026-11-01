# apps/dsn_study/skills/builtin/study_tracking/tools/tracking_tools.py
# 学习跟踪工具 — 打卡 / 学习时段 / 学习日志 / 每日报告。
#
# 移植说明：参考实现（DSN-exp）把这组能力放在 skills/system/tools/tracking_tools.py
#（包装 tracking/tracking.py 的 TrackingTools），其 5 个工具面向"行为感知跟踪"
#（摄像头/麦克风/作息建模），dsn_study 无硬件链路。
# 本技能改为面向 dsn_study 已有的 tracking-lite + 纯软件打卡：把原本只能走 HTTP
# 的能力暴露给 AI，补齐"AI 可达性"缺口（参考实现有、dsn_study 曾缺失）。

from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger("skill.study_tracking")


class StudyTrackingTools:
    """打卡 + 学习时段 + 学习日志 + 每日报告的 AI 工具集。"""

    def __init__(self, studylog=None, checkin_store=None):
        self._studylog = studylog
        self._checkin = checkin_store

    # ── 打卡 ──

    def record_checkin(self, text: str = "", user_id: int = 0) -> dict:
        """今日打卡。text 为打卡备注（可空）。"""
        if self._checkin is None:
            return {"error": "打卡系统未初始化"}
        now = datetime.now()
        day = self._checkin.checkin_date_for(now)
        uid = int(user_id or 1)
        try:
            self._checkin.add_checkin(uid, day, now.strftime("%H:%M:%S"),
                                      text=text or "")
        except Exception as e:
            return {"error": f"打卡失败: {e}"}
        today = self._checkin.get_today_checkin(uid, day) or {}
        return {
            "success": True,
            "checkin_date": day,
            "checkin_time": today.get("checkin_time"),
            "streak": self._checkin.compute_checkin_streak(uid),
            "total_days": self._checkin.count_checkin_days(uid),
        }

    def query_checkin_stats(self, user_id: int = 0) -> dict:
        """打卡统计：累计天数 / 连续天数 / 今日状态 / 最近记录。"""
        if self._checkin is None:
            return {"error": "打卡系统未初始化"}
        uid = int(user_id or 1)
        try:
            today = self._checkin.get_today_checkin(uid,
                                                 self._checkin.checkin_date_for(datetime.now()))
            return {
                "success": True,
                "total_days": self._checkin.count_checkin_days(uid),
                "streak": self._checkin.compute_checkin_streak(uid),
                "checked_in_today": bool(today),
                "checkin_time": (today or {}).get("checkin_time"),
                "recent": self._checkin.query_checkins(uid, limit=10),
            }
        except Exception as e:
            return {"error": f"查询打卡统计失败: {e}"}

    # ── 学习时段 ──

    def record_session(self, subject: str = "未分类", minutes: float = 0,
                       note: str = "", user_id: int = 0) -> dict:
        """记录一段学习时间。"""
        if self._studylog is None:
            return {"error": "学习日志系统未初始化"}
        try:
            rec = self._studylog.record_session(int(user_id or 1), subject,
                                               float(minutes), note)
        except Exception as e:
            return {"error": f"记录学习时段失败: {e}"}
        return {"success": True, "record": rec}

    def record_note(self, text: str = "", subject: str = "未分类",
                    user_id: int = 0) -> dict:
        """记录一条学习笔记（自由文本）。"""
        if self._studylog is None:
            return {"error": "学习日志系统未初始化"}
        try:
            rec = self._studylog.record_note(int(user_id or 1), text, subject)
        except Exception as e:
            return {"error": f"记录学习笔记失败: {e}"}
        return {"success": True, "record": rec}

    def list_sessions(self, since: str = "", until: str = "", limit: int = 20,
                      user_id: int = 0) -> dict:
        """列出学习时段记录。"""
        if self._studylog is None:
            return {"error": "学习日志系统未初始化"}
        try:
            sessions = self._studylog.sessions(int(user_id or 1), since, until, limit)
        except Exception as e:
            return {"error": f"查询学习时段失败: {e}"}
        return {"success": True, "sessions": sessions}

    def minutes_by_day(self, days: int = 7, user_id: int = 0) -> dict:
        """最近 N 天每日学习分钟数。"""
        if self._studylog is None:
            return {"error": "学习日志系统未初始化"}
        try:
            data = self._studylog.minutes_by_day(int(user_id or 1), int(days))
        except Exception as e:
            return {"error": f"查询学习时长失败: {e}"}
        return {"success": True, "minutes_by_day": data}

    def daily_report(self, day: str = "", user_id: int = 0) -> dict:
        """每日报告：打卡 + 学习时段 + 计划完成度。"""
        if self._studylog is None:
            return {"error": "学习日志系统未初始化"}
        try:
            report = self._studylog.daily_report(int(user_id or 1), day or None)
        except Exception as e:
            return {"error": f"生成每日报告失败: {e}"}
        return {"success": True, "report": report}
