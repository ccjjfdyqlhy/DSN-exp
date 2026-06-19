
# plan_engine.py
# 计划引擎 — Goal 拆解、日计划生成、任务追踪

import uuid
import logging
from datetime import datetime, date, timedelta
from typing import Optional

from plan_store import PlanStore, Goal, Phase, DailyTask

logger = logging.getLogger(__name__)


class PlanEngine:
    """计划引擎核心业务逻辑"""

    def __init__(self, store: PlanStore):
        self._store = store

    # ── Goal 创建 ──

    def create_goal(self, user_id: int, title: str, description: str = "",
                    deadline: str = "") -> Goal:
        goal = Goal(
            goal_id=str(uuid.uuid4()),
            user_id=user_id,
            title=title,
            description=description,
            deadline=deadline,
        )
        self._store.create_goal(goal)
        logger.info("创建目标: %s (%s)", goal.goal_id[:8], title)
        return goal

    # ── Phase 创建 ──

    def add_phase(self, goal_id: str, title: str, description: str = "",
                  start_date: str = "", end_date: str = "") -> Phase:
        phase = Phase(
            phase_id=str(uuid.uuid4()),
            goal_id=goal_id,
            title=title,
            description=description,
            start_date=start_date,
            end_date=end_date,
        )
        self._store.create_phase(phase)
        return phase

    # ── 日计划生成 ──

    def generate_daily_plan(self, user_id: int, date_str: str = "") -> list[DailyTask]:
        """生成指定日期的待办计划（基于当前 active 的 Goal 和 Phase 进度）"""
        if not date_str:
            date_str = date.today().isoformat()

        # 检查是否已有当日计划
        existing = self._store.get_tasks_by_date(user_id, date_str)
        if existing:
            return existing

        # 从 active goal 中推算今日任务
        goals = self._store.list_goals(user_id)
        tasks: list[DailyTask] = []
        for goal in goals:
            if goal.status != "active":
                continue
            for phase in goal.phases:
                if phase.status not in ("pending", "active"):
                    continue
                if phase.start_date and phase.end_date:
                    if not (phase.start_date <= date_str <= phase.end_date):
                        continue
                # 生成一条今日任务摘要
                task = DailyTask(
                    task_id=str(uuid.uuid4()),
                    user_id=user_id,
                    date=date_str,
                    title=f"{goal.title} — {phase.title}",
                    subject=goal.title,
                    duration_min=30,
                    priority=3,
                )
                tasks.append(task)

        if not tasks:
            # 没有任何活跃 phase 时，基于 Goal 生成顶层任务
            for goal in goals:
                if goal.status == "active":
                    task = DailyTask(
                        task_id=str(uuid.uuid4()),
                        user_id=user_id,
                        date=date_str,
                        title=goal.title,
                        subject=goal.title,
                        duration_min=30,
                        priority=3,
                    )
                    tasks.append(task)

        for t in tasks:
            self._store.save_task(t)
        return tasks

    # ── 任务追踪 ──

    def check_off(self, task_id: str, note: str = ""):
        self._store.update_task_status(task_id, "done", note)

    def skip_task(self, task_id: str):
        self._store.update_task_status(task_id, "skipped")

    # ── 进度统计 ──

    def daily_summary(self, user_id: int, date_str: str = "") -> dict:
        if not date_str:
            date_str = date.today().isoformat()
        tasks = self._store.get_tasks_by_date(user_id, date_str)
        total = len(tasks)
        done = sum(1 for t in tasks if t.status == "done")
        skipped = sum(1 for t in tasks if t.status == "skipped")
        pending = total - done - skipped
        return {
            "date": date_str,
            "total": total,
            "done": done,
            "skipped": skipped,
            "pending": pending,
            "progress": round(done / total, 2) if total > 0 else 0,
            "tasks": [{"title": t.title, "status": t.status, "duration": t.duration_min} for t in tasks],
        }
