# harness/agent/loop.py
# AgentLoop — 通用 Agent 循环。
#
# 流程:
#   for step in range(max_steps):
#       回复 = model.invoke(messages, tools)
#       解析出 (文本, 工具调用)
#       若无工具调用 → 返回最终回复
#       执行工具 → 组装下一轮消息 → 继续
#
# 完全场景无关：只依赖 IChatClient + ToolRegistry + ToolCallAdapter。

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Optional

from ..models.base import ChatMessage, ChatResponse, IChatClient, ToolCall
from ..tools import ToolRegistry, ToolResult
from .adapters import ToolCallAdapter, NativeToolCallAdapter

logger = logging.getLogger("harness.agent")


@dataclass
class StreamEvent:
    """流式执行事件（AgentLoop.run_stream 产出）。

    kind:
      round_start  新一轮开始（round 从 1 起）
      delta        模型文本增量（content）
      tool_call    模型请求执行某工具（tool_call: {id, name, arguments}）
      tool_result  工具执行结果（tool_result: {call_id, name, success, output, error}）
      reply        最终回复（无更多工具调用时）
      done         执行结束（reply 为最终文本）
    """

    kind: str
    round: int = 0
    content: str = ""
    tool_call: Optional[dict] = None
    tool_result: Optional[dict] = None
    reply: str = ""
    hit_max: bool = False


@dataclass
class ToolExecution:
    call_id: str
    name: str
    arguments: dict
    result: ToolResult


@dataclass
class AgentRunResult:
    reply: str = ""
    tool_executions: list[ToolExecution] = field(default_factory=list)
    steps: int = 0
    hit_max_steps: bool = False


@dataclass
class RoundResult:
    """轮次策略结果（run_rounds 模式）。

    round_runner 每轮返回它，驱动循环骨架的继续/终止语义。
    """

    continue_loop: bool = True       # False → 终止循环（reply 作为最终回复）
    reply: str = ""                  # 最终回复（continue_loop=False 时有效）
    hit_max: bool = False            # 是否因达到步数上限终止（供上层兜底）
    state: Any = None                # 可选的跨轮状态传递


class AgentLoop:
    """执行 模型 → 工具 → 回喂 的循环，直到模型给出最终答复或达到步数上限。

    run_async / run  : 原生路径（模型返回工具调用 → 经 ToolRegistry 执行 → 回喂）。
    run_rounds       : 通用循环骨架（超集）——由应用提供每轮策略 round_runner，
                       骨架负责步数迭代 / 上限 / on_progress 生命周期。
                       DSN 引擎的 Agent 循环即以此方式驱动（见 apps.dsn.plugins.pipeline）。
    """

    def __init__(
        self,
        client: Optional[IChatClient] = None,
        tools: Optional[ToolRegistry] = None,
        adapter: Optional[ToolCallAdapter] = None,
        *,
        max_steps: int = 8,
        on_progress: Optional[Callable[[int, int, list[str]], None]] = None,
        on_tool_error: Optional[Callable[[str, str], None]] = None,
        toolbox: Optional[Any] = None,
    ):
        # client/tools 在原生路径（run_async）必需；run_rounds 轮次策略模式可缺省
        self.client = client
        self.tools = tools
        self.adapter = adapter or NativeToolCallAdapter()
        self.max_steps = max_steps
        self.on_progress = on_progress
        self.on_tool_error = on_tool_error
        # 两阶段工具激活策略（ToolboxManager 或同构对象；None = 不启用）
        self.toolbox = toolbox

    def run(
        self,
        messages: list[ChatMessage],
        *,
        tool_names: Optional[list[str]] = None,
        system_prompt: str = "",
    ) -> AgentRunResult:
        """同步执行。返回最终回复与工具执行记录。"""
        return asyncio.run(self.run_async(messages, tool_names=tool_names,
                                          system_prompt=system_prompt))

    async def run_async(
        self,
        messages: list[ChatMessage],
        *,
        tool_names: Optional[list[str]] = None,
        system_prompt: str = "",
    ) -> AgentRunResult:
        msgs: list[ChatMessage] = []
        if system_prompt:
            msgs.append(ChatMessage.system(system_prompt))
        msgs.extend(list(messages))

        if self.toolbox is not None and self.toolbox.enabled:
            # 工具箱模式：schema 按激活状态构建（首轮仅索引工具）
            schema = self.toolbox.build_schema(self.toolbox.activated)
        elif self.tools is None:
            schema = []
        else:
            schema = self.adapter.build_tools_schema(self.tools) if tool_names is None \
                else [self.tools.require(n).to_openai_schema() for n in tool_names]

        executions: list[ToolExecution] = []
        final_reply = ""
        hit_max = False

        for step in range(self.max_steps):
            if self.on_progress:
                self.on_progress(step, self.max_steps, [])

            # 工具箱模式：每轮刷新 schema（激活状态可能在本轮发生变化）
            if self.toolbox is not None and self.toolbox.enabled:
                schema = self.toolbox.build_schema(self.toolbox.activated)

            response = await self._invoke(msgs, schema)
            parsed = self.adapter.parse(response)

            if not parsed.tool_calls:
                final_reply = parsed.text or response.content
                break

            # 工具箱模式：分离 toolbox 索引调用（激活确认），其余照常执行
            toolbox_results: list[dict] = []
            if self.toolbox is not None and self.toolbox.enabled:
                parsed.tool_calls, toolbox_results = self.toolbox.handle_calls(parsed.tool_calls)

            names = [tc.name for tc in parsed.tool_calls]
            if self.on_progress:
                self.on_progress(step + 1, self.max_steps, names)

            results: list[dict] = []
            for tc in parsed.tool_calls:
                tool = self.tools.get(tc.name)
                if tool is None:
                    result = ToolResult.fail(f"工具不存在: {tc.name}")
                else:
                    result = await tool.run_async(**tc.arguments)
                if not result.success and self.on_tool_error:
                    self.on_tool_error(tc.name, result.error or "")
                executions.append(ToolExecution(
                    call_id=tc.id, name=tc.name, arguments=tc.arguments, result=result))
                results.append({
                    "call_id": tc.id,
                    "name": tc.name,
                    "success": result.success,
                    "status": result.status,
                    "output": result.output,
                    "error": result.error,
                    "hint": result.hint,
                })

            # 合并 toolbox 确认结果（assistant 消息含 toolbox tool_calls，配对正确）
            msgs.extend(self.adapter.build_round(response, toolbox_results + results))

            if step >= self.max_steps - 1:
                hit_max = True
                final_reply = parsed.text or ""
                break

        return AgentRunResult(
            reply=final_reply,
            tool_executions=executions,
            steps=min(self.max_steps, len(executions) + 1),
            hit_max_steps=hit_max,
        )

    async def run_rounds(
        self,
        round_runner: Callable[[Any, int, int], Any],
        state: Any = None,
    ) -> RoundResult:
        """按 round_runner 轮次策略驱动的通用循环骨架（超集能力）。

        round_runner: async (state, step, max_steps) -> RoundResult
          - 骨架负责：步数迭代、max_steps 上限、on_progress 生命周期；
          - 策略负责：单轮的"调模型 → 执行工具 → 组装下一轮消息"语义；
          - 原生路径（run_async）行为不受影响，二者可并存。
        """
        outcome = RoundResult(state=state)
        for step in range(self.max_steps):
            if self.on_progress:
                self.on_progress(step, self.max_steps, [])
            outcome = await round_runner(state, step, self.max_steps)
            if not outcome.continue_loop:
                break
        if self.on_progress:
            self.on_progress(self.max_steps, self.max_steps, [])
        return outcome

    # ── 流式执行（含流式工具调用） ──

    async def run_stream(
        self,
        messages: list[ChatMessage],
        *,
        tool_names: Optional[list[str]] = None,
        system_prompt: str = "",
    ) -> AsyncGenerator[StreamEvent, None]:
        """流式执行：文本增量实时产出，工具调用自动执行并继续下一轮。

        与 run_async 等价语义，但每轮模型调用走 IChatClient.stream：
          - 文本增量 yield StreamEvent(kind="delta")
          - 流中累积 tool_calls（OpenAI delta 协议，按 index 合并）
          - 工具执行 yield tool_call / tool_result，结果回喂后进入下一轮
          - toolbox 两阶段激活在流式路径同样生效
        客户端未实现 stream 时自动回退 invoke（整体作为单个 delta 产出）。
        """
        msgs: list[ChatMessage] = []
        if system_prompt:
            msgs.append(ChatMessage.system(system_prompt))
        msgs.extend(list(messages))

        if self.toolbox is not None and self.toolbox.enabled:
            schema = self.toolbox.build_schema(self.toolbox.activated)
        elif self.tools is None:
            schema = []
        else:
            schema = self.adapter.build_tools_schema(self.tools) if tool_names is None \
                else [self.tools.require(n).to_openai_schema() for n in tool_names]

        final_reply = ""
        hit_max = False

        for step in range(self.max_steps):
            yield StreamEvent(kind="round_start", round=step + 1)
            if self.toolbox is not None and self.toolbox.enabled:
                schema = self.toolbox.build_schema(self.toolbox.activated)

            # 1) 流式调用模型（无 stream 时回退 invoke）
            content_parts: list[str] = []
            tool_deltas: dict[int, dict] = {}
            stream_fn = getattr(self.client, "stream", None)
            if stream_fn is not None:
                async for chunk in self._stream_or_invoke(msgs, schema, stream_fn):
                    if isinstance(chunk, str):
                        content_parts.append(chunk)
                        yield StreamEvent(kind="delta", content=chunk, round=step + 1)
                    elif isinstance(chunk, dict):
                        for item in chunk.get("tool_calls", []) or []:
                            idx = item.get("index", 0)
                            acc = tool_deltas.setdefault(idx, {})
                            acc["id"] = item.get("id") or acc.get("id", "")
                            acc["name"] = item.get("name") or acc.get("name", "")
                            acc["arguments"] = (acc.get("arguments", "")
                                                + (item.get("arguments") or ""))
            else:
                response = await self._invoke(msgs, schema)
                if response.content:
                    content_parts.append(response.content)
                    yield StreamEvent(kind="delta", content=response.content,
                                      round=step + 1)
                for tc in response.tool_calls:
                    tool_deltas[tool_deltas.__len__()] = {
                        "id": tc.id, "name": tc.name, "arguments": tc.arguments}

            content = "".join(content_parts)
            tool_calls: list[ToolCall] = []
            for idx in sorted(tool_deltas):
                d = tool_deltas[idx]
                try:
                    args = json.loads(d.get("arguments") or "{}")
                except (TypeError, ValueError):
                    args = {}
                tool_calls.append(ToolCall(
                    id=d.get("id") or f"stream-{idx}",
                    name=d.get("name") or "unknown",
                    arguments=args))

            # 2) toolbox 分离（激活确认）
            had_any_calls = bool(tool_calls)
            toolbox_results: list[dict] = []
            if self.toolbox is not None and self.toolbox.enabled:
                tool_calls, toolbox_results = self.toolbox.handle_calls(tool_calls)

            # 没有任何调用（含 toolbox 激活）→ 本轮即最终回复
            if not had_any_calls:
                final_reply = content or "…"
                yield StreamEvent(kind="reply", reply=final_reply, round=step + 1)
                break

            # 3) 执行真实工具（toolbox 激活轮无真实工具时仅回喂确认消息）
            results: list[dict] = []
            for tc in tool_calls:
                yield StreamEvent(kind="tool_call", round=step + 1,
                                  tool_call={"id": tc.id, "name": tc.name,
                                             "arguments": tc.arguments})
                if self.tools is None:
                    result = ToolResult.fail("无工具注册表")
                else:
                    tool = self.tools.get(tc.name)
                    result = (ToolResult.fail(f"工具不存在: {tc.name}")
                              if tool is None else await tool.run_async(**tc.arguments))
                if not result.success and self.on_tool_error:
                    self.on_tool_error(tc.name, result.error or "")
                results.append({
                    "call_id": tc.id, "name": tc.name, "success": result.success,
                    "output": result.output, "error": result.error,
                })
                yield StreamEvent(kind="tool_result", round=step + 1,
                                  tool_result=results[-1])

            # 4) 回喂下一轮
            response = ChatResponse(content=content, tool_calls=tool_calls)
            msgs.extend(self.adapter.build_round(response, toolbox_results + results))

            if step >= self.max_steps - 1:
                hit_max = True
                final_reply = content or "…"
                break

        yield StreamEvent(kind="done", reply=final_reply, hit_max=hit_max,
                          round=self.max_steps)

    async def _stream_or_invoke(self, msgs, schema, stream_fn):
        """把 client.stream 的同步/异步生成器统一为 async 迭代。"""
        import inspect
        if inspect.isasyncgenfunction(stream_fn) or asyncio.iscoroutinefunction(stream_fn):
            # async 生成器 / async 协程（返回可迭代对象）
            async for chunk in stream_fn(msgs, tools=schema):
                yield chunk
        else:
            # 同步生成器 → 线程池
            def _iterate():
                for chunk in stream_fn(msgs, tools=schema):
                    yield chunk
            loop = asyncio.get_event_loop()
            gen = await loop.run_in_executor(None, lambda: list(_iterate()))
            for chunk in gen:
                yield chunk

    async def _invoke(self, msgs: list[ChatMessage],
                      schema: list[dict]) -> ChatResponse:
        import inspect
        if inspect.iscoroutinefunction(self.client.invoke):
            return await self.client.invoke(msgs, tools=schema)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.client.invoke(msgs, tools=schema))
