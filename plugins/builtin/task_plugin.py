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
