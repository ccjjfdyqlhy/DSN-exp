# plugins/builtin/task_plugin.py
# 任务解析与执行插件 — POST_PROCESS

from __future__ import annotations

import json
import re
import logging
from datetime import datetime
from typing import Optional

from plugins.base import Plugin, HookPoint, PluginContext

logger = logging.getLogger("TaskPlugin")


class TaskPlugin(Plugin):
    """
    解析 AI 回复中的 <task> 和 <tool> 标签，创建并执行后台任务。

    依赖: task_manager (TaskManager 实例，可选),
          db (ChatDBManager 实例，可选),
          skill_registry (SkillRegistry 实例，可选 — 技能系统完成后使用)
    """

    name = "task"
    description = "任务解析 — 解析 <task>/<tool> 标签并调度执行"
    hooks = [HookPoint.POST_PROCESS]
    priority = 40

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

        tasks = self._parse_tasks(ctx.original_reply)
        if not tasks:
            return ctx

        for task_data in tasks:
            self._handle_task(task_data, ctx)

        return ctx

    # ---- 解析 ----

    _ACTION_RE = re.compile(r"```action\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
    _TASK_RE = re.compile(r"<task>(.*?)</task>", re.DOTALL | re.IGNORECASE)

    @classmethod
    def _parse_tasks(cls, text: str) -> list[dict]:
        """解析回复中的 <task> 指令，支持两种顺序的 action 代码块配对"""
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

    # ---- 任务处理 ----

    def _handle_task(self, task_data: dict, ctx: PluginContext) -> None:
        from tasks import TaskType

        task_type = task_data.get("type")
        params = task_data.get("params", {})

        try:
            if task_type == "reminder":
                self._create_reminder(params, ctx)
            elif task_type == "reasoner":
                self._create_reasoner(params, ctx)
            elif task_type == "action":
                self._create_action(params, ctx)
        except Exception:
            logger.exception("处理任务失败: %s", task_data)

    def _create_reminder(self, params: dict, ctx: PluginContext) -> None:
        time_str = params.get("time")
        if not time_str:
            return
        scheduled_time = datetime.fromisoformat(time_str)
        task_id = self._task_mgr.create_task(
            task_type=1,  # TaskType.REMINDER
            user_id=ctx.user_id,
            chat_id=ctx.chat_id,
            params=params,
            priority=1,
            scheduled_time=scheduled_time,
        )
        logger.info("已创建提醒任务: %s, 时间: %s", task_id, scheduled_time)

    def _create_reasoner(self, params: dict, ctx: PluginContext) -> None:
        task_id = self._task_mgr.create_task(
            task_type=2,  # TaskType.REASONER
            user_id=ctx.user_id,
            chat_id=ctx.chat_id,
            params=params,
            priority=1,
        )
        self._task_mgr.execute_task(task_id)
        logger.info("已创建并执行推理任务: %s", task_id)

    def _create_action(self, params: dict, ctx: PluginContext) -> None:
        if "action_type" not in params:
            params["action_type"] = "shell"
        task_id = self._task_mgr.create_task(
            task_type=3,  # TaskType.ACTION
            user_id=ctx.user_id,
            chat_id=ctx.chat_id,
            params=params,
            priority=1,
        )
        self._task_mgr.execute_task(task_id)
        logger.info("已创建并执行动作任务: %s (类型: %s)", task_id, params.get("action_type"))
