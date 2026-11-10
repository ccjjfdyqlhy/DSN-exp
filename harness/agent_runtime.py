# harness/agent_runtime.py
# AgentRuntime — 一站式 Agent 装配门面。
#
# 把 Runtime / Settings / ToolRegistry / Conversation / Memory / AgentLoop
# 组装成一个开箱即用的 Agent，用于快速构建场景无关的应用。
#
# 用法:
#     from harness import AgentRuntime
#     rt = AgentRuntime(chat_client)
#     rt.register_tool("time.now", "获取时间", lambda: now())
#     reply = rt.run("现在几点了？")
#     result = rt.run_with_tools("1+2 等于多少？")

from __future__ import annotations

from typing import Any, AsyncGenerator, Optional

from .agent import AgentLoop, AgentRunResult
from .conversation import Conversation, ConversationManager
from .memory import InMemoryStore, MemoryEntry
from infra.orchestrator.base import IChatClient, IEmbeddingClient
from infra.runtime import Runtime
from infra.settings import Settings
from .tools import Tool, ToolRegistry


class AgentRuntime:
    """开箱即用的通用 Agent。"""

    def __init__(
        self,
        chat_client: IChatClient,
        *,
        embedding_client: Optional[IEmbeddingClient] = None,
        name: str = "agent",
        system_prompt: str = "",
        max_steps: int = 8,
        adapter: Optional[Any] = None,
    ):
        self.chat_client = chat_client
        self.embedding_client = embedding_client
        self.system_prompt = system_prompt
        self.max_steps = max_steps
        # 工具调用协议适配器（None → harness 默认的原生 function calling）。
        # 应用可注入自定义适配器（如 dsn_study 的 <tool> 标签降级适配器）。
        self.adapter = adapter

        self.runtime = Runtime(name=name)
        self.settings = Settings()
        self.tools = ToolRegistry()
        self.conversations = ConversationManager()
        self.memory = InMemoryStore(embedding_client)

        self.runtime.register("settings", self.settings)
        self.runtime.register("tools", self.tools)
        self.runtime.register("conversations", self.conversations)
        self.runtime.register("memory", self.memory)
        self.runtime.register("chat_client", chat_client)
        self.runtime.set_default()

    # ── 工具注册 ──

    def register_tool(self, name: str, description: str,
                      handler: Any, parameters: Optional[dict] = None,
                      *, async_mode: bool = False) -> Tool:
        return self.tools.register_tool(
            name, description, handler, parameters, async_mode=async_mode)

    def register(self, tool: Tool) -> Tool:
        return self.tools.register(tool)

    # ── 会话 ──

    def session(self, session_id: Optional[str] = None) -> Conversation:
        if session_id and self.conversations.get(session_id):
            return self.conversations.require(session_id)
        return self.conversations.create(session_id=session_id)

    # ── 执行 ──

    def run_with_tools(self, message: str, *,
                       session_id: Optional[str] = None,
                       tool_names: Optional[list[str]] = None,
                       system_prompt: Optional[str] = None) -> AgentRunResult:
        """带工具循环的完整执行。

        ``system_prompt`` 可按调用覆盖实例默认 —— 有些内容**逐轮变化**
        （人格状态按 uid、上下文按会话/用户），不能只靠实例上的静态字符串。
        AgentLoop.run 本就接受 per-call 的 system_prompt，这里只是把它透出来。
        """
        conv = self.session(session_id)
        conv.add_text("user", message)
        loop = AgentLoop(self.chat_client, self.tools, max_steps=self.max_steps,
                         adapter=self.adapter)
        result = loop.run(conv.messages,
                          system_prompt=(self.system_prompt
                                         if system_prompt is None
                                         else system_prompt),
                          tool_names=tool_names)
        conv.add_text("assistant", result.reply)
        self.memory.add(MemoryEntry(
            text=f"user: {message}\nassistant: {result.reply}"))
        return result

    async def run_stream_with_tools(
        self,
        message: str,
        *,
        session_id: Optional[str] = None,
        tool_names: Optional[list[str]] = None,
        system_prompt: Optional[str] = None,
    ) -> AsyncGenerator[Any, None]:
        """流式执行 + 工具循环（异步生成器）。

        与 :meth:`run_with_tools` 语义等价，但走 :meth:`AgentLoop.run_stream`：
        文本增量实时产出，**原生 tool call 在流中照常累积、执行、回喂**，
        多轮工具循环完整保留。

        产出 :class:`harness.agent.StreamEvent`（kind = round_start / delta /
        reasoning / tool_call / tool_result / reply / done）。

        会话历史在**流结束时**才写回 —— 生成器被提前关闭（客户端断开）时
        不会写入半截回复。调用方若需要中途落库，自行监听 reply 事件。
        """
        conv = self.session(session_id)
        conv.add_text("user", message)
        loop = AgentLoop(self.chat_client, self.tools, max_steps=self.max_steps,
                         adapter=self.adapter)
        collected: list[str] = []
        final_reply = ""
        try:
            async for event in loop.run_stream(
                    conv.messages,
                    tool_names=tool_names,
                    system_prompt=(self.system_prompt
                                   if system_prompt is None
                                   else system_prompt)):
                kind = getattr(event, "kind", "")
                if kind == "delta" and event.content:
                    collected.append(event.content)
                elif kind in ("reply", "done") and getattr(event, "reply", ""):
                    final_reply = event.reply
                yield event
        finally:
            text = final_reply or "".join(collected)
            if text:
                conv.add_text("assistant", text)
                self.memory.add(MemoryEntry(
                    text=f"user: {message}\nassistant: {text}"))

    def run(self, message: str, *, session_id: Optional[str] = None,
            system_prompt: Optional[str] = None) -> str:
        """单轮便捷入口，返回最终文本回复。"""
        return self.run_with_tools(message, session_id=session_id,
                                   system_prompt=system_prompt).reply

    def __repr__(self) -> str:
        return f"<AgentRuntime name={self.runtime.name} tools={len(self.tools)}>"
