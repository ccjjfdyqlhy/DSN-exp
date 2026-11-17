# harness/agent/engine_config.py
# Settings and model descriptors for the conversation engine.
#
# Plain dataclasses with engine defaults, so an application can drive the
# engine without wiring a full configuration store.

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ContextSettings:
    auto_compact: bool = True
    compact_threshold: int = 85        # percent of the usable budget
    keep_recent_turns: int = 2
    reserved_output: int = 8_192
    compaction_reasoning_effort: str = 'low'


@dataclass
class ReasoningSettings:
    effort: str = 'medium'
    force: bool = False


@dataclass
class ThinkingSettings:
    show_completed: bool = True


@dataclass
class HoldSettings:
    """Keep a broken request alive instead of failing the turn.

    A round whose stream breaks, or that ends without a finish signal, is
    re-sent until it works, the user interrupts, or the retries run out.
    ``delay`` is the first wait; every further retry waits twice as long,
    capped at ``max_delay``.
    """

    enabled: bool = False
    max_retries: int = 20
    delay: float = 2.0
    max_delay: float = 30.0


@dataclass
class AgentSettings:
    team_enabled: bool = True
    max_concurrent: int = 10
    max_depth: int = 4
    wait_timeout_ms: int = 30_000
    default_fork_turns: str = 'all'
    show_activity: bool = True
    show_output: bool = False
    default_type: str = 'general'
    system_suffix: str = ''


@dataclass
class ModelInfo:
    """The model metadata the engine needs, wire-agnostic."""

    id: str = ''
    provider: str = ''
    endpoint: str = ''
    wire: str = ''
    context_window: int = 128_000
    max_output_tokens: int = 8_192
    vision: bool = False
    # 'none' | 'effort' | 'toggle': how this model takes a reasoning dial
    reasoning_style: str = 'effort'
    reasoning_efforts: tuple[str, ...] = ()
    reasoning: bool = False


@dataclass
class EngineConfig:
    context: ContextSettings = field(default_factory=ContextSettings)
    reasoning: ReasoningSettings = field(default_factory=ReasoningSettings)
    thinking: ThinkingSettings = field(default_factory=ThinkingSettings)
    agents: AgentSettings = field(default_factory=AgentSettings)
    hold: HoldSettings = field(default_factory=HoldSettings)
    max_output_tokens: int = 8_192
    checkpoint_interval: float = 30.0
    max_continuations: int = 3
