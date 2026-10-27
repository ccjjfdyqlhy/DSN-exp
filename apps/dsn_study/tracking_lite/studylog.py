# apps/dsn_study/tracking_lite/studylog.py
# StudyLog — 学习日志门面（dsn_study 功能补齐阶段 4）。
#
# 在 TrackingStore 分天事件之上提供学习场景语义：
#   record_session(uid, subject, minutes, note)  学习时段事件（etype=note,
#                                                source=studylog，meta 带分钟数）
#   daily_report(uid, day)                        每日报告：学习时段汇总 +
#                                                打卡状态 + 计划完成度
#
# 计划完成度经 plan_engine 注入（boot 已装配），打卡经 CheckinStore 注入；
# 两者缺省时对应段落自动留空，不阻塞报告生成。

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger("StudyLog")


class StudyLog:
    def __init__(self, store: TrackingStore, checkin_store=None, plan_engine=None):
        self._store = store
        self.checkin_store = checkin_store
        self.plan_engine = plan_engine

    # ── 事件写入 ──

    def record_session(self, user_id: int, subject: str, minutes: float,
                       note: str = "", day: Optional[str] = None) -> int:
        """记录一段学习时间。minutes 支持小数（0.1h 粒度足够）。"""
        meta = {"subject": subject, "minutes": round(float(minutes), 1)}
        payload = f"[学习时段] {subject} {round(float(minutes), 1)} 分钟"
        if note:
            payload += f"：{note}"
            meta["note"] = note
        _day = day.replace("-", "") if day else None
        return self._store.add_event(user_id=user_id, etype="note",
                                     payload=payload, source="studylog",
                                     meta=meta, _day=_day)

    def record_note(self, user_id: int, text: str,
                    source: str = "studylog") -> int:
        """记录一条自由文本学习日志。"""
        return self._store.add_event(user_id=user_id, etype="text",
                                     payload=text, source=source)

    # ── 查询 ──

    def sessions(self, user_id: int, since: str = "", until: str = "",
                 limit: int = 50) -> list[dict]:
        """学习时段事件列表（倒序）。"""
        events = self._store.search_events(user_id, etype="note",
                                           since=since, until=until,
                                           limit=limit)
        return [e for e in events if e.get("source") == "studylog"]

    def minutes_by_day(self, user_id: int, days: int = 30) -> dict[str, float]:
        """最近 N 天每日学习分钟数 {YYYY-MM-DD: minutes}。"""
        out: dict[str, float] = {}
        tables = self._store.day_tables()
        for table in tables:
            day_key = table.replace("tracking_events_", "")
            try:
                day_iso = datetime.strptime(day_key, "%Y%m%d").strftime("%Y-%m-%d")
            except ValueError:
                continue
            events = self._store.search_events(user_id, etype="note", since=day_iso,
                                               until=day_iso, limit=500)
            total = sum(float((e.get("meta") or {}).get("minutes", 0) or 0)
                        for e in events if e.get("source") == "studylog")
            if total:
                out[day_iso] = round(total, 1)
        return out

    # ── 每日报告 ──

    def _checkin_day_for(self, day: str) -> str:
        """把「自然日」映射为「打卡日」，读取侧必须与写入侧同口径。

        打卡日 D 覆盖 [D 04:00, D+1 04:00)：写入侧按 checkin_date_for(now) 归并，
        凌晨 0:00-03:59 的打卡记在前一天的打卡日。

        踩过的坑（曾导致"当日报告读不到当天打卡"）：
        把自然日 strptime 成午夜（hour=0）再喂给 checkin_date_for —— 午夜恒 <4，
        于是回退一整天。而写入侧用的是真实时刻（hour>=4 时为当天），两侧口径不一致，
        表现为 04:00~24:00 之间写入的打卡，在当日报告里 checked_in 恒为 False
        （凌晨 0:00-03:59 又恰好自洽，所以表现为"20/24 小时必挂"的时间相关用例）。

        口径：
        - 当天报告：取当前打开的打卡日，与 /api/checkin/status 保持一致；
        - 历史某天：取该自然日对应的打卡日（该日 04:00 之后写入的记录）。
        """
        now = datetime.now()
        if day == now.strftime("%Y-%m-%d"):
            return self.checkin_store.checkin_date_for(now)
        return day

    def daily_report(self, user_id: int, day: Optional[str] = None) -> dict:
        """聚合某天的学习报告（打卡 + 学习时段 + 计划完成度）。"""
        day = day or datetime.now().strftime("%Y-%m-%d")

        report: dict = {"date": day, "success": True}

        # 学习时段
        sessions = self.sessions(user_id, since=day, until=day, limit=200)
        total_minutes = round(sum(float((s.get("meta") or {}).get("minutes", 0) or 0)
                                  for s in sessions), 1)
        subjects: dict[str, float] = {}
        for s in sessions:
            subj = (s.get("meta") or {}).get("subject", "未分类")
            subjects[subj] = round(subjects.get(subj, 0) +
                                   float((s.get("meta") or {}).get("minutes", 0) or 0), 1)
        report["study"] = {
            "total_minutes": total_minutes,
            "sessions": len(sessions),
            "subjects": subjects,
        }

        # 打卡（4点边界：当天 00:00-03:59 属前一天）
        if self.checkin_store is not None:
            checkin_date = self._checkin_day_for(day)
            today = self.checkin_store.get_today_checkin(user_id, checkin_date)
            report["checkin"] = {
                "checked_in": today is not None,
                "checkin_time": (today or {}).get("checkin_time", ""),
                "streak": self.checkin_store.compute_checkin_streak(user_id),
                "total_days": self.checkin_store.count_checkin_days(user_id),
            }

        # 计划完成度
        if self.plan_engine is not None:
            try:
                summary = self.plan_engine.daily_summary(user_id, day)
                report["plan"] = summary
            except Exception:
                logger.warning("计划摘要获取失败（报告留空）", exc_info=True)
                report["plan"] = None

        return report
