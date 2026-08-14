# -*- coding: utf-8 -*-
"""dsn Agent 循环迁移等价性测试。

新旧 _run_agent_loop 行为等价性：新实现由 harness AgentLoop.run_rounds
驱动轮次策略（_dsn_agent_round），旧实现（迁移前内联 for 循环）作为回归基线。
本测试用假 ModelsPlugin / PluginManager 覆盖: 原生 tool call 双轮 / XML 标签 /
空结果立即结束 / 超步数兜底汇报 四类场景。
"""
from __future__ import annotations

import asyncio
import copy
import logging
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.pipeline import HookPoint, Context as PluginContext
from apps.dsn.plugins.pipeline import ChatPipeline

# ── 旧实现快照（迁移前） — 回归基线 ──
_LEGACY_SRC = '    async def _run_agent_loop(self, ctx: PluginContext) -> PluginContext:\n        from datetime import datetime\n        max_steps = ctx.agent_max_steps or 5\n        loop = asyncio.get_event_loop()\n        logger.info("_run_agent_loop 启动, max_steps=%d", max_steps)\n\n        models_plugin = None\n        for p in self.pm.get_hooks_for(HookPoint.MODEL_INVOKE):\n            if p.__class__.__name__ == "ModelsPlugin":\n                models_plugin = p\n                break\n\n        self._report_agent_progress(ctx, 0, max_steps, ["开始处理"])\n\n        # 超步数兜底汇报: 记录最后一轮是否仍在执行工具、以及未回喂给 LLM 的工具结果\n        hit_max = False\n        report_tool_calls: list = []\n        report_results: list = []\n\n        for step in range(max_steps):\n            results = ctx.extra.pop("_tag_results", [])\n            if not results:\n                logger.info("Agent 第 %d 步: _tag_results 为空", step + 1)\n                break\n\n            # 提取本次执行了哪些工具，用于进度提示\n            tool_names = []\n            for r in results:\n                func = r.get("function", "")\n                # "skill-document-process_scan" → "process_scan"\n                short = func.rsplit("-", 1)[-1] if "-" in func else func\n                if short:\n                    tool_names.append(short)\n                if not r.get("success"):\n                    self._report_tool_error(\n                        ctx, func or r.get("skill", "") or "tool",\n                        r.get("error") or r.get("summary") or "未知错误")\n\n            # 检测是否为原生 tool call 结果（有 function 和 tool_call_id 字段）\n            has_native_results = any(\n                r.get("function") and r.get("tool_call_id") for r in results\n            )\n\n            if has_native_results and models_plugin:\n                msgs: list[dict] = [{"role": "system", "content": ctx.system_prompt}]\n                msgs.extend(ctx.full_history)\n                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")\n                msgs.append({"role": "user", "content": f"[{now}] {ctx.message}"})\n\n                # assistant 消息必须携带 tool_calls（对应后续 tool role 消息）\n                last_tool_calls = ctx.extra.pop("_last_tool_calls", [])\n                assistant_msg = {"role": "assistant",\n                                 "content": ctx.original_reply or ctx.reply}\n                if last_tool_calls:\n                    assistant_msg["tool_calls"] = last_tool_calls\n                msgs.append(assistant_msg)\n\n                for r in results:\n                    content = json.dumps(r.get("data", r.get("error", "")),\n                                         ensure_ascii=False, default=str)\n                    msgs.append({\n                        "role": "tool",\n                        "tool_call_id": r.get("tool_call_id", "unknown"),\n                        "content": content,\n                    })\n\n                tools_schema = None\n                if hasattr(models_plugin, \'_build_tools_schema\'):\n                    activated = ctx.extra.get("_activated_tools", None)\n                    tools_schema = models_plugin._build_tools_schema(activated)\n\n                self._report_agent_progress(ctx, step + 1, max_steps, tool_names)\n\n                try:\n                    new_reply = await loop.run_in_executor(\n                        None, lambda: models_plugin.invoke(msgs, ctx, tools=tools_schema)\n                    )\n                except Exception as e:\n                    logger.error("Agent 第 %d 步(native): invoke 失败: %s", step + 1, e)\n                    break\n                if not new_reply:\n                    has_pending = bool(ctx.extra.get("_native_tool_calls", []))\n                    has_pending_toolbox = bool(ctx.extra.get("_tag_results", []))\n                    if not has_pending and not has_pending_toolbox:\n                        logger.warning("Agent 第 %d 步(native): LLM 返回空且无待处理 tool_calls，终止",\n                                       step + 1)\n                        break\n                    logger.info("Agent 第 %d 步(native): LLM 返回空但有 %d 个待处理 tool_calls，继续执行",\n                                step + 1, len(ctx.extra.get("_native_tool_calls", [])))\n\n                logger.info("Agent 第 %d 步(native): LLM 回复 %d 字符",\n                            step + 1, len(new_reply or ""))\n                ctx.original_reply = new_reply\n                reply_text = (models_plugin._clean_reply(new_reply)\n                              if new_reply else "…")\n                ctx.reply = reply_text\n                ctx.extra["_agent_step"] = step + 1\n\n                # 将本轮 LLM 回复推送给前端（非空且不是占位符时 TTS 会朗读）\n                if new_reply:\n                    self._report_agent_progress(ctx, step + 1, max_steps,\n                                                 tool_names, reply_text=reply_text)\n\n                ctx = await self._dispatch_post_process(ctx)\n                if step >= max_steps - 1:\n                    hit_max = True\n                    report_tool_calls = last_tool_calls\n                    report_results = ctx.extra.get("_tag_results", [])\n                    logger.warning("Agent 达到最大步数 %d，等待兜底汇报", max_steps)\n                continue\n\n            # 降级模式：传统 XML 标签处理\n            formatted = self._format_tag_results(results)\n            logger.info("Agent 第 %d 步(xml): %d 个标签执行完毕",\n                        step + 1, len(results))\n\n            self._report_agent_progress(ctx, step + 1, max_steps, tool_names)\n\n            msgs: list[dict] = [{"role": "system", "content": ctx.system_prompt}]\n            msgs.extend(ctx.full_history)\n            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")\n            msgs.append({"role": "user", "content": f"[{now}] {ctx.message}"})\n            msgs.append({"role": "assistant", "content": ctx.reply})\n            msgs.append({"role": "user", "content": f"[执行结果]\\n{formatted}"})\n\n            if models_plugin is None:\n                logger.warning("models_plugin 未找到，中断 agent 循环")\n                break\n\n            try:\n                new_reply = await loop.run_in_executor(\n                    None, lambda: models_plugin.invoke(msgs, ctx)\n                )\n            except Exception as e:\n                logger.error("Agent 第 %d 步(xml): invoke 失败: %s", step + 1, e)\n                break\n            if not new_reply:\n                logger.info("Agent 第 %d 步: LLM 返回空", step + 1)\n                break\n\n            logger.info("Agent 第 %d 步(xml): LLM 回复 %d 字符",\n                        step + 1, len(new_reply))\n            ctx.original_reply = new_reply\n            ctx.reply = new_reply\n            ctx.extra["_agent_step"] = step + 1\n\n            # 将本轮 LLM 回复推送给前端\n            if new_reply:\n                self._report_agent_progress(ctx, step + 1, max_steps,\n                                             tool_names, reply_text=new_reply)\n\n            ctx = await self._dispatch_post_process(ctx)\n            if step >= max_steps - 1:\n                hit_max = True\n                report_results = ctx.extra.get("_tag_results", [])\n                logger.warning("Agent 达到最大步数 %d，等待兜底汇报", max_steps)\n\n        # ── 超步数兜底：最后一轮仍在执行工具、且未产出面向用户的文本时，\n        #    追加一轮"汇报"，把已执行的工具结果总结成最终答复，避免无声终止 ──\n        last_text = (ctx.reply or "").strip()\n        need_report = (hit_max and report_results and models_plugin is not None\n                       and (not last_text or last_text == "…"))\n        if need_report:\n            logger.info("Agent 超步数且无最终文本，追加汇报轮 (%d 条工具结果)",\n                        len(report_results))\n            msgs: list[dict] = [{"role": "system", "content": ctx.system_prompt}]\n            msgs.extend(ctx.full_history)\n            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")\n            msgs.append({"role": "user", "content": f"[{now}] {ctx.message}"})\n\n            if report_tool_calls:\n                assistant_msg = {"role": "assistant",\n                                 "content": ctx.original_reply or ctx.reply,\n                                 "tool_calls": report_tool_calls}\n                msgs.append(assistant_msg)\n                for r in report_results:\n                    content = json.dumps(r.get("data", r.get("error", "")),\n                                         ensure_ascii=False, default=str)\n                    msgs.append({\n                        "role": "tool",\n                        "tool_call_id": r.get("tool_call_id", "unknown"),\n                        "content": content,\n                    })\n                msgs.append({"role": "user", "content":\n                             "以上工具调用已全部执行完毕，处理步骤已达上限。"\n                             "请直接基于上述工具结果，向用户给出简洁、完整的最终答复。"\n                             "不要调用任何工具。"})\n            else:\n                formatted = self._format_tag_results(report_results)\n                msgs.append({"role": "assistant", "content": ctx.reply or ctx.original_reply or ""})\n                msgs.append({"role": "user", "content":\n                             f"[执行结果]\\n{formatted}\\n\\n处理步骤已达上限，"\n                             "请基于上述结果直接给出面向用户的最终答复，不要调用工具。"})\n\n            try:\n                report = await loop.run_in_executor(\n                    None, lambda: models_plugin.invoke(msgs, ctx)\n                )\n            except Exception as e:\n                logger.error("Agent 汇报轮 invoke 失败: %s", e)\n                report = ""\n\n            if report:\n                ctx.original_reply = report\n                ctx.reply = models_plugin._clean_reply(report)\n                ctx.extra["_agent_step"] = max_steps + 1\n                self._report_agent_progress(ctx, max_steps + 1, max_steps, [],\n                                            reply_text=ctx.reply)\n                logger.info("Agent 超步数汇报完成: %d 字符", len(report))\n\n        self._report_agent_progress(ctx, max_steps, max_steps, [], done=True)\n        return ctx\n'
ns = {"PluginContext": PluginContext, "HookPoint": HookPoint,
      "asyncio": asyncio, "json": __import__("json"),
      "logger": logging.getLogger("agent-equiv")}
exec(compile(textwrap.dedent(_LEGACY_SRC), "<legacy>", "exec"), ns)


class LegacyPipe(ChatPipeline):
    """仅替换 agent 循环为旧实现的回归基线。"""
    _run_agent_loop = ns["_run_agent_loop"]


class FakeModels:
    """按队列返回回复，可注入原生 tool_calls（类名需为 ModelsPlugin 才能被识别）。"""
    def __init__(self, queue):
        self._q = list(queue)
        self.invoke_calls = []
    def invoke(self, msgs, ctx, tools=None):
        self.invoke_calls.append({"n_msgs": len(msgs), "tools": tools})
        item = self._q.pop(0) if self._q else ""
        if isinstance(item, dict):
            tc = item.get("tool_calls", [])
            if tc:
                ctx.extra["_native_tool_calls"] = tc
                ctx.extra["_last_tool_calls"] = tc
            return item.get("reply", "")
        return item
    def _clean_reply(self, s):
        return s or "…"
    def _build_tools_schema(self, activated=None):
        return [{"type": "function", "function": {"name": "toolbox"}}]


class FakePM:
    """假 PluginManager：MODEL_INVOKE 返回假模型；POST_PROCESS 模拟工具执行。"""
    def __init__(self, models):
        self.models = models
        self.post_calls = 0
    def get_hooks_for(self, hook):
        return [self.models] if hook == HookPoint.MODEL_INVOKE else []
    async def dispatch(self, hook, ctx):
        if hook == HookPoint.POST_PROCESS:
            self.post_calls += 1
            natives = ctx.extra.pop("_native_tool_calls", [])
            results = []
            for tc in natives:
                fname = tc.get("function", {}).get("name", "?")
                results.append({"function": fname, "tool_call_id": tc.get("id"),
                                "success": True, "data": {"r": 1}})
            if results:
                ctx.extra.setdefault("_tag_results", []).extend(results)
        return ctx


def _run(name, replies, pre_extra, agent_max_steps=5):
    """分别用新旧实现跑同一场景，返回 (新结果, 旧结果)。"""
    def build(kind):
        models = FakeModels(replies)
        models.__class__.__name__ = "ModelsPlugin"
        pm = FakePM(models)
        pipe = ChatPipeline(plugin_manager=pm) if kind == "new" else LegacyPipe(plugin_manager=pm)
        ctx = PluginContext(user_id=1, message="测试", chat_id=2,
                            agent_active=True, agent_max_steps=agent_max_steps,
                            system_prompt="sys",
                            full_history=[{"role": "user", "content": "h"}])
        ctx.extra.update(copy.deepcopy(pre_extra))
        return pipe, pm, models, ctx
    outs = {}
    for kind in ("new", "legacy"):
        pipe, pm, models, ctx = build(kind)
        asyncio.run(pipe._run_agent_loop(ctx))
        outs[kind] = {
            "reply": ctx.reply, "original": ctx.original_reply,
            "agent_step": ctx.extra.get("_agent_step"),
            "tag_results": ctx.extra.get("_tag_results", []),
            "invoke_calls": len(models.invoke_calls),
            "post_calls": pm.post_calls,
            "hit_max": ctx.extra.get("_agent_hit_max", False),
        }
    return outs


def _assert_equivalent(name, outs):
    """断言新旧行为等价，返回 (new_hit_max, legacy_hit_max)。"""
    new_hit = outs["new"].pop("hit_max")
    legacy_hit = outs["legacy"].pop("hit_max")
    assert outs["new"] == outs["legacy"], (name, outs)
    # _agent_hit_max 为新实现新增的信息标记（legacy 不外露）
    assert new_hit == legacy_hit or (name.endswith("超步数兜底汇报") and new_hit and not legacy_hit)
    return new_hit, legacy_hit


_NATIVE_TC = [{"id": "call_%d", "type": "function",
               "function": {"name": "math.add", "arguments": "{}"}}]


def test_native_two_round_equivalent():
    tc2 = [{"id": "call_2", "type": "function",
            "function": {"name": "math.add", "arguments": "{}"}}]
    outs = _run("A 原生 2 轮",
        [{"reply": "思考中", "tool_calls": tc2}, "最终答复"],
        {"_tag_results": [{"function": "math.add", "tool_call_id": "call_1",
                           "success": True, "data": {"r": 0}}],
         "_last_tool_calls": [{"id": "call_1", "type": "function",
                               "function": {"name": "math.add", "arguments": "{}"}}]})
    _assert_equivalent("A 原生 2 轮", outs)
    assert outs["new"]["reply"] == "最终答复"
    assert outs["new"]["invoke_calls"] == 2


def test_xml_tag_path_equivalent():
    outs = _run("B XML 标签路径",
        ["第一步思考", "不会用到"],
        {"_tag_results": [{"tag": "tool", "success": True, "data": {"x": 1}}]})
    _assert_equivalent("B XML 标签路径", outs)


def test_empty_results_immediate_stop_equivalent():
    outs = _run("C 空结果立即结束", ["不会调用"], {})
    _assert_equivalent("C 空结果立即结束", outs)
    assert outs["new"]["invoke_calls"] == 0


def test_hit_max_fallback_report_equivalent():
    tc3 = [{"id": "call_3", "type": "function",
            "function": {"name": "math.add", "arguments": "{}"}}]
    outs = _run("D 超步数兜底汇报",
        [{"reply": "思考", "tool_calls": tc3},
         {"reply": "", "tool_calls": tc3},
         "兜底汇报"],
        {"_tag_results": [{"function": "math.add", "tool_call_id": "call_0",
                           "success": True, "data": {"r": 0}}],
         "_last_tool_calls": [{"id": "call_0", "type": "function",
                               "function": {"name": "math.add", "arguments": "{}"}}]},
        agent_max_steps=2)
    new_hit, _ = _assert_equivalent("D 超步数兜底汇报", outs)
    assert outs["new"]["reply"] == "兜底汇报"
    assert outs["new"]["invoke_calls"] == 3
    assert new_hit is True


def test_run_agent_loop_uses_harness_agentloop():
    """dsn agent 循环骨架来自 harness AgentLoop.run_rounds。"""
    import inspect
    src = inspect.getsource(ChatPipeline._run_agent_loop)
    assert "AgentLoop" in src and "run_rounds" in src
    assert "harness" in src
