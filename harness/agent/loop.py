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
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ..models.base import ChatMessage, ChatResponse, IChatClient
from ..tools import ToolRegistry, ToolResult
from .adapters import ToolCallAdapter, NativeToolCallAdapter

logger = logging.getLogger("harness.agent")


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


class AgentLoop:
    """执行 模型 → 工具 → 回喂 的循环，直到模型给出最终答复或达到步数上限。"""

    def __init__(
        self,
        client: IChatClient,
        tools: ToolRegistry,
        adapter: Optional[ToolCallAdapter] = None,
        *,
        max_steps: int = 8,
        on_progress: Optional[Callable[[int, int, list[str]], None]] = None,
        on_tool_error: Optional[Callable[[str, str], None]] = None,
    ):
        self.client = client
        self.tools = tools
        self.adapter = adapter or NativeToolCallAdapter()
        self.max_steps = max_steps
        self.on_progress = on_progress
        self.on_tool_error = on_tool_error

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

        schema = self.adapter.build_tools_schema(self.tools) if tool_names is None \
            else [self.tools.require(n).to_openai_schema() for n in tool_names]

        executions: list[ToolExecution] = []
        final_reply = ""
        hit_max = False

        for step in range(self.max_steps):
            if self.on_progress:
                self.on_progress(step, self.max_steps, [])

            response = await self._invoke(msgs, schema)
            parsed = self.adapter.parse(response)

            if not parsed.tool_calls:
                final_reply = parsed.text or response.content
                break

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
                    "output": result.output,
                    "error": result.error,
                })

            msgs.extend(self.adapter.build_round(response, results))

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

    async def _invoke(self, msgs: list[ChatMessage],
                      schema: list[dict]) -> ChatResponse:
        import inspect
        if inspect.iscoroutinefunction(self.client.invoke):
            return await self.client.invoke(msgs, tools=schema)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.client.invoke(msgs, tools=schema))
