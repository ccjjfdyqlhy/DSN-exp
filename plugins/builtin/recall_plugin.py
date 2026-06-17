# plugins/builtin/recall_plugin.py
# 动态记忆召回插件 — POST_PROCESS (priority=33)
# 解析 <recall>/<memo> 标签，调用 MemorySystem 处理
# v3.0 — 适配 MemorySystem

from __future__ import annotations

import logging

from plugins.base import Plugin, HookPoint, PluginContext

logger = logging.getLogger("RecallPlugin")


class RecallPlugin(Plugin):
    name = "recall"
    description = "动态记忆召回 — 解析 <recall>/<memo> 标签"
    hooks = [HookPoint.POST_PROCESS]
    priority = 33

    def __init__(self, memory_system=None):
        self._ms = memory_system

    def on_load(self) -> None:
        if self._ms is None:
            logger.warning("memory_system 未注入，RecallPlugin 将跳过所有操作")

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if hook != HookPoint.POST_PROCESS or self._ms is None:
            return ctx
        if not ctx.original_reply:
            return ctx

        processed = self._ms.handle_tags(
            ctx.user_id, ctx.chat_id, ctx.original_reply
        )

        if processed != ctx.original_reply:
            ctx.extra["recall_executed"] = True

        ctx.reply = processed
        return ctx
