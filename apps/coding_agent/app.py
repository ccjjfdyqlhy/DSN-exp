# apps/coding_agent/app.py
# CodingAgent — 基于 harness 的代码助手应用。
#
# 组合了 harness 的 AgentRuntime + 三区上下文 + 用量追踪 + 会话持久化，
# 以及本 bundle 的 coding 技能。证明 harness 足以承载 coding agent。

from __future__ import annotations

from typing import Optional

from harness import AgentRuntime
from harness.agent import ThreeZoneContext
from harness.models.base import ChatMessage, IChatClient, IEmbeddingClient
from harness.observability import UsageTracker
from harness.store import SessionStore
from .skills import install_coding_tools


class CodingAgent:
    def __init__(
        self,
        client: IChatClient,
        *,
        embedding_client: Optional[IEmbeddingClient] = None,
        system_prompt: str = "你是一名资深软件工程师助手，用中文简洁回答。",
        max_steps: int = 8,
    ):
        self.agent = AgentRuntime(
            client, embedding_client=embedding_client,
            name="coding-agent", system_prompt=system_prompt, max_steps=max_steps,
        )
        install_coding_tools(self.agent.tools)
        self.ctx = ThreeZoneContext(system_prompt)
        self.usage = UsageTracker()
        self.session_store: Optional[SessionStore] = None

    def enable_persistence(self, db_path: str = ":memory:") -> "CodingAgent":
        self.session_store = SessionStore(db_path=db_path)
        self.session_store.create_session()
        return self

    def register_tool(self, name: str, description: str, handler, parameters=None):
        return self.agent.register_tool(name, description, handler, parameters)

    def chat(self, message: str) -> str:
        """执行一次带工具循环的对话。"""
        self.ctx.add_user(message)
        result = self.agent.run_with_tools(message)
        self.ctx.add_assistant(ChatMessage.assistant(result.reply))
        return result.reply

    @property
    def runtime(self):
        return self.agent.runtime
