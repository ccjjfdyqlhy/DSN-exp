# plugins/pipeline.py
# 对话管道 — 编排 5 个 HookPoint 的执行流程

from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator, Callable, Awaitable

from .base import HookPoint, PluginContext
from .manager import PluginManager

logger = logging.getLogger("ChatPipeline")


class ChatPipeline:
    """
    对话处理管道。

    编排流程:
      PRE_FILTER → PRE_PROCESS → MODEL_INVOKE → POST_PROCESS → POST_TTS

    app.py 只调用 pipeline.process(ctx)，拿到结果后构造 HTTP 响应。
    """

    def __init__(self, plugin_manager: PluginManager):
        self.pm = plugin_manager

    # ---- 完整管道 ----

    async def process(self, ctx: PluginContext) -> PluginContext:
        """
        完整处理流程，返回处理后的 ctx。

        各阶段:
        1. PRE_FILTER  — ctx.filtered=True 则短路
        2. PRE_PROCESS — system_prompt + 上下文组装
        3. MODEL_INVOKE— LLM 调用
        4. POST_PROCESS— 任务解析 + 对话保存
        5. POST_TTS    — TTS 语音合成
        """
        # 1
        ctx = await self.pm.dispatch(HookPoint.PRE_FILTER, ctx)
        if ctx.filtered:
            return ctx

        # 2
        ctx = await self.pm.dispatch(HookPoint.PRE_PROCESS, ctx)
        if ctx.filtered:
            return ctx

        # 3
        ctx = await self.pm.dispatch(HookPoint.MODEL_INVOKE, ctx)

        # 4
        ctx = await self.pm.dispatch(HookPoint.POST_PROCESS, ctx)

        # 5
        ctx = await self.pm.dispatch(HookPoint.POST_TTS, ctx)

        return ctx

    # ---- 流式管道（SSE） ----

    _HOOK_SSE_STATUS = {
        HookPoint.PRE_FILTER:   "filtering",
        HookPoint.PRE_PROCESS:  "parsing",
        HookPoint.MODEL_INVOKE: "request",
        HookPoint.POST_PROCESS: "execution",
        HookPoint.POST_TTS:     "tts",
    }

    async def process_stream(
        self, ctx: PluginContext, *,
        on_phase: Callable[[str, PluginContext], Awaitable[None]] | None = None
    ) -> AsyncGenerator[str, None]:
        """
        带 SSE 阶段通知的流式处理。
        每个阶段完成后 yield SSE 事件。

        用法:
            async for event in pipeline.process_stream(ctx):
                yield event
        """
        import json

        hooks_ordered = [
            HookPoint.PRE_FILTER,
            HookPoint.PRE_PROCESS,
            HookPoint.MODEL_INVOKE,
            HookPoint.POST_PROCESS,
            HookPoint.POST_TTS,
        ]

        for hook in hooks_ordered:
            status = self._HOOK_SSE_STATUS.get(hook, hook.value)
            yield f"data: {json.dumps({'status': status})}\n\n"

            ctx = await self.pm.dispatch(hook, ctx)

            if on_phase:
                try:
                    await on_phase(hook.value, ctx)
                except Exception:
                    logger.exception("on_phase 回调异常")

            if ctx.filtered:
                yield f"data: {json.dumps({
                    'status': 'completed',
                    'reply': ctx.reply,
                    'chat_id': ctx.chat_id,
                    'filtered': True
                })}\n\n"
                return

        # 完成
        yield f"data: {json.dumps({
            'status': 'completed',
            'audio': ctx.audio_b64,
            'tts_error': ctx.tts_error,
        })}\n\n"
