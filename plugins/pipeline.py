# plugins/pipeline.py
# 对话管道 — 编排 5 个 HookPoint 的执行流程
# UPD v2 — 并行推理 / 按行 TTS / 计时埋点

from __future__ import annotations

import asyncio
import json
import queue
import time
import logging
from copy import copy
from typing import AsyncGenerator, Callable, Awaitable, Optional

from .base import HookPoint, PluginContext
from .manager import PluginManager
from world.action_narrator import ActionNarrativeCollector

logger = logging.getLogger("ChatPipeline")


async def _task_completion_llm_reply(ctx, progress_q, output: str, error: str, success: bool):
    """任务完成后调用 LLM 生成自然语言回复，推送 text_ready，保存到 DB"""
    import asyncio as _asyncio
    loop = _asyncio.get_event_loop()

    def _invoke():
        pm = ctx.extra.get("_plugin_manager")
        if not pm:
            return None
        models_plugin = None
        for p in pm.get_hooks_for(HookPoint.MODEL_INVOKE):
            if p.__class__.__name__ == 'ModelsPlugin':
                models_plugin = p
                break
        if not models_plugin:
            return None

        from datetime import datetime
        msgs = [{"role": "system", "content": ctx.system_prompt}]
        msgs.extend(ctx.full_history)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msgs.append({"role": "user", "content": f"[{now}] {ctx.message}"})
        msgs.append({"role": "assistant", "content": ctx.original_reply})
        msg = f"[异步任务结果]\n"
        if success:
            msg += f"任务执行成功。\n输出:\n{output}"
        else:
            msg += f"任务执行失败。\n错误: {error}"
        msgs.append({"role": "user", "content": msg})

        try:
            return models_plugin.invoke(msgs, ctx)
        except Exception as e:
            logger.error("任务完成 LLM 调用失败: %s", e)
            return None

    reply = await loop.run_in_executor(None, _invoke)
    if not reply:
        return

    import re as _re
    clean = _re.sub(r"<[^>]+>", "", reply)
    clean = _re.sub(r"[^\S\n]+", " ", clean)
    clean = _re.sub(r"\n{2,}", "\n", clean).strip()
    if not clean:
        return

    ctx.reply = clean
    logger.info("[text_ready:task_llm] reply=%s", clean[:60])
    db = ctx.extra.get("_db")
    if db and ctx.chat_id:
        try:
            db.replace_last_assistant(ctx.user_id, ctx.chat_id, clean)
        except Exception:
            logger.exception("保存任务 LLM 回复到 DB 失败")

    await progress_q.put({
        "status": "text_ready",
        "reply": clean,
        "chat_id": ctx.chat_id,
    })


def _extract_narrations(raw: str) -> list[str]:
    """从原始回复中提取标签，生成人类可读的动作旁白"""
    import re as _re
    results = []
    for tag, label_gen in [
        ("recall", lambda _: "检索了相关记忆"),
        ("tool", lambda inner: _desc_tool(inner)),
        ("task", lambda inner: _desc_task(inner)),
    ]:
        for m in _re.finditer(rf"<{tag}>\s*(.*?)\s*</{tag}>", raw, _re.DOTALL):
            try:
                inner = m.group(1).strip()
                results.append(label_gen(inner))
            except Exception:
                pass
    return results


def _desc_tool(inner: str) -> str:
    try:
        d = json.loads(inner)
        return f"使用了工具 {d.get('tool', d.get('skill', ''))}"
    except Exception:
        return "调用了外部工具"


def _desc_task(inner: str) -> str:
    try:
        d = json.loads(inner)
        m = {"reminder": "设置了一个提醒", "reasoner": "开始深度推理",
             "action": "执行了一个操作", "analysis": "开始分析任务"}
        return m.get(d.get("type", ""), "安排了一个任务")
    except Exception:
        return "执行了一项后台任务"


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
        tts_process_model=None,  # TTSProcessModel
    ):
        self.pm = plugin_manager
        self._prompt_engine = prompt_engine
        self._tts_client = tts_client
        self._tts_profile_mgr = tts_profile_mgr
        self._tts_process_model = tts_process_model

    # ---- 完整管道 ----

    async def process(self, ctx: PluginContext) -> PluginContext:
        """
        完整处理流程，返回处理后的 ctx。

        各阶段:
        1. PRE_FILTER  — ctx.filtered=True 则短路
        2. [PromptEngine] — 构建 system_prompt (必须在 PRE_PROCESS 之前，供世界/印象注入)
        3. PRE_PROCESS — 上下文组装 + 世界状态/印象注入 system_prompt
        4. MODEL_INVOKE— LLM 调用
        5. POST_PROCESS— 任务解析 + 对话保存
        6. POST_TTS    — TTS 语音合成
        """
        # 1
        ctx = await self.pm.dispatch(HookPoint.PRE_FILTER, ctx)
        if ctx.filtered:
            return ctx

        # 2 — PromptEngine 组装 system prompt（为 PRE_PROCESS 插件提供底座）
        self._assemble_prompt(ctx)

        # 3
        ctx = await self._dispatch_pre_process(ctx)
        if ctx.filtered:
            return ctx

        # 3
        ctx = await self.pm.dispatch(HookPoint.MODEL_INVOKE, ctx)

        # 4
        tts_lines = None

        # 创建动作旁白收集器
        collector = ActionNarrativeCollector()
        ctx.extra["_narrative_collector"] = collector

        if ctx.tts_enabled and ctx.original_reply and self._tts_client:
            tts_task = asyncio.create_task(
                self._synthesize_lines(ctx.original_reply)
            )
            ctx = await self.pm.dispatch(HookPoint.POST_PROCESS, ctx)
            tts_lines = await tts_task
            # Agent 修改了回复时，丢弃旧 TTS，对最终回复重新合成
            if ctx.extra.get("_agent_reply_dirty") and ctx.reply and ctx.reply != ctx.original_reply:
                tts_lines = await self._synthesize_lines(ctx.reply)
        else:
            ctx = await self.pm.dispatch(HookPoint.POST_PROCESS, ctx)

        # 排空动作旁白
        action_narratives = collector.drain()
        if action_narratives:
            ctx.extra["action_narratives"] = action_narratives

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
        is_first = not ctx.history
        ctx.system_prompt = self._prompt_engine.build_system_prompt(
            user_info, is_first_interaction=is_first,
        )

        hint = ctx.extra.get("_sensing_hint", "")
        if hint:
            ctx.system_prompt += "\n\n" + hint

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
                processed_line = line
                if self._tts_process_model is not None:
                    processed_line = self._tts_process_model.process_tts_text(line)
                params = self._tts_profile_mgr.build_params(processed_line) if self._tts_profile_mgr else {
                    "text": processed_line, "text_lang": "zh",
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

    @staticmethod
    async def _bridge_progress(thread_q: queue.Queue, progress_q: asyncio.Queue):
        loop = asyncio.get_event_loop()
        while True:
            evt = await loop.run_in_executor(None, thread_q.get)
            if evt is None:
                break
            await progress_q.put(evt)

    async def _run_all_plugins(self, enabled: list, hook: HookPoint,
                                ctx: PluginContext, progress_q: asyncio.Queue):
        for plugin in enabled:
            desc = getattr(plugin, 'description', plugin.name)
            await progress_q.put({"status": "thinking", "text": desc, "plugin": plugin.name})
            try:
                ctx = await self.pm._call_plugin(plugin, hook, ctx)
            except Exception:
                logger.exception("插件 %s 在钩子 %s 中抛出异常", plugin.name, hook.value)
            if ctx.filtered:
                break

        task_mgr = ctx.extra.get("_task_manager")
        pending = ctx.extra.get("_pending_tasks", set())
        if task_mgr and pending:
            await self._poll_pending_tasks(ctx, pending, progress_q)

        thread_q = ctx.extra.get("_progress_queue")
        if thread_q:
            thread_q.put(None)
        await progress_q.put(None)

    async def _poll_pending_tasks(self, ctx, remaining, progress_q):
        from tasks import TaskStatus
        deadline = time.time() + 120
        await progress_q.put({
            "status": "thinking",
            "text": f"等待 {len(remaining)} 个异步任务完成...",
        })
        while remaining and time.time() < deadline:
            for tid in list(remaining):
                task_mgr = ctx.extra.get("_task_manager")
                task = task_mgr.get_task(tid) if task_mgr else None
                if task and task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                    remaining.discard(tid)
                    result = task.result or {}
                    success = result.get("success", False) if isinstance(result, dict) else False
                    output = result.get("output", "") if isinstance(result, dict) else ""
                    error = task.error or result.get("error", "") if isinstance(result, dict) else ""
                    evt = {"status": "task_result", "task_id": tid[:8], "success": success}
                    if output:
                        out = str(output).strip()
                        if len(out) > 2000:
                            out = out[:2000] + "\n...(输出截断)"
                        evt["output"] = out
                    if error:
                        evt["error"] = str(error)[:500]
                    await progress_q.put(evt)
                    if output and success:
                        await _task_completion_llm_reply(ctx, progress_q, output, error, success)
            if remaining:
                await asyncio.sleep(0.3)

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
                self._assemble_prompt(ctx)
                ctx = await self._dispatch_pre_process(ctx)

                # 前置旁白
                pre_narrative = ctx.extra.get("pre_narrative", "")
                if pre_narrative:
                    yield f"data: {json.dumps({
                        'status': 'narrative_update',
                        'text': pre_narrative,
                        'speaker': 'narrator',
                        'style': 'pre',
                    })}\n\n"

            elif hook == HookPoint.MODEL_INVOKE:
                ctx = await self.pm.dispatch(hook, ctx)

                if ctx.original_reply:
                    if ctx.reply and ctx.reply != "…":
                        logger.info("[text_ready:model_invoke] reply=%s", ctx.reply[:60])
                        yield f"data: {json.dumps({
                            'status': 'text_ready',
                            'reply': ctx.reply,
                            'chat_id': ctx.chat_id,
                        })}\n\n"

                    narrations = _extract_narrations(ctx.original_reply)
                    for n in narrations:
                        yield f"data: {json.dumps({
                            'status': 'narrative_update',
                            'text': n,
                            'speaker': 'narrator',
                            'style': 'action',
                        })}\n\n"

            elif hook == HookPoint.POST_PROCESS:
                collector = ActionNarrativeCollector()
                ctx.extra["_narrative_collector"] = collector

                tts_task = None
                if ctx.tts_enabled and ctx.original_reply and self._tts_client:
                    tts_task = asyncio.create_task(
                        self._synthesize_lines(ctx.original_reply)
                    )

                plugins = self.pm.get_hooks_for(HookPoint.POST_PROCESS)
                enabled = [p for p in plugins if self.pm.is_enabled(p.name)]

                progress_q: asyncio.Queue = asyncio.Queue()
                thread_q = queue.Queue()
                ctx.extra["_progress_queue"] = thread_q
                ctx.extra["_plugin_manager"] = self.pm

                bridge_task = asyncio.create_task(self._bridge_progress(thread_q, progress_q))
                runner = asyncio.create_task(self._run_all_plugins(enabled, hook, ctx, progress_q))

                import asyncio as _asyncio
                while True:
                    try:
                        evt = await _asyncio.wait_for(progress_q.get(), timeout=3.0)
                        if evt is None:
                            break
                        yield f"data: {json.dumps(evt)}\n\n"
                    except _asyncio.TimeoutError:
                        yield f"data: {json.dumps({
                            'status': 'thinking',
                            'text': '正在处理...',
                        })}\n\n"

                await runner
                await runner
                await bridge_task

                if tts_task:
                    tts_lines = await tts_task

                narrative = ctx.extra.get("narrative", "")
                if narrative:
                    yield f"data: {json.dumps({
                        'status': 'narrative_update',
                        'text': narrative,
                        'speaker': 'narrator',
                        'style': 'post',
                    })}\n\n"

                if ctx.extra.get("confirm_requested"):
                    yield f"data: {json.dumps({
                        'status': 'confirm_requested',
                    })}\n\n"

                for text in collector.drain():
                    if text:
                        yield f"data: {json.dumps({
                            'status': 'narrative_update',
                            'text': text,
                            'speaker': 'narrator',
                            'style': 'action',
                        })}\n\n"

                if ctx.extra.get("_agent_reply_dirty") and ctx.reply:
                    db = ctx.extra.get("_db")
                    if db and ctx.chat_id:
                        try:
                            db.replace_last_assistant(ctx.user_id, ctx.chat_id, ctx.reply)
                        except Exception:
                            logger.exception("更新 Agent 回复到 DB 失败")
                    yield f"data: {json.dumps({
                        'status': 'text_ready',
                        'reply': ctx.reply,
                        'chat_id': ctx.chat_id,
                    })}\n\n"
                    logger.info("[text_ready:agent_dirty] reply=%s", ctx.reply[:60])
                    if ctx.tts_enabled and self._tts_client and ctx.reply != ctx.original_reply:
                        tts_lines = await self._synthesize_lines(ctx.reply)
                    ctx.extra["_agent_reply_dirty"] = False

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
        completed = {
            'status': 'completed',
            'audio': ctx.audio_b64,
            'tts_error': ctx.tts_error,
            'timing': timing,
        }
        if ctx.extra.get("confirm_requested"):
            completed["confirm_requested"] = True
        if ctx.usage:
            completed['usage'] = ctx.usage
            completed['model_name'] = ctx.model_name
        yield f"data: {json.dumps(completed)}\n\n"
