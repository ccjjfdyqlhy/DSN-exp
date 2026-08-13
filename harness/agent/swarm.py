# harness/agent/swarm.py
# 多智能体 swarm — 黑板共识编排。
#
# - Blackboard: 成员共享状态空间（thought/claim/consensus），带读指针与共识判定
# - SwarmMember: 一个成员 = 独立的 AgentLoop + 绑定的 blackboard.post 工具
# - SwarmRuntime: triage → 并行轮次 → 共识 / 兜底合成
#
# 通用性: 只依赖 IChatClient + ToolRegistry + AgentLoop，不绑定任何具体应用。

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from ..models.base import ChatMessage, IChatClient
from ..tools import Tool, ToolRegistry, ToolResult
from .loop import AgentLoop

logger = logging.getLogger("harness.swarm")

_ENTRY_KINDS = {"thought", "claim", "consensus", "objection"}


@dataclass
class BoardEntry:
    author: str
    kind: str
    content: str
    round: int
    ts: float = field(default_factory=time.time)


class Blackboard:
    """线程安全（异步锁）的共享状态空间。"""

    def __init__(self):
        self._entries: list[BoardEntry] = []
        self._lock = asyncio.Lock()
        self.current_round: int = 0
        self._read_ptr: dict[str, int] = {}

    def register_member(self, name: str) -> None:
        self._read_ptr.setdefault(name, 0)

    async def post(self, author: str, kind: str, content: str) -> None:
        kind = kind if kind in _ENTRY_KINDS else "thought"
        entry = BoardEntry(author=author, kind=kind, content=content,
                           round=self.current_round)
        async with self._lock:
            self._entries.append(entry)

    def digest_for(self, member: str, max_entries: int = 25,
                   max_chars_per: int = 1200) -> str:
        """返回 member 尚未读入的其他成员条目摘要，并推进读指针。"""
        ptr = self._read_ptr.get(member, 0)
        new = [e for e in self._entries[ptr:] if e.author != member]
        self._read_ptr[member] = len(self._entries)
        if not new:
            return ""
        new = new[-max_entries:]
        lines = []
        for e in new:
            c = e.content
            if len(c) > max_chars_per:
                c = c[:max_chars_per] + " …[truncated]"
            lines.append(f"[r{e.round}] {e.author} ({e.kind}): {c}")
        return "\n\n## Blackboard — from your peers\n" + "\n\n".join(lines)

    def _last_consensus_state(self) -> Optional[tuple[BoardEntry, list[BoardEntry]]]:
        last_idx = -1
        last_cons: Optional[BoardEntry] = None
        for i, e in enumerate(self._entries):
            if e.kind == "consensus":
                last_cons = e
                last_idx = i
        if last_cons is None or last_idx < 0:
            return None
        objections = [e for e in self._entries[last_idx + 1:] if e.kind == "objection"]
        return last_cons, objections

    def consensus_survived(self) -> bool:
        state = self._last_consensus_state()
        if state is None:
            return False
        last_cons, objections = state
        return self.current_round > last_cons.round and not objections

    def final_answer(self) -> Optional[str]:
        state = self._last_consensus_state()
        if state is None:
            return None
        last_cons, objections = state
        return None if objections else last_cons.content

    def entries(self) -> list[BoardEntry]:
        return list(self._entries)


@dataclass
class SwarmRunResult:
    answer: str = ""
    rounds: int = 0
    consensus: bool = False
    member_outputs: dict[str, str] = field(default_factory=dict)
    usage: dict = field(default_factory=dict)


class SwarmMember:
    """一个 swarm 成员：独立上下文 + 工具循环，向黑板发布想法/共识。"""

    def __init__(
        self,
        name: str,
        client: IChatClient,
        tools: ToolRegistry,
        board: Blackboard,
        system_prompt: str = "",
        *,
        max_turns: int = 4,
        timeout: float = 120.0,
    ):
        self.name = name
        self.client = client
        self.board = board
        self.max_turns = max_turns
        self.timeout = timeout
        self.system_prompt = system_prompt
        board.register_member(name)
        self.tools = self._bind_board_tool(tools)

    def _bind_board_tool(self, shared: ToolRegistry) -> ToolRegistry:
        reg = ToolRegistry()
        for tool in shared.tools():
            reg.register(tool)
        reg.register(Tool(
            name="blackboard.post",
            description="向黑板发布一条消息。kind 为 thought(想法) / claim(主张) / "
                        "consensus(共识结论) / objection(反对意见)。",
            handler=lambda kind, content: self._post(kind, content),
            parameters={"type": "object", "properties": {
                "kind": {"type": "string", "enum": ["thought", "claim", "consensus", "objection"]},
                "content": {"type": "string"},
            }, "required": ["kind", "content"]},
            async_mode=True,
        ))
        return reg

    async def _post(self, kind: str, content: str) -> ToolResult:
        await self.board.post(self.name, kind, content)
        return ToolResult.ok(f"posted {kind} to blackboard")

    async def run_round(self, round_idx: int, directive: str = "",
                        seed_user_msg: Optional[str] = None) -> str:
        digest = self.board.digest_for(self.name)
        system = self.system_prompt
        if directive:
            system += f"\n\n# Directive\n{directive}"
        if digest:
            system += f"\n{digest}"

        messages: list[ChatMessage] = []
        if round_idx == 0 and seed_user_msg:
            messages.append(ChatMessage.user(seed_user_msg))

        loop = AgentLoop(self.client, self.tools, max_steps=self.max_turns)
        try:
            async with asyncio.timeout(self.timeout):
                result = await loop.run_async(messages, system_prompt=system)
        except asyncio.TimeoutError:
            logger.warning("成员 %s 第 %d 轮超时", self.name, round_idx)
            return ""

        content = (result.reply or "").strip()
        if content:
            await self.board.post(self.name, "thought", content)
        return content


class SwarmRuntime:
    """编排成员轮次，追求黑板共识。"""

    def __init__(self, members: list[SwarmMember], *,
                 max_rounds: int = 3):
        self.members = members
        self.max_rounds = max_rounds
        self.board = members[0].board if members else Blackboard()

    async def run(self, message: str, *, directive: str = "") -> SwarmRunResult:
        result = SwarmRunResult()
        for round_idx in range(self.max_rounds):
            self.board.current_round = round_idx
            outputs = await asyncio.gather(
                *[m.run_round(round_idx, directive=directive,
                              seed_user_msg=message if round_idx == 0 else None)
                  for m in self.members],
                return_exceptions=True,
            )
            for m, out in zip(self.members, outputs):
                if isinstance(out, Exception):
                    logger.warning("成员 %s 异常: %s", m.name, out)
                    result.member_outputs[m.name] = ""
                else:
                    result.member_outputs[m.name] = out or ""

            answer = self.board.final_answer()
            if answer and self.board.consensus_survived():
                result.answer = answer
                result.consensus = True
                result.rounds = round_idx + 1
                return result

        # 兜底：无共识，用最后内容拼接
        result.answer = self._fallback_synthesis(result.member_outputs)
        result.rounds = self.max_rounds
        return result

    @staticmethod
    def _fallback_synthesis(member_outputs: dict[str, str]) -> str:
        parts = [f"{name}: {out}" for name, out in member_outputs.items() if out]
        return "\n\n".join(parts) if parts else "（无输出）"
