# plugins/builtin/plan_plugin.py
# 计划系统插件 — 晨间计划注入 + <plan_check> 解析 + 日终报告

from __future__ import annotations

import logging
import re
from datetime import datetime, date

from plugins.base import Plugin, HookPoint, PluginContext
from plan_store import PlanStore
from plan_engine import PlanEngine

logger = logging.getLogger(__name__)

_PLAN_CHECK_RE = re.compile(r"<plan_check>\s*(.*?)\s*</plan_check>", re.DOTALL | re.IGNORECASE)


class PlanPlugin(Plugin):
    """
    计划系统插件。
    PRE_PROCESS (priority=42): 将今日计划注入 system_prompt
    POST_PROCESS (priority=72): <plan_check> 标签解析 + 日终报告
    """

    name = "plan"
    description = "计划管理 — 今日计划注入 + check_off + 日终报告"
    hooks = [HookPoint.PRE_PROCESS, HookPoint.POST_PROCESS]
    priority = 42

    def __init__(self, db=None):
        self._db = db
        self._store: PlanStore | None = None
        self._engine: PlanEngine | None = None
        self._report_generated_today: str = ""

    def on_load(self) -> None:
        if self._db:
            self._store = PlanStore(self._db)
            self._engine = PlanEngine(self._store)
            logger.info("PlanPlugin 已加载")

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if self._engine is None:
            return ctx
        if hook == HookPoint.PRE_PROCESS:
            return self._on_pre_process(ctx)
        if hook == HookPoint.POST_PROCESS:
            return self._on_post_process(ctx)
        return ctx

    def _on_pre_process(self, ctx: PluginContext) -> PluginContext:
        today = date.today().isoformat()
        tasks = self._store.get_tasks_by_date(ctx.user_id, today) if self._store else []
        if not tasks:
            tasks = self._engine.generate_daily_plan(ctx.user_id, today)
        if not tasks:
            return ctx

        lines = ["\n[今日计划]"]
        for t in tasks:
            status_icon = "☐" if t.status == "pending" else "☑" if t.status == "done" else "⏭"
            star = "★" * t.priority + "☆" * (5 - t.priority)
            lines.append(f"  {status_icon} {t.title}  ({t.duration_min}min) {star}  [id={t.task_id}]")
        ctx.system_prompt += "\n" + "\n".join(lines)
        return ctx

    def _on_post_process(self, ctx: PluginContext) -> PluginContext:
        self._handle_plan_check(ctx)
        self._handle_daily_report(ctx)
        return ctx

    def _handle_plan_check(self, ctx: PluginContext) -> None:
        reply = ctx.original_reply or ctx.reply or ""
        results: list[dict] = []
        for match in _PLAN_CHECK_RE.finditer(reply):
            try:
                import json
                data = json.loads(match.group(1).strip())
                task_id = data.get("task_id", "")
                action = data.get("action", "done")
                if task_id:
                    if action == "skip":
                        self._engine.skip_task(task_id)
                    else:
                        self._engine.check_off(task_id)
                    results.append({
                        "tag": "<plan_check>", "success": True,
                        "summary": f"任务 {task_id[:8]} → {action}",
                    })
                    logger.info("plan_check: %s → %s", task_id[:8], action)
                else:
                    results.append({
                        "tag": "<plan_check>", "success": False,
                        "summary": "缺少 task_id",
                    })
            except (json.JSONDecodeError, Exception) as e:
                logger.error("plan_check 解析失败: %s", e)
                results.append({
                    "tag": "<plan_check>", "success": False,
                    "summary": f"解析失败: {e}",
                    "error": str(e),
                })

        ctx.reply = _PLAN_CHECK_RE.sub("", ctx.reply).strip()

        if results:
            ctx.extra.setdefault("_tag_results", []).extend(results)

    def _handle_daily_report(self, ctx: PluginContext) -> None:
        now = datetime.now()
        if now.hour < 22:
            return

        today = date.today().isoformat()
        if self._report_generated_today == today:
            return

        summary = self._engine.daily_summary(ctx.user_id, today) if self._engine else {}
        if not summary or summary["total"] == 0:
            return

        self._report_generated_today = today

        lines = [
            f"\n[日终报告 — {today}]",
            f"  完成: {summary['done']}/{summary['total']}",
            f"  跳过: {summary['skipped']}",
            f"  进度: {summary['progress']:.0%}",
        ]
        if summary["done"] > 0:
            done_titles = [t["title"] for t in summary["tasks"] if t["status"] == "done"]
            lines.append(f"  完成项: {', '.join(done_titles)}")
        ctx.system_prompt += "\n" + "\n".join(lines)
