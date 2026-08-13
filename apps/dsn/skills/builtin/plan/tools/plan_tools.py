# skills/builtin/plan/tools/plan_tools.py
# 计划系统工具 — AI 通过 <tool>{"skill":"plan","tool":"xxx",...}</tool> 操作 Goal/Phase/DailyTask

from __future__ import annotations

import logging
from datetime import date

logger = logging.getLogger("skill.plan")


class PlanTools:
    """计划系统。AI 通过 <tool>{"skill":"plan","tool":"xxx",...}</tool> 调用。"""

    def __init__(self):
        from apps.dsn.db.plan_store import get_plan_db, PlanStore
        from apps.dsn.db.plan_engine import PlanEngine
        db = get_plan_db()
        if db:
            store = PlanStore(db)
            self._engine = PlanEngine(store)
            logger.info("PlanTools 已就绪")
        else:
            self._engine = None
            logger.warning("PlanTools: plan_db 未初始化")

    def _check(self):
        if self._engine is None:
            raise RuntimeError("计划系统不可用（plan_db 未初始化）")

    def create_goal(self, title: str, description: str = "",
                    deadline: str = "", user_id: int = 0) -> dict:
        self._check()
        uid = user_id or 1
        goal = self._engine.create_goal(uid, title, description, deadline)
        logger.info("创建目标: %s (uid=%d)", title, uid)
        return {"success": True, "goal_id": goal.goal_id, "title": goal.title}

    def add_phase(self, goal_id: str, title: str, description: str = "",
                  start_date: str = "", end_date: str = "") -> dict:
        self._check()
        phase = self._engine.add_phase(goal_id, title, description, start_date, end_date)
        logger.info("创建阶段: %s → goal=%s", title, goal_id[:8])
        return {"success": True, "phase_id": phase.phase_id, "title": phase.title}

    def list_goals(self, user_id: int = 0) -> dict:
        self._check()
        uid = user_id or 1
        goals = self._engine._store.list_goals(uid)
        return {
            "success": True,
            "goals": [{
                "goal_id": g.goal_id,
                "title": g.title,
                "status": g.status,
                "deadline": g.deadline,
                "progress": g.progress,
                "phases": [{"phase_id": p.phase_id, "title": p.title,
                             "start_date": p.start_date, "end_date": p.end_date,
                             "status": p.status}
                            for p in g.phases],
            } for g in goals],
        }

    def generate_daily_plan(self, user_id: int = 0, date_str: str = "") -> dict:
        self._check()
        uid = user_id or 1
        today = date_str or date.today().isoformat()
        tasks = self._engine.generate_daily_plan(uid, today)
        logger.info("生成日计划: %d 任务 (date=%s)", len(tasks), today)
        return {
            "success": True,
            "date": today,
            "tasks": [{
                "task_id": t.task_id, "title": t.title,
                "duration_min": t.duration_min, "priority": t.priority,
                "status": t.status,
            } for t in tasks],
            "count": len(tasks),
        }

    def check_off(self, task_id: str, note: str = "") -> dict:
        self._check()
        self._engine.check_off(task_id, note)
        logger.info("任务完成: %s", task_id[:8])
        return {"success": True, "task_id": task_id, "status": "done"}

    def skip_task(self, task_id: str) -> dict:
        self._check()
        self._engine.skip_task(task_id)
        logger.info("任务跳过: %s", task_id[:8])
        return {"success": True, "task_id": task_id, "status": "skipped"}

    def daily_summary(self, user_id: int = 0, date_str: str = "") -> dict:
        self._check()
        uid = user_id or 1
        today = date_str or date.today().isoformat()
        summary = self._engine.daily_summary(uid, today)
        return {"success": True, **summary}
