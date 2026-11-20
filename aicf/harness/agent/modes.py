# harness/agent/modes.py
# AgentMode — 运行模式（场景无关）。
#
# 从 dekacode modes.py 提炼：
#   AGENT    多轮交互（默认）
#   ONESHOT  单轮一次性执行（@ 指令 / 脚本调用）
#   SWARM    多智能体黑板协作
#
# ModeState 提供模式切换与查询；模式影响上层如何调用 AgentLoop。

from __future__ import annotations

from enum import Enum


class AgentMode(str, Enum):
    AGENT = "agent"
    ONESHOT = "oneshot"
    SWARM = "swarm"


_MODE_ALIASES = {
    "agent": AgentMode.AGENT,
    "a": AgentMode.AGENT,
    "oneshot": AgentMode.ONESHOT,
    "one": AgentMode.ONESHOT,
    "o": AgentMode.ONESHOT,
    "swarm": AgentMode.SWARM,
    "s": AgentMode.SWARM,
}


class ModeState:
    """模式状态机：切换（含别名）、查询、默认。"""

    def __init__(self, mode: AgentMode = AgentMode.AGENT):
        self._mode = mode
        self._history: list[AgentMode] = []

    @property
    def mode(self) -> AgentMode:
        return self._mode

    @property
    def is_agent(self) -> bool:
        return self._mode is AgentMode.AGENT

    @property
    def is_oneshot(self) -> bool:
        return self._mode is AgentMode.ONESHOT

    @property
    def is_swarm(self) -> bool:
        return self._mode is AgentMode.SWARM

    def switch(self, mode):
        if isinstance(mode, AgentMode):
            new = mode
        else:
            new = _MODE_ALIASES.get(str(mode).strip().lower())
            if new is None:
                raise ValueError(f"未知模式: {mode!r}（可用: agent/oneshot/swarm）")
        if new is not self._mode:
            self._history.append(self._mode)
            self._mode = new
        return self._mode

    def back(self) -> AgentMode:
        """回退到上一模式。"""
        if self._history:
            self._mode = self._history.pop()
        return self._mode

    def __repr__(self) -> str:
        return f"<ModeState mode={self._mode.value}>"
