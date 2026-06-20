# plugins/builtin/task_plugin.py
# 任务解析与执行插件 — POST_PROCESS

from __future__ import annotations

import json
import re
import logging
from datetime import datetime
from typing import Optional

from plugins.base import Plugin, HookPoint, PluginContext
from tasks import TaskType

logger = logging.getLogger("TaskPlugin")


class TaskPlugin(Plugin):
    """
    解析 AI 回复中的 <task> 标签，创建并执行后台任务。

    POST_PROCESS (priority=40):
    - 解析 <task> 标签 + ```action 代码块
    - 创建后台任务（提醒 / 推理 / 动作）
    - 将 task_id 写入 ctx.extra["_pending_tasks"]，供 Pipeline 轮询

    依赖: task_manager (TaskManager), db, skill_registry
    """

    name = "task"
    description = "任务解析 — <task> 标签调度执行"
    hooks = [HookPoint.POST_PROCESS]
    priority = 40

    _ACTION_RE = re.compile(r"```action\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
    _TASK_RE = re.compile(r"<task>(.*?)</task>", re.DOTALL | re.IGNORECASE)

    def __init__(self, task_manager=None, db=None, skill_registry=None):
        self._task_mgr = task_manager
        self._db = db
        self._skill_registry = skill_registry

    def on_load(self) -> None:
        if self._task_mgr is None:
            logger.warning("task_manager 未注入，TaskPlugin 将跳过任务处理")

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if self._task_mgr is None:
            return ctx

        # agent 循环修改了 reply 时使用 ctx.reply（含 agent 最终输出中的 <task> 和代码块），
        # 否则使用 ctx.original_reply（原始 LLM 输出，<task> 和代码块未被 _clean_reply 清除）
        text = ctx.reply if ctx.extra.get("_agent_reply_dirty") else ctx.original_reply
        tasks = self._parse_tasks(text)
        if not tasks:
            return ctx

        pending = ctx.extra.setdefault("_pending_tasks", set())
        for task_data in tasks:
            tid = self._handle_task(task_data, ctx)
            if tid:
                pending.add(tid)

        # 从 ctx.reply 中移除已处理的 <task> 和 ```action``` 标签
        ctx.reply = self._ACTION_RE.sub("", ctx.reply).strip()
        ctx.reply = self._TASK_RE.sub("", ctx.reply).strip()
        if not ctx.reply:
            ctx.reply = "…"

        return ctx

    # ---- 解析 ----

    @classmethod
    def _parse_tasks(cls, text: str) -> list[dict]:
        tasks: list[dict] = []
        action_matches = list(cls._ACTION_RE.finditer(text))
        task_matches = list(cls._TASK_RE.finditer(text))
        if not task_matches:
            return tasks

        action_matches.sort(key=lambda m: m.start())
        task_matches.sort(key=lambda m: m.start())
        used_actions: list[bool] = [False] * len(action_matches)

        for tm in task_matches:
            try:
                task_data = json.loads(tm.group(1).strip())
            except json.JSONDecodeError:
                logger.error("JSON 解析失败: %s", tm.group(1)[:100])
                continue

            if task_data.get("type") != "action":
                tasks.append(task_data)
                continue

            nearest_idx = -1
            nearest_dist = float("inf")
            for i, am in enumerate(action_matches):
                if used_actions[i]:
                    continue
                dist = abs(am.start() - tm.start())
                if dist < nearest_dist:
                    nearest_dist = dist
                    nearest_idx = i

            if nearest_idx >= 0:
                used_actions[nearest_idx] = True
                task_data.setdefault("params", {})
                task_data["params"]["content"] = action_matches[nearest_idx].group(1).strip()
                tasks.append(task_data)

        return tasks

    # ---- 任务创建 ----

    def _handle_task(self, task_data: dict, ctx: PluginContext) -> str | None:
        task_type = task_data.get("type")
        params = task_data.get("params", {})
        try:
            if task_type == "reminder":
                return self._create_reminder(params, ctx)
            elif task_type == "habit":
                return self._create_habit(params, ctx)
            elif task_type == "countdown":
                return self._create_countdown(params, ctx)
            elif task_type == "daily_plan":
                return self._create_daily_plan(params, ctx)
            elif task_type == "periodic":
                return self._create_periodic(params, ctx)
            elif task_type == "reasoner":
                return self._create_reasoner(params, ctx)
            elif task_type == "action":
                return self._create_action(params, ctx)
        except Exception:
            logger.exception("处理任务失败: %s", task_data)
        return None

    def _create_reminder(self, params: dict, ctx: PluginContext) -> str | None:
        time_str = params.get("time")
        if not time_str:
            return None
        scheduled_time = datetime.fromisoformat(time_str)
        task_id = self._task_mgr.create_task(
            task_type=TaskType.REMINDER,
            user_id=ctx.user_id,
            chat_id=ctx.chat_id,
            params=params,
            priority=1,
            scheduled_time=scheduled_time,
        )
        logger.info("已创建提醒任务: %s, 时间: %s", task_id, scheduled_time)
        return task_id

    def _create_habit(self, params: dict, ctx: PluginContext) -> str | None:
        time_str = params.get("time")
        interval_str = params.get("interval", "")
        if not time_str:
            return None
        scheduled_time = datetime.fromisoformat(time_str)
        interval_seconds = self._parse_interval(interval_str)
        task_id = self._task_mgr.create_task(
            task_type=TaskType.HABIT,
            user_id=ctx.user_id,
            chat_id=ctx.chat_id,
            params=params,
            priority=1,
            scheduled_time=scheduled_time,
            interval_seconds=interval_seconds,
        )
        logger.info("已创建习惯任务: %s, 间隔=%ds, 起始=%s", task_id, interval_seconds, scheduled_time)
        return task_id

    def _create_countdown(self, params: dict, ctx: PluginContext) -> str | None:
        target_str = params.get("target")
        if not target_str:
            return None
        scheduled_time = datetime.fromisoformat(target_str)
        task_id = self._task_mgr.create_task(
            task_type=TaskType.COUNTDOWN,
            user_id=ctx.user_id,
            chat_id=ctx.chat_id,
            params=params,
            priority=1,
            scheduled_time=scheduled_time,
        )
        logger.info("已创建倒计时: %s, 目标: %s", task_id, scheduled_time)
        return task_id

    def _create_daily_plan(self, params: dict, ctx: PluginContext) -> str | None:
        trigger_time = params.get("trigger_time", "07:30")
        try:
            hour, minute = map(int, trigger_time.split(":"))
        except ValueError:
            return None
        now = datetime.now()
        scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if scheduled <= now:
            from datetime import timedelta
            scheduled += timedelta(days=1)
        task_id = self._task_mgr.create_task(
            task_type=TaskType.DAILY_PLAN,
            user_id=ctx.user_id,
            chat_id=ctx.chat_id,
            params=params,
            priority=1,
            scheduled_time=scheduled,
        )
        logger.info("已创建每日计划提醒: %s, 时间=%s", task_id, trigger_time)
        return task_id

    def _create_periodic(self, params: dict, ctx: PluginContext) -> str | None:
        cron_expr = params.get("cron", "")
        if not cron_expr:
            return None
        try:
            import croniter
            cron = croniter.croniter(cron_expr, datetime.now())
            next_time = cron.get_next(datetime)
        except Exception:
            return None
        task_id = self._task_mgr.create_task(
            task_type=TaskType.PERIODIC,
            user_id=ctx.user_id,
            chat_id=ctx.chat_id,
            params=params,
            priority=1,
            scheduled_time=next_time,
        )
        logger.info("已创建周期性任务: %s, cron=%s, 下次=%s", task_id, cron_expr, next_time)
        return task_id

    @staticmethod
    def _parse_interval(interval_str: str) -> int:
        """解析时间间隔字符串为秒: 30m/2h/1d 等"""
        import re
        if not interval_str or not isinstance(interval_str, str):
            return 0
        m = re.match(r"(\d+)\s*(min|m|h|d|s)", interval_str.strip().lower())
        if not m:
            return 0
        value = int(m.group(1))
        unit = m.group(2)
        if unit in ("s",):
            return value
        elif unit in ("min", "m"):
            return value * 60
        elif unit in ("h",):
            return value * 3600
        elif unit in ("d",):
            return value * 86400
        return 0

    def _create_reasoner(self, params: dict, ctx: PluginContext) -> str:
        task_id = self._task_mgr.create_task(
            task_type=TaskType.REASONER,
            user_id=ctx.user_id,
            chat_id=ctx.chat_id,
            params=params,
            priority=1,
        )
        self._task_mgr.execute_task(task_id)
        logger.info("已创建并执行推理任务: %s", task_id)
        return task_id

    def _create_action(self, params: dict, ctx: PluginContext) -> str:
        if "action_type" not in params:
            params["action_type"] = "shell"
        task_id = self._task_mgr.create_task(
            task_type=TaskType.ACTION,
            user_id=ctx.user_id,
            chat_id=ctx.chat_id,
            params=params,
            priority=1,
        )
        self._task_mgr.execute_task(task_id)
        logger.info("已创建并执行动作任务: %s (类型: %s)", task_id, params.get("action_type"))
        return task_id
