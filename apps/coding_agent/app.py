# apps/coding_agent/app.py
# CodingAgent — 基于 harness 的代码助手应用。
#
# 组合了 harness 的 AgentRuntime + 三区上下文 + 用量追踪 + 会话持久化，
# 以及本 bundle 的 coding 技能。证明 harness 足以承载 coding agent。
#
# 外部 MCP 工具源（可选）：mcp_config 传入 mcp_servers.yaml 路径即启用，
# 远端工具注册为 mcp.<server>.<tool>，与本地 coding 工具同一注册表。

from __future__ import annotations

import asyncio
from typing import Optional

from harness import AgentRuntime
from harness.agent import ThreeZoneContext
from harness.tools.mcp import MCPManager
from infra.models.base import ChatMessage, IChatClient, IEmbeddingClient
from infra.observability import UsageTracker
from infra.store import SessionStore
from .skills import install_coding_tools


class CodingAgent:
    def __init__(
        self,
        client: IChatClient,
        *,
        embedding_client: Optional[IEmbeddingClient] = None,
        system_prompt: str = "你是一名资深软件工程师助手，用中文简洁回答。",
        max_steps: int = 8,
        mcp_config: Optional[str] = None,
    ):
        self.agent = AgentRuntime(
            client, embedding_client=embedding_client,
            name="coding-agent", system_prompt=system_prompt, max_steps=max_steps,
        )
        install_coding_tools(self.agent.tools)
        self.ctx = ThreeZoneContext(system_prompt)
        self.usage = UsageTracker()
        self.session_store: Optional[SessionStore] = None
        # 外部 MCP 工具源。同步 REPL 场景：首轮对话时加载一次工具清单；
        # stdio 子进程随各轮事件循环销毁，后续调用靠 handler 里的
        # 重连一次机制自动恢复（详见 harness/tools/mcp.py 模块头）。
        self.mcp: Optional[MCPManager] = None
        self._mcp_loaded = False
        if mcp_config:
            self.mcp = MCPManager.from_yaml(mcp_config)

    def enable_persistence(self, db_path: str = ":memory:") -> "CodingAgent":
        self.session_store = SessionStore(db_path=db_path)
        self.session_store.create_session()
        return self

    def register_tool(self, name: str, description: str, handler, parameters=None):
        return self.agent.register_tool(name, description, handler, parameters)

    def chat(self, message: str) -> str:
        """执行一次带工具循环的对话。"""
        if self.mcp is not None and not self._mcp_loaded:
            errors = asyncio.run(self.mcp.load_tools(self.agent.tools))
            if errors:
                import logging
                logging.getLogger("coding_agent").warning(
                    "MCP 服务器加载失败（已跳过）: %s", errors)
            self._mcp_loaded = True
        self.ctx.add_user(message)
        result = self.agent.run_with_tools(message)
        self.ctx.add_assistant(ChatMessage.assistant(result.reply))
        # 修复：enable_persistence 此前是空操作——SessionStore 建了会话但
        # chat() 从不写入，__main__ 明确启用它而对话从未落库。每轮结束把
        # 用户/助手消息持久化。
        if self.session_store is not None:
            try:
                self.session_store.save_messages([
                    ChatMessage.user(message),
                    ChatMessage.assistant(result.reply),
                ])
            except Exception:
                import logging
                logging.getLogger("coding_agent").warning(
                    "会话持久化失败（已跳过）", exc_info=True)
        return result.reply

    @property
    def runtime(self):
        return self.agent.runtime
