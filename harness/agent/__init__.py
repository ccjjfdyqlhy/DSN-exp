# harness/agent/__init__.py
# Agent 执行层 — 模型调用 + 工具执行的循环。

from .loop import AgentLoop, AgentRunResult, ToolExecution, RoundResult, StreamEvent
from .adapters import ToolCallAdapter, NativeToolCallAdapter, TaggedToolCallAdapter
from .context import (
    ThreeZoneContext,
    SpeculativePrefetch,
    PrefetchPlaceholders,
)
from .swarm import Blackboard, SwarmMember, SwarmRuntime, SwarmRunResult
from .assembler import AgentAssembler, AssembledAgent, AgentSpec
from .subagent import SubAgentRunner, SubTask, SubAgentRunResult
from .modes import AgentMode, ModeState
from .events import EVENT_KINDS, EventSink, LEVELS, STATUSES
from .engine_config import (
    AgentSettings, ContextSettings, EngineConfig, ModelInfo,
    ReasoningSettings, ThinkingSettings,
)
from .engine import ConversationEngine, EngineSnapshot

__all__ = [
    "AgentLoop",
    "AgentRunResult",
    "ToolExecution",
    "RoundResult",
    "StreamEvent",
    "AgentAssembler",
    "AssembledAgent",
    "AgentSpec",
    "SubAgentRunner",
    "SubTask",
    "SubAgentRunResult",
    "AgentMode",
    "ModeState",
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
    "ConversationEngine",
    "EngineSnapshot",
    "EngineConfig",
    "ModelInfo",
    "EventSink",
    "EVENT_KINDS",
    "STATUSES",
    "LEVELS",
]
