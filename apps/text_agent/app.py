# apps/text_agent/app.py
# TextAgentApp — 完全基于 harness 核心的纯文本 Agent 参考应用。
#
# 组成: Runtime + Settings + ToolRegistry + AgentLoop + Conversation + Memory + TextRenderer
# 无任何 DSN 依赖。

from __future__ import annotations

import datetime
import operator
from typing import Optional

from harness import Runtime, Settings, Tool, ToolRegistry, Conversation
from harness.agent import AgentLoop
from harness.memory import InMemoryStore, MemoryEntry
from harness.models.base import IChatClient, IEmbeddingClient


class TextAgentApp:
    """最小但完整的文本 Agent 应用，演示 harness 的装配方式。"""

    def __init__(
        self,
        client: IChatClient,
        *,
        embedding_client: Optional[IEmbeddingClient] = None,
        name: str = "text-agent",
    ):
        self.client = client
        self.embedding_client = embedding_client
        self.name = name

        self.runtime = Runtime(name=name)
        self.settings = Settings()
        self.tools = ToolRegistry()
        self.memory = InMemoryStore(embedding_client)
        self.conversation = Conversation()

        self.runtime.register("settings", self.settings)
        self.runtime.register("tools", self.tools)
        self.runtime.register("memory", self.memory)
        self.runtime.register("conversation", self.conversation)
        self.runtime.register("chat_client", self.client)
        self.runtime.set_default()

        self._register_tools()

    def _register_tools(self) -> None:
        self.tools.register(Tool(
            name="calculator.eval",
            description="计算数学表达式，例如 1+2*3",
            handler=self._calc,
            parameters={"type": "object", "properties": {
                "expression": {"type": "string", "description": "数学表达式"},
            }},
        ))
        self.tools.register(Tool(
            name="time.now",
            description="获取当前日期时间",
            handler=lambda: datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            parameters={"type": "object", "properties": {}},
        ))

    @staticmethod
    def _calc(expression: str):
        allowed = set("0123456789+-*/(). ")
        if any(c not in allowed for c in expression):
            raise ValueError("表达式包含非法字符")
        return eval(expression, {"__builtins__": {}}, {})  # noqa: S307

    def run(self, message: str, *, system_prompt: str = "") -> str:
        """执行一次对话。"""
        self.conversation.add_text("user", message)

        loop = AgentLoop(self.client, self.tools, max_steps=6)
        result = loop.run(
            self.conversation.messages,
            system_prompt=system_prompt,
        )

        self.conversation.add_text("assistant", result.reply)
        self.memory.add(MemoryEntry(text=f"user: {message}\nassistant: {result.reply}"))
        return result.reply
