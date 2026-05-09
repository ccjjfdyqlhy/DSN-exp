# plugins/builtin/memory_plugin.py
# 记忆注入 + 对话保存插件 — PRE_PROCESS + POST_PROCESS

from __future__ import annotations

import logging
from typing import Optional

from plugins.base import Plugin, HookPoint, PluginContext

logger = logging.getLogger("MemoryPlugin")


class MemoryPlugin(Plugin):
    """
    在 PRE_PROCESS 阶段组装上下文（历史 + 记忆摘要），
    在 POST_PROCESS 阶段保存对话并异步生成摘要。

    依赖: memory_manager (MemoryManager 实例，可选), db (ChatDBManager 实例，可选)
    """

    name = "memory"
    description = "记忆管理 — 上下文组装 + 对话保存与摘要"
    hooks = [HookPoint.PRE_PROCESS, HookPoint.POST_PROCESS]
    priority = 30

    def __init__(self, memory_manager=None, db=None):
        self._memory = memory_manager
        self._db = db

    def on_load(self) -> None:
        if self._memory is None:
            logger.warning("memory_manager 未注入，MemoryPlugin 将跳过所有记忆操作")
        if self._db is None:
            logger.warning("db 未注入，MemoryPlugin 无法访问数据库")

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if hook == HookPoint.PRE_PROCESS:
            return self._on_pre_process(ctx)
        if hook == HookPoint.POST_PROCESS:
            return self._on_post_process(ctx)
        return ctx

    # ---- PRE_PROCESS ----

    def _on_pre_process(self, ctx: PluginContext) -> PluginContext:
        if self._memory is not None:
            ctx.full_history = self._memory.assemble_context(
                ctx.user_id, ctx.chat_id, ctx.history
            )
        else:
            ctx.full_history = list(ctx.history)
        return ctx

    # ---- POST_PROCESS ----

    def _on_post_process(self, ctx: PluginContext) -> PluginContext:
        if self._memory is None or self._db is None:
            return ctx

        try:
            round_index = self._db.get_memory_count(ctx.user_id, ctx.chat_id) + 1
            self._memory.record_dialog_and_summary(
                user_id=ctx.user_id,
                chat_id=ctx.chat_id,
                round_index=round_index,
                messages=[
                    {"role": "user", "content": ctx.message},
                    {"role": "assistant", "content": ctx.original_reply},
                ],
                async_mode=True,
            )
            logger.debug("记忆摘要任务已提交 (round=%d)", round_index)
        except Exception as e:
            logger.error("提交记忆摘要失败: %s", e)

        return ctx
