# plugins/pipeline.py
# 对话管道 — 编排 5 个 HookPoint 的执行流程

from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator, Callable, Awaitable, Optional

from .base import HookPoint, PluginContext
from .manager import PluginManager

logger = logging.getLogger("ChatPipeline")


class ChatPipeline:
    """
    对话处理管道。

    编排流程:
      PRE_FILTER → PRE_PROCESS → [PromptEngine] → MODEL_INVOKE → POST_PROCESS → POST_TTS

    app.py 只调用 pipeline.process(ctx)，拿到结果后构造 HTTP 响应。

    prompt_engine 在 PRE_PROCESS 和 MODEL_INVOKE 之间被调用，
    根据 user_info 组装最终的 system_prompt。
    """

    def __init__(
        self,
        plugin_manager: PluginManager,
        prompt_engine=None,  # Optional[PromptEngine]
    ):
        self.pm = plugin_manager
        self._prompt_engine = prompt_engine

    # ---- 完整管道 ----

    async def process(self, ctx: PluginContext) -> PluginContext:
        """
        完整处理流程，返回处理后的 ctx。

        各阶段:
        1. PRE_FILTER  — ctx.filtered=True 则短路
        2. PRE_PROCESS — 上下文组装 (history + memories)
        3. [PromptEngine] — 构建 system_prompt
        4. MODEL_INVOKE— LLM 调用
        5. POST_PROCESS— 任务解析 + 对话保存
        6. POST_TTS    — TTS 语音合成
        """
        # 1
        ctx = await self.pm.dispatch(HookPoint.PRE_FILTER, ctx)
        if ctx.filtered:
            return ctx

        # 2
        ctx = await self.pm.dispatch(HookPoint.PRE_PROCESS, ctx)
        if ctx.filtered:
            return ctx

        # 2.5 — PromptEngine 组装 system prompt
        self._assemble_prompt(ctx)

        # 3
        ctx = await self.pm.dispatch(HookPoint.MODEL_INVOKE, ctx)

        # 4
        ctx = await self.pm.dispatch(HookPoint.POST_PROCESS, ctx)

        # 5
        ctx = await self.pm.dispatch(HookPoint.POST_TTS, ctx)

        return ctx

    def _assemble_prompt(self, ctx: PluginContext) -> None:
        """调用 PromptEngine 构建 system_prompt，写入 ctx"""
        if ctx.system_prompt:
            return  # 已有预设的 system_prompt，不覆盖
        if self._prompt_engine is None:
            return

        user_info = {
            "uid": ctx.user_id,
            "nickname": ctx.nickname,
        }
        ctx.system_prompt = self._prompt_engine.build_system_prompt(user_info)

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

            if hook == HookPoint.MODEL_INVOKE:
                self._assemble_prompt(ctx)

            ctx = await self.pm.dispatch(hook, ctx)

            if on_phase:
                try:
                    await on_phase(hook.value, ctx)
                except Exception:
                    logger.exception("on_phase 回调异常")

            if hook == HookPoint.MODEL_INVOKE and ctx.original_reply:
                yield f"data: {json.dumps({
                    'status': 'text_ready',
                    'reply': ctx.original_reply,
                    'chat_id': ctx.chat_id,
                })}\n\n"

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
