# harness/agent/__init__.py
# Agent 执行层 — 模型调用 + 工具执行的循环。

from .loop import AgentLoop, AgentRunResult, ToolExecution
from .adapters import ToolCallAdapter, NativeToolCallAdapter, TaggedToolCallAdapter
from .context import (
    ThreeZoneContext,
    SpeculativePrefetch,
    PrefetchPlaceholders,
)
from .swarm import Blackboard, SwarmMember, SwarmRuntime, SwarmRunResult

__all__ = [
    "AgentLoop",
    "AgentRunResult",
    "ToolExecution",
    "ToolCallAdapter",
    "NativeToolCallAdapter",
    "TaggedToolCallAdapter",
    "ThreeZoneContext",
    "SpeculativePrefetch",
    "PrefetchPlaceholders",
    "Blackboard",
    "SwarmMember",
    "SwarmRuntime",
    "SwarmRunResult",
]
