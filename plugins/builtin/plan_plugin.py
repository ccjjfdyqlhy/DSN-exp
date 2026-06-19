
# plugins/builtin/plan_plugin.py
# 计划系统插件 — 晨间计划注入 + 日终报告

from __future__ import annotations

import logging
from datetime import datetime, date

from plugins.base import Plugin, HookPoint, PluginContext
from plan_store import PlanStore
from plan_engine import PlanEngine

logger = logging.getLogger(__name__)


class PlanPlugin(Plugin):
    """
    计划系统插件。
    PRE_PROCESS (priority=42): 将今日计划注入 system_prompt
    POST_PROCESS (priority=72): 检测日终触发报告
    """

    name = "plan"
    description = "计划管理 — 今日计划注入 + 日终报告"
    hooks = [HookPoint.PRE_PROCESS, HookPoint.POST_PROCESS]
    priority = 42

    def __init__(self, db=None):
        self._db = db
        self._store: PlanStore | None = None
        self._engine: PlanEngine | None = None
        self._today = date.today().isoformat()

    def on_load(self) -> None:
        if self._db:
            self._store = PlanStore(self._db)
            self._engine = PlanEngine(self._store)
            logger.info("PlanPlugin 已加载 (store=%s, engine=%s)",
                        self._store is not None, self._engine is not None)

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if self._engine is None:
            return ctx
        if hook == HookPoint.PRE_PROCESS:
            return self._on_pre_process(ctx)
        if hook == HookPoint.POST_PROCESS:
            return self._on_post_process(ctx)
        return ctx

    def _on_pre_process(self, ctx: PluginContext) -> PluginContext:
        """在 system_prompt 末尾注入今日计划"""
        today = date.today().isoformat()
        tasks = self._store.get_tasks_by_date(ctx.user_id, today) if self._store else []
        if not tasks:
            # 无计划时自动生成
            tasks = self._engine.generate_daily_plan(ctx.user_id, today)
        if not tasks:
            return ctx

        lines = ["\n[今日计划]"]
        for t in tasks:
            status_icon = "☐" if t.status == "pending" else "☑" if t.status == "done" else "⏭"
            star = "★" * t.priority + "☆" * (5 - t.priority)
            lines.append(f"  {status_icon} {t.title}  ({t.duration_min}min) {star}")
        ctx.system_prompt += "\n" + "\n".join(lines)
        return ctx

    def _on_post_process(self, ctx: PluginContext) -> PluginContext:
        """22:00 后触发日终报告注入"""
        now = datetime.now()
        if now.hour < 22:
            return ctx

        # 今日已触发过则跳过（暂简单判断）
        today = date.today().isoformat()
        summary = self._engine.daily_summary(ctx.user_id, today) if self._engine else {}
        if not summary or summary["total"] == 0:
            return ctx

        lines = [
            f"\n[日终报告 — {today}]",
            f"  完成: {summary['done']}/{summary['total']}",
            f"  进度: {summary['progress']:.0%}",
        ]
        if summary["done"] > 0:
            lines.append(f"  完成的: {', '.join(t['title'] for t in summary['tasks'] if t['status'] == 'done')}")
        ctx.system_prompt += "\n" + "\n".join(lines)
        return ctx
