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

from typing import Any, Optional

from .agent import AgentLoop, AgentRunResult
from .conversation import Conversation, ConversationManager
from .memory import InMemoryStore, MemoryEntry
from .models.base import IChatClient, IEmbeddingClient
from .runtime import Runtime
from .settings import Settings
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
    ):
        self.chat_client = chat_client
        self.embedding_client = embedding_client
        self.system_prompt = system_prompt
        self.max_steps = max_steps

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
                       tool_names: Optional[list[str]] = None) -> AgentRunResult:
        """带工具循环的完整执行。"""
        conv = self.session(session_id)
        conv.add_text("user", message)
        loop = AgentLoop(self.chat_client, self.tools, max_steps=self.max_steps)
        result = loop.run(conv.messages, system_prompt=self.system_prompt,
                          tool_names=tool_names)
        conv.add_text("assistant", result.reply)
        self.memory.add(MemoryEntry(
            text=f"user: {message}\nassistant: {result.reply}"))
        return result

    def run(self, message: str, *, session_id: Optional[str] = None) -> str:
        """单轮便捷入口，返回最终文本回复。"""
        return self.run_with_tools(message, session_id=session_id).reply

    def __repr__(self) -> str:
        return f"<AgentRuntime name={self.runtime.name} tools={len(self.tools)}>"
