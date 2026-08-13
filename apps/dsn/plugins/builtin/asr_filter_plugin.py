# plugins/builtin/asr_filter_plugin.py
# ASR 语音输入过滤插件 — PRE_FILTER

from __future__ import annotations

import logging
from typing import Optional

from apps.dsn.plugins.base import Plugin, HookPoint, PluginContext

logger = logging.getLogger("ASRFilterPlugin")


class ASRFilterPlugin(Plugin):
    """
    过滤 ASR 语音输入，判断是否应转发给主 AI 模型。

    依赖: filter_model (LMFilterModel 实例，可选), db (ChatDBManager 实例，可选)
    """

    name = "asr_filter"
    description = "ASR 语音输入过滤 — 拦截非对话语音"
    hooks = [HookPoint.PRE_FILTER]
    priority = 10

    def __init__(self, filter_model=None, db=None):
        self._filter_model = filter_model
        self._db = db

    def on_load(self) -> None:
        if self._filter_model is None:
            logger.warning("filter_model 未注入，ASRFilterPlugin 将跳过所有过滤")
        if self._db is None:
            logger.warning("db 未注入，ASR 记忆保存将不可用")

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if not ctx.is_asr_input:
            return ctx

        if self._filter_model is None:
            logger.debug("filter_model 未配置，放行 ASR 输入")
            return ctx

        try:
            decision = self._filter_model.filter_input(ctx.message)
        except Exception as e:
            logger.error("过滤模型调用失败: %s，放行输入", e)
            return ctx

        if decision == "HOLD":
            logger.info("ASR 输入被过滤: %s...", ctx.message[:50])
            if self._db and ctx.chat_id:
                self._save_filtered_memory(ctx)
            ctx.filtered = True
            ctx.reply = ""
        else:
            logger.debug("ASR 输入放行")

        return ctx

    def _save_filtered_memory(self, ctx: PluginContext) -> None:
        """将过滤掉的语音输入保存为记忆"""
        try:
            memory_content = f"听到：{ctx.message}"
            round_index = self._db.get_next_round_index(ctx.chat_id)
            self._db.save_memory(ctx.user_id, ctx.chat_id, round_index, memory_content)
            self._db.append_messages(
                ctx.user_id,
                ctx.chat_id,
                [{"role": "system", "content": f"记忆摘要：{memory_content}"}],
            )
            logger.info("ASR 过滤记忆已保存: %s", memory_content)
        except Exception as e:
            logger.error("保存 ASR 记忆失败: %s", e)
