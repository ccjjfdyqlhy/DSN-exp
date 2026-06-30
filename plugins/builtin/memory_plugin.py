# plugins/builtin/memory_plugin.py
# 记忆注入 + 对话保存插件 — PRE_PROCESS + POST_PROCESS
# v3.0 — 适配 MemorySystem

from __future__ import annotations

import logging
from typing import Optional

from plugins.base import Plugin, HookPoint, PluginContext

logger = logging.getLogger("MemoryPlugin")


class MemoryPlugin(Plugin):
    name = "memory"
    description = "记忆管理 — 上下文组装 + 对话保存与摘要"
    hooks = [HookPoint.PRE_PROCESS, HookPoint.POST_PROCESS]
    priority = 30

    def __init__(self, memory_system=None, db=None):
        self._ms = memory_system
        self._db = db

    def on_load(self) -> None:
        if self._ms is None:
            logger.warning("memory_system 未注入，MemoryPlugin 将跳过所有记忆操作")
        if self._db is None:
            logger.warning("db 未注入，MemoryPlugin 无法访问数据库")

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if hook == HookPoint.PRE_PROCESS:
            return self._on_pre_process(ctx)
        if hook == HookPoint.POST_PROCESS:
            return self._on_post_process(ctx)
        return ctx

    def _on_pre_process(self, ctx: PluginContext) -> PluginContext:
        if self._ms is not None:
            ctx.full_history = self._ms.assemble_context(
                ctx.user_id, ctx.history
            )
        else:
            ctx.full_history = list(ctx.history)
        return ctx

    def _on_post_process(self, ctx: PluginContext) -> PluginContext:
        if self._ms is None or self._db is None:
            return ctx
        if ctx.extra.get("_debug_mode"):
            return ctx

        try:
            round_index = ctx.extra.get("round_index") or self._db.get_next_round_index(ctx.chat_id)
            self._ms.summarize_turn(
                user_id=ctx.user_id,
                chat_id=ctx.chat_id,
                round_idx=round_index,
                user_msg=ctx.message,
                assistant_reply=ctx.original_reply,
                async_mode=True,
            )
            logger.debug("记忆摘要任务已提交 (round=%d)", round_index)
        except Exception as e:
            logger.error("提交记忆摘要失败: %s", e)

        return ctx
