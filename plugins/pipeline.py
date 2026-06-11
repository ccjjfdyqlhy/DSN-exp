# plugins/pipeline.py
# 对话管道 — 编排 5 个 HookPoint 的执行流程
# UPD v2 — 并行推理 / 按行 TTS / 计时埋点

from __future__ import annotations

import asyncio
import json
import time
import logging
from copy import copy
from typing import AsyncGenerator, Callable, Awaitable, Optional

from .base import HookPoint, PluginContext
from .manager import PluginManager

logger = logging.getLogger("ChatPipeline")


class ChatPipeline:
    """
    对话处理管道。

    编排流程:
      PRE_FILTER → PRE_PROCESS → [PromptEngine] → MODEL_INVOKE → POST_PROCESS → POST_TTS

    PRE_PROCESS 支持图片模态并行:
      若 ctx.image_data 非空，VisionPlugin 与其余 PRE_PROCESS 插件并行执行。

    POST_PROCESS 支持 TTS 并行:
      若 ctx.tts_enabled，TTS 合成在后台与 POST_PROCESS 并行运行。
    """

    def __init__(
        self,
        plugin_manager: PluginManager,
        prompt_engine=None,  # Optional[PromptEngine]
        tts_client=None,      # VocalExp
        tts_profile_mgr=None, # TTSProfileManager
    ):
        self.pm = plugin_manager
        self._prompt_engine = prompt_engine
        self._tts_client = tts_client
        self._tts_profile_mgr = tts_profile_mgr

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
        ctx = await self._dispatch_pre_process(ctx)
        if ctx.filtered:
            return ctx

        # 2.5 — PromptEngine 组装 system prompt
        self._assemble_prompt(ctx)

        # 3
        ctx = await self.pm.dispatch(HookPoint.MODEL_INVOKE, ctx)

        # 4
        tts_lines = None
        if ctx.tts_enabled and ctx.original_reply and self._tts_client:
            tts_task = asyncio.create_task(
                self._synthesize_lines(ctx.original_reply)
            )
            ctx = await self.pm.dispatch(HookPoint.POST_PROCESS, ctx)
            tts_lines = await tts_task
        else:
            ctx = await self.pm.dispatch(HookPoint.POST_PROCESS, ctx)

        # 5 — TTS: 使用并行合成的结果或走插件
        if tts_lines is not None:
            if tts_lines:
                all_audio = b"".join(
                    line["audio_bytes"] for line in tts_lines if line.get("audio_bytes")
                )
                if all_audio:
                    import base64
                    ctx.audio = all_audio
                    ctx.audio_b64 = base64.b64encode(all_audio).decode("utf-8")
            ctx.extra["tts_lines"] = tts_lines
        else:
            ctx = await self.pm.dispatch(HookPoint.POST_TTS, ctx)

        return ctx

    def _assemble_prompt(self, ctx: PluginContext) -> None:
        """调用 PromptEngine 构建 system_prompt，写入 ctx"""
        if ctx.system_prompt:
            return
        if self._prompt_engine is None:
            return

        user_info = {
            "uid": ctx.user_id,
            "nickname": ctx.nickname,
        }
        ctx.system_prompt = self._prompt_engine.build_system_prompt(user_info)

    # ---- PRE_PROCESS 图片并行 ----

    async def _dispatch_pre_process(self, ctx: PluginContext) -> PluginContext:
        """PRE_PROCESS 阶段调度：若含图片则并行运行 VisionPlugin"""
        if not ctx.image_data:
            return await self.pm.dispatch(HookPoint.PRE_PROCESS, ctx)

        logger.info("检测到图片输入，启用 Vision/Memory 并行路径")

        # 并行：Vision 单独跑，其余插件一起跑
        vision_ctx = copy(ctx)
        other_ctx = copy(ctx)

        vision_task = asyncio.create_task(
            self.pm.dispatch_only(HookPoint.PRE_PROCESS, vision_ctx, {"vision"})
        )
        other_task = asyncio.create_task(
            self.pm.dispatch_except(HookPoint.PRE_PROCESS, other_ctx, {"vision"})
        )

        results = await asyncio.gather(vision_task, other_task, return_exceptions=True)
        vision_result, other_result = results

        if isinstance(other_result, Exception):
            logger.exception("PRE_PROCESS 并行(other)异常: %s", other_result)
        if isinstance(vision_result, Exception):
            logger.exception("PRE_PROCESS 并行(vision)异常: %s", vision_result)

        # 合并：vision 修改 ctx.message，other 修改 ctx.full_history / ctx.system_prompt
        if not isinstance(vision_result, Exception) and vision_result is not None:
            ctx.message = vision_result.message
            ctx.image_data = vision_result.image_data
            ctx.extra.update(vision_result.extra)

        result_ctx = other_result if not isinstance(other_result, Exception) else other_ctx
        ctx.full_history = result_ctx.full_history
        ctx.system_prompt = result_ctx.system_prompt
        ctx.filtered = result_ctx.filtered

        return ctx

    # ---- 按行 TTS 合成 ----

    async def _synthesize_lines(self, text: str) -> list[dict]:
        """在 executor 中同步合成各行 TTS 音频"""
        from utils.text_clean import clean_tts_text

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._synthesize_lines_sync, clean_tts_text(text)
        )

    def _synthesize_lines_sync(self, text: str) -> list[dict]:
        """同步按行合成 TTS（在 executor 线程中运行）"""
        import base64

        if not text or not self._tts_client:
            return []

        raw_lines = text.split("\n")
        lines = []
        for line in raw_lines:
            stripped = line.strip()
            if not stripped:
                continue
            if not any(c.isalpha() or "\u4e00" <= c <= "\u9fff" for c in stripped):
                continue
            lines.append(stripped)

        if not lines:
            return []

        results = []
        for i, line in enumerate(lines):
            try:
                params = self._tts_profile_mgr.build_params(line) if self._tts_profile_mgr else {
                    "text": line, "text_lang": "zh",
                    "ref_audio_path": "", "prompt_lang": "en", "prompt_text": "",
                    "media_type": "wav", "streaming_mode": False,
                }
                audio_bytes = self._tts_client.tts(**params)
                audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
                results.append({
                    "index": i,
                    "total": len(lines),
                    "text": line,
                    "audio_b64": audio_b64,
                    "audio_bytes": audio_bytes,
                })
                logger.debug("TTS 行 %d/%d 合成完成 (len=%d)", i + 1, len(lines), len(audio_b64))
            except Exception as e:
                logger.warning("TTS 行 %d 合成失败: %s", i + 1, e)
                results.append({
                    "index": i,
                    "total": len(lines),
                    "text": line,
                    "audio_b64": None,
                    "audio_bytes": None,
                })

        logger.info("按行 TTS 合成完成: %d/%d 行成功", 
                     sum(1 for r in results if r["audio_b64"]), len(results))
        return results

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
        每个阶段完成后 yield SSE 事件，含计时信息。

        用法:
            async for event in pipeline.process_stream(ctx):
                yield event
        """
        timing: dict[str, float] = {}
        t_total = time.perf_counter()
        tts_lines: list[dict] | None = None

        hooks_ordered = [
            HookPoint.PRE_FILTER,
            HookPoint.PRE_PROCESS,
            HookPoint.MODEL_INVOKE,
            HookPoint.POST_PROCESS,
            HookPoint.POST_TTS,
        ]

        for hook in hooks_ordered:
            t0 = time.perf_counter()
            status = self._HOOK_SSE_STATUS.get(hook, hook.value)
            yield f"data: {json.dumps({'status': status})}\n\n"

            if hook == HookPoint.PRE_FILTER:
                ctx = await self.pm.dispatch(hook, ctx)

            elif hook == HookPoint.PRE_PROCESS:
                ctx = await self._dispatch_pre_process(ctx)

            elif hook == HookPoint.MODEL_INVOKE:
                self._assemble_prompt(ctx)
                ctx = await self.pm.dispatch(hook, ctx)

                if ctx.original_reply:
                    yield f"data: {json.dumps({
                        'status': 'text_ready',
                        'reply': ctx.original_reply,
                        'chat_id': ctx.chat_id,
                    })}\n\n"

            elif hook == HookPoint.POST_PROCESS:
                # TTS 并行：在 executor 中后台合成，同时运行 POST_PROCESS
                tts_task = None
                if ctx.tts_enabled and ctx.original_reply and self._tts_client:
                    tts_task = asyncio.create_task(
                        self._synthesize_lines(ctx.original_reply)
                    )

                ctx = await self.pm.dispatch(hook, ctx)

                if tts_task:
                    tts_lines = await tts_task

                # 叙事文本
                narrative = ctx.extra.get("narrative", "")
                if narrative:
                    yield f"data: {json.dumps({
                        'status': 'narrative_update',
                        'text': narrative,
                        'speaker': 'narrator',
                    })}\n\n"

            elif hook == HookPoint.POST_TTS:
                if tts_lines is not None:
                    # 逐行发送 TTS 音频事件
                    for line in tts_lines:
                        yield f"data: {json.dumps({
                            'status': 'line',
                            'index': line['index'],
                            'total': line['total'],
                            'text': line['text'],
                            'audio_b64': line['audio_b64'],
                        })}\n\n"
                    if tts_lines:
                        all_audio = b"".join(
                            l["audio_bytes"] for l in tts_lines if l.get("audio_bytes")
                        )
                        if all_audio:
                            import base64
                            ctx.audio = all_audio
                            ctx.audio_b64 = base64.b64encode(all_audio).decode("utf-8")
                else:
                    ctx = await self.pm.dispatch(hook, ctx)

            timing[hook.value] = round((time.perf_counter() - t0) * 1000)

            if on_phase:
                try:
                    await on_phase(hook.value, ctx)
                except Exception:
                    logger.exception("on_phase 回调异常")

            if ctx.filtered:
                timing["total_ms"] = round((time.perf_counter() - t_total) * 1000)
                yield f"data: {json.dumps({
                    'status': 'completed',
                    'reply': ctx.reply,
                    'chat_id': ctx.chat_id,
                    'filtered': True,
                    'timing': timing,
                })}\n\n"
                return

        # 完成
        timing["total_ms"] = round((time.perf_counter() - t_total) * 1000)
        yield f"data: {json.dumps({
            'status': 'completed',
            'audio': ctx.audio_b64,
            'tts_error': ctx.tts_error,
            'timing': timing,
        })}\n\n"
