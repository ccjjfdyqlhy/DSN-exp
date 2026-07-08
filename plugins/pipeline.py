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
from config import Config

logger = logging.getLogger("ChatPipeline")

_TIMER_ENABLED = False


def timer_enabled() -> bool:
    # check if stage timer is running
    return _TIMER_ENABLED


def enable_timer():
    global _TIMER_ENABLED
    _TIMER_ENABLED = True


def disable_timer():
    global _TIMER_ENABLED
    _TIMER_ENABLED = False


def toggle_timer() -> bool:
    # flip timer state and return new state
    global _TIMER_ENABLED
    _TIMER_ENABLED = not _TIMER_ENABLED
    return _TIMER_ENABLED


async def _call_llm_with_msgs(ctx, msgs: list[dict]) -> str | None:
    """调用主模型，返回原始回复"""
    import asyncio as _asyncio
    loop = _asyncio.get_event_loop()

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

    def _invoke():
        # call llm with optional tool schemas
        try:
            tools = None
            if hasattr(models_plugin, '_build_tools_schema'):
                tools = models_plugin._build_tools_schema()
            return models_plugin.invoke(msgs, ctx, tools=tools)
        except Exception as e:
            logger.error("LLM 调用失败: %s", e)
            return None

    return await loop.run_in_executor(None, _invoke)


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


def _log_stage_timing(stage: str, ms: float):
    # log per-stage timing if timer is on
    if _TIMER_ENABLED:
        logger.info("  ⏱ %-15s %8.0fms", stage, ms)


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
        prompt_engine=None,
        tts_client=None,
        tts_profile_mgr=None,
        tts_process_model=None,
        async_task_store=None,
        skill_registry=None,
    ):
        # wire up pipeline dependencies
        self.pm = plugin_manager
        self._prompt_engine = prompt_engine
        self._tts_client = tts_client
        self._tts_profile_mgr = tts_profile_mgr
        self._tts_process_model = tts_process_model
        self._async_store = async_task_store
        self._skill_registry = skill_registry

    # ---- 管道子阶段（供调试模式等复用） ----

    @staticmethod
    def _concat_wav(wav_chunks: list[bytes]) -> bytes | None:
        """正确拼接多个 WAV 文件（去除多余文件头，只保留首个 WAV 的文件头）。"""
        if not wav_chunks:
            return None
        if len(wav_chunks) == 1:
            return wav_chunks[0]
        # 各 WAV 均为 44 字节 RIFF 头 + PCM 数据
        pcm_parts = []
        total_pcm = 0
        for buf in wav_chunks:
            if len(buf) > 44:
                pcm = buf[44:]
                pcm_parts.append(pcm)
                total_pcm += len(pcm)
        if not pcm_parts:
            return wav_chunks[0]
        # 复用第一个 WAV 的头部，更新数据尺寸
        header = bytearray(wav_chunks[0][:44])
        # data 子块大小 (bytes 40-43)
        header[40:44] = total_pcm.to_bytes(4, 'little')
        # RIFF 总大小 - 8 (bytes 4-7)
        riff_size = 36 + total_pcm
        header[4:8] = riff_size.to_bytes(4, 'little')
        return bytes(header) + b"".join(pcm_parts)

    async def process_tts(self, ctx: PluginContext) -> PluginContext:
        """仅执行 TTS 合成"""
        if ctx.tts_enabled and ctx.reply:
            if self._tts_client:
                tts_lines = await self._synthesize_lines(ctx.reply)
                if tts_lines:
                    all_audio = self._concat_wav(
                        [l["audio_bytes"] for l in tts_lines if l.get("audio_bytes")])
                    if all_audio:
                        import base64
                        ctx.audio = all_audio
                        ctx.audio_b64 = base64.b64encode(all_audio).decode("utf-8")
            else:
                ctx = await self.pm.dispatch(HookPoint.POST_TTS, ctx)
        return ctx

    async def process_pre_process(self, ctx: PluginContext) -> PluginContext:
        """执行管线前半段：PRE_FILTER → PRE_PROCESS（不含 MODEL_INVOKE）"""
        ctx = await self.pm.dispatch(HookPoint.PRE_FILTER, ctx)
        if ctx.filtered:
            return ctx
        self._assemble_prompt(ctx)
        ctx = await self._dispatch_pre_process(ctx)
        return ctx

    async def process_post_process(self, ctx: PluginContext, *,
                                     skip_agent_loop: bool = False) -> PluginContext:
        """执行管线后半段：POST_PROCESS → Agent Loop（跳过 MODEL_INVOKE，不含 TTS）"""
        ctx = await self._dispatch_post_process(ctx)
        if not skip_agent_loop and ctx.agent_active and ctx.extra.get("_tag_results"):
            ctx = await self._run_agent_loop(ctx)
        return ctx

    # ---- 完整管道 ----

    async def process(self, ctx: PluginContext) -> PluginContext:
        # run full pipeline: pre-filter, pre-process, model invoke, post-process, tts
        timing: dict[str, float] = {}
        t_total = time.perf_counter()
        if _TIMER_ENABLED:
            ctx.extra["_plugin_timings"] = {}

        # 1
        t0 = time.perf_counter()
        ctx = await self.pm.dispatch(HookPoint.PRE_FILTER, ctx)
        timing["pre_filter"] = round((time.perf_counter() - t0) * 1000, 1)
        _log_stage_timing("PRE_FILTER", timing["pre_filter"])
        if ctx.filtered:
            self._print_timing(timing, ctx)
            return ctx

        # 2 — PromptEngine 组装 system prompt（为 PRE_PROCESS 插件提供底座）
        t0 = time.perf_counter()
        self._assemble_prompt(ctx)
        timing["pre_process"] = 0.0

        # 3
        t0 = time.perf_counter()
        ctx = await self._dispatch_pre_process(ctx)
        timing["pre_process"] += round((time.perf_counter() - t0) * 1000, 1)
        _log_stage_timing("PRE_PROCESS", timing["pre_process"])
        if ctx.filtered:
            self._print_timing(timing, ctx)
            return ctx

        # 3 — MODEL_INVOKE（若剧本回放命中则跳过）
        t0 = time.perf_counter()
        if not ctx.skip_model:
            ctx = await self.pm.dispatch(HookPoint.MODEL_INVOKE, ctx)
        timing["model_invoke"] = round((time.perf_counter() - t0) * 1000, 1)
        _log_stage_timing("MODEL_INVOKE", timing["model_invoke"])
        if ctx.filtered:
            self._print_timing(timing, ctx)
            return ctx

        # ── 异步工具检测：含 async 标记的工具调用 → 后台执行 ──
        if ctx.extra.get("_async_detected") and self._async_store:
            ctx = await self._run_async_background(ctx)
            timing["total_ms"] = round((time.perf_counter() - t_total) * 1000, 1)
            self._print_timing(timing, ctx)
            return ctx

        # 创建动作旁白收集器
        collector = ActionNarrativeCollector()
        ctx.extra["_narrative_collector"] = collector

        # 4 — POST_PROCESS（支持 agent 循环）
        t0 = time.perf_counter()
        ctx = await self._dispatch_post_process(ctx)
        timing["post_process"] = round((time.perf_counter() - t0) * 1000, 1)
        _log_stage_timing("POST_PROCESS", timing["post_process"])

        # ── Agent 循环：标签结果回馈 LLM ──
        if ctx.agent_active and ctx.extra.get("_tag_results"):
            t0 = time.perf_counter()
            ctx = await self._run_agent_loop(ctx)
            timing["agent_loop"] = round((time.perf_counter() - t0) * 1000, 1)
            _log_stage_timing("Agent Loop", timing["agent_loop"])

        # 排空动作旁白
        action_narratives = collector.drain()
        if action_narratives:
            ctx.extra["action_narratives"] = action_narratives

        # 5 — TTS: 对最终回复合成
        t0 = time.perf_counter()
        if ctx.tts_enabled and ctx.reply and self._tts_client:
            tts_lines = await self._synthesize_lines(ctx.reply)
            if tts_lines:
                all_audio = self._concat_wav(
                    [l["audio_bytes"] for l in tts_lines if l.get("audio_bytes")]
                )
                if all_audio:
                    import base64
                    ctx.audio = all_audio
                    ctx.audio_b64 = base64.b64encode(all_audio).decode("utf-8")
            ctx.extra["tts_lines"] = tts_lines
        else:
            ctx = await self.pm.dispatch(HookPoint.POST_TTS, ctx)
        timing["post_tts"] = round((time.perf_counter() - t0) * 1000, 1)
        _log_stage_timing("POST_TTS", timing["post_tts"])

        timing["total_ms"] = round((time.perf_counter() - t_total) * 1000, 1)
        self._print_timing(timing, ctx)

        return ctx

    async def _dispatch_post_process(self, ctx: PluginContext) -> PluginContext:
        # run post-process hook, no agent loop
        return await self.pm.dispatch(HookPoint.POST_PROCESS, ctx)

    async def _run_async_background(self, ctx: PluginContext) -> str:
        # kick off a non-blocking background pipeline
        import threading
        import uuid

        task_id = f"async_{uuid.uuid4().hex[:16]}"
        store = self._async_store
        store.create(task_id, ctx.user_id, ctx.chat_id or 0)

        from copy import deepcopy

        # 弹出 deepcopy 不安全的键（_thread._local 等不可 pickle 的对象）
        _safe_keys = ('_db', '_task_manager', '_completion_queue')
        _shared = {}
        for _k in _safe_keys:
            try:
                _shared[_k] = ctx.extra.pop(_k)
            except KeyError:
                pass

        _unpickleable = []
        for _k in list(ctx.extra.keys()):
            try:
                deepcopy(ctx.extra[_k])
            except Exception:
                _unpickleable.append(_k)
        _stashed = {}
        for _k in _unpickleable:
            _stashed[_k] = ctx.extra.pop(_k)

        try:
            _ctx = deepcopy(ctx)
        finally:
            for _k, _v in _shared.items():
                ctx.extra[_k] = _v
            for _k, _v in _stashed.items():
                ctx.extra[_k] = _v

        for _k, _v in _shared.items():
            _ctx.extra[_k] = _v
        for _k, _v in _stashed.items():
            _ctx.extra[_k] = _v

        _pm = self.pm

        def _run_tool():
            """后台线程：仅执行工具调用，不走 Agent Loop / TTS"""
            _loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(_loop)
                ntc = len(_ctx.extra.get("_native_tool_calls", []))
                logger.info("异步后台 POST_PROCESS 开始 (async=%s, native_tool_calls=%d)",
                             task_id, ntc)
                _sctx = _loop.run_until_complete(_pm.dispatch(HookPoint.POST_PROCESS, _ctx))

                tag_results = _sctx.extra.get("_tag_results", [])
                logger.info("异步后台 POST_PROCESS 完成 (async=%s, tag_results=%d)",
                             task_id, len(tag_results))

                linked = False
                for i, r in enumerate(tag_results):
                    logger.info("  tag_result[%d]: function=%s success=%s data=%s",
                                 i, r.get("function", "?"), r.get("success"),
                                 str(r.get("data", {}))[:120])
                    if not r.get("success"):
                        continue
                    tdata = r.get("data", {})
                    if isinstance(tdata, dict):
                        tm_id = tdata.get("task_id", "")
                        if tm_id and len(tm_id) > 8:
                            store.link_taskmgr(task_id, tm_id)
                            linked = True
                            logger.info("  → 已联动 async=%s -> taskmgr=%s", task_id, tm_id)

                if not linked:
                    reply = _sctx.reply or "任务已完成"
                    store.complete(task_id, reply=reply)
                    logger.info("异步工具无 taskmgr 联动，立即完成 (async=%s)", task_id)
                else:
                    logger.info("异步工具已联动 taskmgr，等待 taskmgr 完成时再标记 (async=%s, taskmgr=%s)",
                                task_id, tm_id)
            except Exception as e:
                logger.error("异步后台执行失败 %s: %s", task_id, e)
                store.complete(task_id, error=str(e))
            finally:
                _loop.close()

        threading.Thread(target=_run_tool, daemon=True).start()
        ctx.reply = "任务已创建，后台执行中…"
        ctx.extra["_async_task_id"] = task_id
        logger.info("异步切换: task_id=%s", task_id)
        return task_id

    @staticmethod
    def _report_agent_progress(ctx: PluginContext, step: int, max_steps: int,
                               tool_names: list[str], done: bool = False,
                               reply_text: str = None):
        """向流式前端推送 Agent 步骤进度（非阻塞，通过 ctx 内的线程安全队列）"""
        q = ctx.extra.get("_agent_progress_queue")
        if q is None:
            return
        if done:
            q.put(None)
            return
        tool_text = ", ".join(tool_names) if tool_names else "处理中"
        evt = {
            "status": "agent_progress",
            "step": step,
            "max": max_steps,
            "text": f"[{step}/{max_steps}] {tool_text}",
        }
        if reply_text:
            evt["reply"] = reply_text
        q.put(evt)

    async def _run_agent_loop(self, ctx: PluginContext) -> PluginContext:
        from datetime import datetime
        max_steps = ctx.agent_max_steps or 5
        loop = asyncio.get_event_loop()
        logger.info("_run_agent_loop 启动, max_steps=%d", max_steps)

        models_plugin = None
        for p in self.pm.get_hooks_for(HookPoint.MODEL_INVOKE):
            if p.__class__.__name__ == "ModelsPlugin":
                models_plugin = p
                break

        self._report_agent_progress(ctx, 0, max_steps, ["开始处理"])

        for step in range(max_steps):
            results = ctx.extra.pop("_tag_results", [])
            if not results:
                logger.info("Agent 第 %d 步: _tag_results 为空", step + 1)
                break

            # 提取本次执行了哪些工具，用于进度提示
            tool_names = []
            for r in results:
                func = r.get("function", "")
                # "skill-document-process_scan" → "process_scan"
                short = func.rsplit("-", 1)[-1] if "-" in func else func
                if short:
                    tool_names.append(short)

            # 检测是否为原生 tool call 结果（有 function 和 tool_call_id 字段）
            has_native_results = any(
                r.get("function") and r.get("tool_call_id") for r in results
            )

            if has_native_results and models_plugin:
                msgs: list[dict] = [{"role": "system", "content": ctx.system_prompt}]
                msgs.extend(ctx.full_history)
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                msgs.append({"role": "user", "content": f"[{now}] {ctx.message}"})

                # assistant 消息必须携带 tool_calls（对应后续 tool role 消息）
                last_tool_calls = ctx.extra.pop("_last_tool_calls", [])
                assistant_msg = {"role": "assistant",
                                 "content": ctx.original_reply or ctx.reply}
                if last_tool_calls:
                    assistant_msg["tool_calls"] = last_tool_calls
                msgs.append(assistant_msg)

                for r in results:
                    content = json.dumps(r.get("data", r.get("error", "")),
                                         ensure_ascii=False, default=str)
                    msgs.append({
                        "role": "tool",
                        "tool_call_id": r.get("tool_call_id", "unknown"),
                        "content": content,
                    })

                tools_schema = None
                if hasattr(models_plugin, '_build_tools_schema'):
                    tools_schema = models_plugin._build_tools_schema()

                self._report_agent_progress(ctx, step + 1, max_steps, tool_names)

                try:
                    new_reply = await loop.run_in_executor(
                        None, lambda: models_plugin.invoke(msgs, ctx, tools=tools_schema)
                    )
                except Exception as e:
                    logger.error("Agent 第 %d 步(native): invoke 失败: %s", step + 1, e)
                    break
                if not new_reply:
                    has_pending = bool(ctx.extra.get("_native_tool_calls", []))
                    if not has_pending:
                        logger.warning("Agent 第 %d 步(native): LLM 返回空且无待处理 tool_calls，终止",
                                       step + 1)
                        break
                    logger.info("Agent 第 %d 步(native): LLM 返回空但有 %d 个待处理 tool_calls，继续执行",
                                step + 1, len(ctx.extra.get("_native_tool_calls", [])))

                logger.info("Agent 第 %d 步(native): LLM 回复 %d 字符",
                            step + 1, len(new_reply or ""))
                ctx.original_reply = new_reply
                reply_text = (models_plugin._clean_reply(new_reply)
                              if new_reply else "…")
                ctx.reply = reply_text
                ctx.extra["_agent_step"] = step + 1

                # 将本轮 LLM 回复推送给前端（非空且不是占位符时 TTS 会朗读）
                if new_reply:
                    self._report_agent_progress(ctx, step + 1, max_steps,
                                                 tool_names, reply_text=reply_text)

                ctx = await self._dispatch_post_process(ctx)
                if step >= max_steps - 1:
                    logger.warning("Agent 达到最大步数 %d", max_steps)
                continue

            # 降级模式：传统 XML 标签处理
            formatted = self._format_tag_results(results)
            logger.info("Agent 第 %d 步(xml): %d 个标签执行完毕",
                        step + 1, len(results))

            self._report_agent_progress(ctx, step + 1, max_steps, tool_names)

            msgs: list[dict] = [{"role": "system", "content": ctx.system_prompt}]
            msgs.extend(ctx.full_history)
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            msgs.append({"role": "user", "content": f"[{now}] {ctx.message}"})
            msgs.append({"role": "assistant", "content": ctx.reply})
            msgs.append({"role": "user", "content": f"[执行结果]\n{formatted}"})

            if models_plugin is None:
                logger.warning("models_plugin 未找到，中断 agent 循环")
                break

            try:
                new_reply = await loop.run_in_executor(
                    None, lambda: models_plugin.invoke(msgs, ctx)
                )
            except Exception as e:
                logger.error("Agent 第 %d 步(xml): invoke 失败: %s", step + 1, e)
                break
            if not new_reply:
                logger.info("Agent 第 %d 步: LLM 返回空", step + 1)
                break

            logger.info("Agent 第 %d 步(xml): LLM 回复 %d 字符",
                        step + 1, len(new_reply))
            ctx.original_reply = new_reply
            ctx.reply = new_reply
            ctx.extra["_agent_step"] = step + 1

            # 将本轮 LLM 回复推送给前端
            if new_reply:
                self._report_agent_progress(ctx, step + 1, max_steps,
                                             tool_names, reply_text=new_reply)

            ctx = await self._dispatch_post_process(ctx)
            if step >= max_steps - 1:
                logger.warning("Agent 达到最大步数 %d", max_steps)

        self._report_agent_progress(ctx, max_steps, max_steps, [], done=True)
        return ctx

    def _print_timing(self, timing: dict[str, float], ctx: PluginContext | None = None):
        # log timing breakdown for each pipeline stage
        if not _TIMER_ENABLED:
            return
        total = timing.get("total_ms", 0)
        stages = [
            ("pre_filter",   "PRE_FILTER"),
            ("pre_process",  "PRE_PROCESS"),
            ("model_invoke", "MODEL_INVOKE"),
            ("post_process", "POST_PROCESS"),
            ("agent_loop",   "Agent Loop"),
            ("post_tts",     "POST_TTS"),
        ]
        logger.info("═════ Pipeline 计时 ═════ total=%.0fms", total)
        for key, label in stages:
            ms = timing.get(key)
            if ms is not None:
                pct = ms / total * 100 if total > 0 else 0
                logger.info("  %-15s %8.0fms  (%5.1f%%)", label, ms, pct)
        if ctx is not None:
            pt = ctx.extra.get("_plugin_timings", {})
            if pt:
                logger.info("─────────────────────────────────")
                for hook_val, plugins in pt.items():
                    for name, ms in plugins:
                        logger.info("    ↳ %-30s %8.0fms", name, ms)
        logger.info("═══════════════════════════════")

    def _print_plugin_timing(self, timing: dict[str, float]):
        # log per-plugin timing breakdown
        pt = timing.get("_plugin_timings", {})
        if not pt:
            return
        for hook_val, plugins in pt.items():
            for name, ms in plugins:
                logger.info("    ↳ %-30s %8.0fms", name, ms)

    @staticmethod
    def _format_tag_results(results: list[dict]) -> str:
        lines: list[str] = []
        for r in results:
            tag = r.get("tag", "?")
            success = "✅" if r.get("success") else "❌"
            data = r.get("data")
            if data is not None:
                snippet = json.dumps(data, ensure_ascii=False, indent=2, default=str)
                if len(snippet) > 1500:
                    keys = list(data.keys()) if isinstance(data, dict) else []
                    snippet = snippet[:1500] + f"\n  ...(已截断, keys={keys})"
                lines.append(f"{success} {tag}\n{snippet}")
            else:
                summary = r.get("summary", "")
                lines.append(f"{success} {tag} {summary}")
            if not r.get("success") and r.get("error"):
        # format tool tag execution results into a string
                lines.append(f"  错误: {r['error']}")
        return "\n".join(lines)

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
        """返回完整列表（兼容同步 process() 用）。"""
        from utils.text_clean import clean_tts_text
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._synthesize_lines_sync, clean_tts_text(text), None, None
        )

    async def _synthesize_lines_stream(
        self, text: str, tts_q: asyncio.Queue
    ) -> list[dict]:
        """每合完一行推入 asyncio.Queue，返回完整列表。"""
        from utils.text_clean import clean_tts_text
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._synthesize_lines_sync, clean_tts_text(text), tts_q, loop
        )

    def _synthesize_lines_sync(
        self, text: str,
        tts_q: asyncio.Queue | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> list[dict]:
        """同步按行合成 TTS（在 executor 线程中运行）。

        若 tts_q 非 None，每行合完后推入 asyncio.Queue 供流式消费。
        """
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
            if tts_q is not None and loop is not None:
                asyncio.run_coroutine_threadsafe(tts_q.put(None), loop)
            return []

        results = []
        total = len(lines)
        logger.info("[TTS-DEBUG] ===== _synthesize_lines_sync 开始, total=%d 行, t=%.3f =====", total, time.perf_counter())
        for i, line in enumerate(lines):
            logger.info("[TTS-DEBUG] TTS 行 %d/%d: 开始合成, 文本前40字=%r, t=%.3f", i + 1, total, line[:40], time.perf_counter())
            t_tts_start = time.perf_counter()
            try:
                processed_line = line
                if self._tts_process_model is not None:
                    fast_first = False
                    try:
                        fast_first = bool(Config.TTS_FAST_FIRST_LINE)
                    except Exception:
                        fast_first = True
                    if fast_first and tts_q is not None and i == 0:
                        local = getattr(self._tts_process_model, "_local_preprocess", None)
                        processed_line = local(line) if callable(local) else line
                        logger.info("[TTS-DEBUG] TTS 行 %d/%d: 使用 local_preprocess 快路径, t=%.3f", i + 1, total, time.perf_counter())
                    else:
                        processed_line = self._tts_process_model.process_tts_text(line)
                        logger.info("[TTS-DEBUG] TTS 行 %d/%d: 使用 process_tts_text (可能 LLM), t=%.3f", i + 1, total, time.perf_counter())
                params = self._tts_profile_mgr.build_params(processed_line) if self._tts_profile_mgr else {
                    "text": processed_line, "text_lang": "zh",
                    "ref_audio_path": "", "prompt_lang": "en", "prompt_text": "",
                    "media_type": "wav", "streaming_mode": False,
                }
                logger.info("[TTS-DEBUG] TTS 行 %d/%d: 调用 tts_client.tts(), t=%.3f", i + 1, total, time.perf_counter())
                audio_bytes = self._tts_client.tts(**params)
                logger.info("[TTS-DEBUG] TTS 行 %d/%d: tts_client 返回 (len=%d), 耗时 %.1fms, t=%.3f", i + 1, total, len(audio_bytes), (time.perf_counter() - t_tts_start) * 1000, time.perf_counter())
                audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
                result = {
                    "index": i,
                    "total": total,
                    "text": line,
                    "audio_b64": audio_b64,
                    "audio_bytes": audio_bytes,
                }
                results.append(result)
                logger.info("[TTS-DEBUG] TTS 行 %d/%d: base64 编码完成, t=%.3f", i + 1, total, time.perf_counter())
            except Exception as e:
                logger.warning("TTS 行 %d 合成失败: %s", i + 1, e)
                result = {
                    "index": i,
                    "total": total,
                    "text": line,
                    "audio_b64": None,
                    "audio_bytes": None,
                }
                results.append(result)

            # 流式推送：每行合完立即入队
            if tts_q is not None and loop is not None:
                logger.info("[TTS-DEBUG] TTS 行 %d/%d: 推入 tts_q (asyncio.run_coroutine_threadsafe), t=%.3f", i + 1, total, time.perf_counter())
                asyncio.run_coroutine_threadsafe(tts_q.put(result), loop)

        if tts_q is not None and loop is not None:
            logger.info("[TTS-DEBUG] TTS 全部完成, 推入 None 哨兵到 tts_q, t=%.3f", time.perf_counter())
            asyncio.run_coroutine_threadsafe(tts_q.put(None), loop)

        logger.info("[TTS-DEBUG] ===== _synthesize_lines_sync 结束: %d/%d 行成功, t=%.3f =====",
                     sum(1 for r in results if r.get("audio_b64")), len(results), time.perf_counter())
        return results

    @staticmethod
    async def _bridge_progress(thread_q: queue.Queue, progress_q: asyncio.Queue):
        # bridge progress events from thread queue to async queue
        loop = asyncio.get_event_loop()
        while True:
            evt = await loop.run_in_executor(None, thread_q.get)
            if evt is None:
                break
            await progress_q.put(evt)

    async def _run_all_plugins(self, enabled: list, hook: HookPoint,
                                ctx: PluginContext, progress_q: asyncio.Queue):
        # run all enabled plugins for a given hook with progress reporting
        for plugin in enabled:
            desc = getattr(plugin, 'description', plugin.name)
            await progress_q.put({"status": "thinking", "text": desc, "plugin": plugin.name})
            t0 = time.perf_counter()
            try:
                ctx = await self.pm._call_plugin(plugin, hook, ctx)
            except Exception:
                logger.exception("插件 %s 在钩子 %s 中抛出异常", plugin.name, hook.value)
            elapsed = round((time.perf_counter() - t0) * 1000, 1)
            pt = ctx.extra.get("_plugin_timings")
            if pt is not None:
                pt.setdefault(hook.value, []).append((plugin.name, elapsed))
            if _TIMER_ENABLED:
                logger.info("  ⏱   └─ %-17s %8.0fms", plugin.name, elapsed)
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
        """Agent 任务循环：轮询任务完成 → 喂回主模型 → 解析新任务 → 重复，最多 N 步"""
        from tasks import TaskStatus, TaskType
        max_steps = ctx.agent_max_steps or Config.AGENT_MAX_STEPS
        task_mgr = ctx.extra.get("_task_manager")
        # 收集本轮所有任务结果
        all_results: dict[str, dict] = {}

        # 获取 TaskPlugin 实例用于创建新任务
        task_plugin = None
        pm = ctx.extra.get("_plugin_manager")
        if pm:
            for p in pm.get_hooks_for(HookPoint.POST_PROCESS):
                if p.__class__.__name__ == 'TaskPlugin':
                    task_plugin = p
                    break

        # 构造基础消息（对话上下文）
        from datetime import datetime
        msgs = [{"role": "system", "content": ctx.system_prompt}]
        msgs.extend(ctx.full_history)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msgs.append({"role": "user", "content": f"[{now}] {ctx.message}"})
        msgs.append({"role": "assistant", "content": ctx.original_reply})

        step = 0
        for step in range(max_steps):
            if not remaining:
                break

            # ── 等待本轮所有任务完成 ──
            deadline = time.time() + 120
            await progress_q.put({
                "status": "thinking",
                "text": f"等待 {len(remaining)} 个任务完成... (第{step+1}/{max_steps}步)",
            })
            while remaining and time.time() < deadline:
                for tid in list(remaining):
                    task = task_mgr.get_task(tid) if task_mgr else None
                    if task and task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                        remaining.discard(tid)
                        task.handled_by_pipeline = True
                        result = task.result or {}
                        success = result.get("success", False) if isinstance(result, dict) else False
                        output = result.get("output", "") if isinstance(result, dict) else ""
                        error = task.error or result.get("error", "") if isinstance(result, dict) else ""
                        # 保存结果供后续 LLM 调用
                        all_results[tid] = {"success": success, "output": output, "error": error}
                        # 发送 task_result SSE 事件
                        evt = {"status": "task_result", "task_id": tid[:8], "success": success}
                        if output:
                            out = str(output).strip()
                            if len(out) > 2000:
                                out = out[:2000] + "\n...(输出截断)"
                            evt["output"] = out
                        if error:
                            evt["error"] = str(error)[:500]
                        await progress_q.put(evt)
                if remaining:
                    await asyncio.sleep(0.3)

            if not all_results:
                break

            # ── 本轮所有任务已完成，构造结果摘要 ──
            results_lines = []
            for tid, r in all_results.items():
                tag = "成功" if r["success"] else "失败"
                out = (r["output"] or "")[:500]
                err = (r["error"] or "")[:500]
                results_lines.append(f"任务 {tid[:8]} [{tag}]\n输出: {out}\n错误: {err}")
            results_text = "\n---\n".join(results_lines)

            # ── 把结果摘要加到消息列表，调用主模型 ──
            msgs.append({"role": "user", "content": f"[异步任务结果]\n{results_text}"})
            reply = await _call_llm_with_msgs(ctx, msgs)
            if not reply:
                break

            # ── 解析回复中是否有新任务 ──
            from plugins.builtin.task_plugin import TaskPlugin
            new_task_datas = TaskPlugin._parse_tasks(reply)

            if not new_task_datas:
                # AI 决定直接回复用户 → 清理标签后设为最终 ctx.reply
                import re as _re
                clean = _re.sub(r"<[^>]+>", "", reply).strip()
                ctx.reply = clean if clean else "…"
                ctx.extra["_agent_reply_dirty"] = True
                logger.info("[Agent任务循环] 第%d步: 无新任务,回复用户", step + 1)
                return

            # ── AI 生成了新任务（修复重试 / 连锁操作）→ 把本轮回复记入历史，创建任务 ──
            msgs.append({"role": "assistant", "content": reply})
            await progress_q.put({
                "status": "thinking",
                "text": f"第{step+1}步完成, 开始执行 {len(new_task_datas)} 个新任务...",
            })
            for td in new_task_datas:
                tid = None
                if task_plugin:
                    tid = task_plugin._handle_task(td, ctx)
                elif task_mgr:
                    task_type = td.get("type")
                    params = td.get("params", {})
                    if task_type == "action":
                        if "action_type" not in params:
                            params["action_type"] = "shell"
                        tid = task_mgr.create_task(
                            task_type=TaskType.ACTION,
                            user_id=ctx.user_id, chat_id=ctx.chat_id,
                            params=params, priority=1,
                        )
                        task_mgr.execute_task(tid)
                if tid:
                    remaining.add(tid)

        # ── 达到最大步数或意外退出 ──
        if not ctx.reply:
            ctx.reply = "……"
        ctx.extra["_agent_reply_dirty"] = True
        if step >= max_steps - 1:
            logger.warning("Agent 任务循环达到最大步数 %d", max_steps)

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
        if _TIMER_ENABLED:
            ctx.extra["_plugin_timings"] = {}
        tts_lines: list[dict] | None = None
        tts_task = None

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

                # ── v4: 世界激活事件 ──
                if ctx.extra.get("world_activated"):
                    yield f"data: {json.dumps({
                        'status': 'world_activated',
                    })}\n\n"

            elif hook == HookPoint.MODEL_INVOKE:
                if not ctx.skip_model:
                    ctx = await self.pm.dispatch(hook, ctx)
                if ctx.filtered:
                    timing[hook.value] = round((time.perf_counter() - t0) * 1000)
                    _log_stage_timing(hook.value, timing[hook.value])
                    timing["total_ms"] = round((time.perf_counter() - t_total) * 1000)
                    self._print_timing(timing, ctx)
                    yield f"data: {json.dumps({'status': 'completed', 'reply': ctx.reply, 'chat_id': ctx.chat_id, 'filtered': True, 'timing': timing})}\n\n"
                    return

                # ── 异步工具检测 ──
                if ctx.extra.get("_async_detected") and self._async_store:
                    task_id = await self._run_async_background(ctx)
                    yield f"data: {json.dumps({'status': 'async_task', 'task_id': task_id, 'chat_id': ctx.chat_id})}\n\n"
                    timing[hook.value] = round((time.perf_counter() - t0) * 1000)
                    _log_stage_timing(hook.value, timing[hook.value])
                    timing["total_ms"] = round((time.perf_counter() - t_total) * 1000)
                    self._print_timing(timing, ctx)
                    yield f"data: {json.dumps({'status': 'completed', 'reply': ctx.reply, 'chat_id': ctx.chat_id, 'filtered': True, 'task_id': task_id, 'timing': timing})}\n\n"
                    return

                if ctx.original_reply:
                    if ctx.reply and ctx.reply != "…":
                        logger.info("[SSE-DEBUG] >>> YIELD text_ready (t=%.4f), reply[:60]=%r", time.perf_counter(), ctx.reply[:60])
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
                tts_collected: list[dict] = []
                tts_q: asyncio.Queue | None = None
                tts_streamed = False  # 标记是否已逐行 yield 过

                if ctx.tts_enabled and ctx.reply and self._tts_client:
                    tts_q = asyncio.Queue()
                    tts_task = asyncio.create_task(
                        self._synthesize_lines_stream(ctx.reply, tts_q)
                    )
                    tts_streamed = True

                plugins = self.pm.get_hooks_for(HookPoint.POST_PROCESS)
                enabled = [p for p in plugins if self.pm.is_enabled(p.name)]

                progress_q: asyncio.Queue = asyncio.Queue()
                thread_q = queue.Queue()
                ctx.extra["_progress_queue"] = thread_q
                ctx.extra["_plugin_manager"] = self.pm

                bridge_task = asyncio.create_task(self._bridge_progress(thread_q, progress_q))
                runner = asyncio.create_task(self._run_all_plugins(enabled, hook, ctx, progress_q))

                import asyncio as _asyncio
                plugins_done = False
                tts_done = tts_q is None  # TTS 未启用则直接标记完成
                while True:
                    # 消费进度事件
                    try:
                        evt = await _asyncio.wait_for(progress_q.get(), timeout=0.1)
                        if evt is None:
                            plugins_done = True
                        else:
                            yield f"data: {json.dumps(evt)}\n\n"
                    except _asyncio.TimeoutError:
                        yield f"data: {json.dumps({
                            'status': 'thinking',
                            'text': '正在处理...',
                        })}\n\n"

                    # 消费 TTS 流式队列：每行合完立即 yield
                    if tts_q is not None:
                        try:
                            while True:
                                line = tts_q.get_nowait()
                                if line is None:
                                    tts_done = True
                                    logger.info("[SSE-DEBUG] tts_q 收到 None 哨兵, tts_done=True, t=%.4f", time.perf_counter())
                                else:
                                    tts_collected.append(line)
                                    logger.info("[SSE-DEBUG] >>> YIELD line %d/%d (t=%.4f), 文本=%r", line['index'] + 1, line['total'], time.perf_counter(), line['text'][:40])
                                    yield f"data: {json.dumps({
                                        'status': 'line',
                                        'index': line['index'],
                                        'total': line['total'],
                                        'text': line['text'],
                                        'audio_b64': line['audio_b64'],
                                    })}\n\n"
                        except _asyncio.QueueEmpty:
                            pass

                    if plugins_done and tts_done:
                        logger.info("[SSE-DEBUG] POST_PROCESS 循环退出: plugins_done=%s tts_done=%s, t=%.4f", plugins_done, tts_done, time.perf_counter())
                        break

                await runner
                await bridge_task

                # ── Agent 循环（streaming + 实时进度）──
                tag_results = ctx.extra.get("_tag_results")
                logger.info("Agent 循环检查: agent_active=%s tag_results=%s",
                            ctx.agent_active, bool(tag_results))
                if ctx.agent_active and tag_results:
                    yield f"data: {json.dumps({
                        'status': 'thinking',
                        'text': 'Agent 循环: 处理执行结果...',
                    })}\n\n"

                    agent_thread_q = queue.Queue()
                    ctx.extra["_agent_progress_queue"] = agent_thread_q

                    async def _consume_agent_progress(tq: queue.Queue,
                                                       apq: asyncio.Queue):
                        # bridge agent progress from thread queue to async queue
                        loop = asyncio.get_event_loop()
                        while True:
                            evt = await loop.run_in_executor(None, tq.get)
                            if evt is None:
                                break
                            await apq.put(evt)

                    agent_progress_q: asyncio.Queue = asyncio.Queue()
                    agent_bridge = asyncio.create_task(
                        _consume_agent_progress(agent_thread_q, agent_progress_q))
                    agent_task = asyncio.create_task(self._run_agent_loop(ctx))

                    agent_tts_q: asyncio.Queue | None = None

                    async def _drain_q():
                        """排空 TTS 队列，逐行 yield 到前端。"""
                        nonlocal agent_tts_q
                        if agent_tts_q is None:
                            return
                        try:
                            while True:
                                line = agent_tts_q.get_nowait()
                                if line is None:
                                    agent_tts_q = None
                                    break
                                else:
                                    logger.info("[SSE-DEBUG] >>> YIELD line %d/%d (Agent stream), t=%.4f", line['index'] + 1, line['total'], time.perf_counter())
                                    yield f"data: {json.dumps({
                                        'status': 'line',
                                        'index': line['index'],
                                        'total': line['total'],
                                        'text': line['text'],
                                        'audio_b64': line['audio_b64'],
                                    })}\n\n"
                        except asyncio.QueueEmpty:
                            pass

                    while True:
                        try:
                            evt = await asyncio.wait_for(
                                agent_progress_q.get(), timeout=0.3)
                            if evt is None:
                                break
                            # 先 yield 进度文本（前端显示步骤信息）
                            yield f"data: {json.dumps(evt)}\n\n"
                            # 如果本轮 LLM 有回复，立即 yield text_ready + 异步 TTS（流式）
                            reply = evt.get("reply")
                            if reply and reply != "…":
                                yield f"data: {json.dumps({
                                    'status': 'text_ready',
                                    'reply': reply,
                                    'chat_id': ctx.chat_id,
                                })}\n\n"
                                if ctx.tts_enabled and self._tts_client:
                                    # 排空旧 TTS 队列（如果有未完成的前一轮合成）
                                    if agent_tts_q is not None:
                                        async for ev in _drain_q():
                                            yield ev
                                    agent_tts_q = asyncio.Queue()
                                    asyncio.create_task(
                                        self._synthesize_lines_stream(reply, agent_tts_q))

                            # 消费 TTS 流式队列：每行合完立即 yield
                            async for ev in _drain_q():
                                yield ev

                        except asyncio.TimeoutError:
                            if agent_task.done():
                                break
                            # 保持连接活跃
                            yield f"data: {json.dumps({
                                'status': 'thinking',
                                'text': 'Agent 正在执行...',
                            })}\n\n"
                            # 消费 TTS 流式队列
                            async for ev in _drain_q():
                                yield ev

                    # Agent 循环结束，阻塞等待 TTS 流式队列排空（TTS 可能仍在合成）
                    agent_tts_collected: list[dict] = []
                    if agent_tts_q is not None:
                        while True:
                            try:
                                line = await asyncio.wait_for(agent_tts_q.get(), timeout=0.5)
                                if line is None:
                                    break
                                agent_tts_collected.append(line)
                                logger.info("[SSE-DEBUG] >>> YIELD line %d/%d (Agent post drain), t=%.4f", line['index'] + 1, line['total'], time.perf_counter())
                                yield f"data: {json.dumps({
                                    'status': 'line',
                                    'index': line['index'],
                                    'total': line['total'],
                                    'text': line['text'],
                                    'audio_b64': line['audio_b64'],
                                })}\n\n"
                            except asyncio.TimeoutError:
                                yield f"data: {json.dumps({
                                    'status': 'thinking',
                                    'text': '音频合成中...',
                                })}\n\n"

                    ctx = await agent_task
                    await agent_bridge
                    ctx.extra["_agent_progress_queue"] = False  # 标记已 streamed
                    # 将 Agent TTS 结果注入 tts_lines，阻止 POST_TTS 重复合成
                    if agent_tts_collected:
                        tts_collected = agent_tts_collected
                        tts_streamed = True
                        ctx.extra["_agent_tts_done"] = True
                    if ctx.reply and ctx.reply != "…":
                        ctx.extra["_agent_reply_dirty"] = True

                tts_lines = tts_collected if tts_collected else None
                if tts_task:
                    await tts_task

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
                    # 如果 Agent 循环中已经按步骤 streamed 过 text_ready + TTS，
                    # 此处不再重复推送，避免重复音频
                    has_agent_reply = ctx.extra.get("_agent_progress_queue") is False
                    if not has_agent_reply:
                        yield f"data: {json.dumps({
                            'status': 'text_ready',
                            'reply': ctx.reply,
                            'chat_id': ctx.chat_id,
                        })}\n\n"
                        logger.info("[text_ready:agent_dirty] reply=%s", ctx.reply[:60])
                        if ctx.tts_enabled and self._tts_client and ctx.extra.get("_agent_step", 0) > 0:
                            tts_lines = await self._synthesize_lines(ctx.reply)
                            tts_streamed = False
                    ctx.extra["_agent_reply_dirty"] = False

            elif hook == HookPoint.POST_TTS:
                if tts_lines is not None:
                    if not tts_streamed:
                        # 非流式模式（agent_dirty 重合成）：逐行 yield
                        for line in tts_lines:
                            yield f"data: {json.dumps({
                                'status': 'line',
                                'index': line['index'],
                                'total': line['total'],
                                'text': line['text'],
                                'audio_b64': line['audio_b64'],
                            })}\n\n"
                    # 组装完整的 ctx.audio（正确拼接多段 WAV）
                    if tts_lines:
                        all_audio = self._concat_wav(
                            [l["audio_bytes"] for l in tts_lines if l.get("audio_bytes")]
                        )
                        if all_audio:
                            import base64
                            ctx.audio = all_audio
                            ctx.audio_b64 = base64.b64encode(all_audio).decode("utf-8")
                else:
                    ctx = await self.pm.dispatch(hook, ctx)

            timing[hook.value] = round((time.perf_counter() - t0) * 1000)
            _log_stage_timing(hook.value, timing[hook.value])

            if on_phase:
                try:
                    await on_phase(hook.value, ctx)
                except Exception:
                    logger.exception("on_phase 回调异常")

            if ctx.filtered:
                timing["total_ms"] = round((time.perf_counter() - t_total) * 1000)
                self._print_timing(timing, ctx)
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
        self._print_timing(timing, ctx)
        completed = {
            'status': 'completed',
            'audio': ctx.audio_b64,
            'tts_error': ctx.tts_error,
            'timing': timing,
        }
        logger.info("[SSE-DEBUG] >>> YIELD completed (t=%.4f), total_ms=%.0f", time.perf_counter(), timing.get("total_ms", 0))
        if ctx.extra.get("confirm_requested"):
            completed["confirm_requested"] = True
        if ctx.extra.get("world_activated"):
            completed["world_activated"] = True
        if ctx.usage:
            completed['usage'] = ctx.usage
            completed['model_name'] = ctx.model_name
        yield f"data: {json.dumps(completed)}\n\n"
