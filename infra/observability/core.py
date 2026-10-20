# infra/observability.py
# 通用可观测性 — 计时器 + 计数器 + 结构化事件日志。

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

from typing import Protocol


class EventPublisher(Protocol):
    """事件发布者契约（结构化类型，无需继承）。

    修复说明（2026-10 分层）：本模块原先 `from harness.pipeline.events import EventBus`，
    是 infra → harness 的逆向依赖。EventLogger 只需要事件总线具备
    「publish(event, payload)」这一个能力，用 Protocol 表达即可切断对 harness 的导入。
    harness 的 EventBus 天然满足本协议，无需任何改动。
    """

    def publish(self, event: str, payload: Any = None) -> None: ...

logger = logging.getLogger("infra.observability")


@dataclass
class Metric:
    name: str
    value: float
    unit: str = ""
    tags: dict = field(default_factory=dict)


class MetricsCollector:
    """轻量计数/计时收集器。"""

    def __init__(self):
        self._counters: dict[str, int] = defaultdict(int)
        self._timers: dict[str, list[float]] = defaultdict(list)

    def incr(self, name: str, amount: int = 1) -> None:
        self._counters[name] += amount

    def timer_start(self, name: str) -> "_Timer":
        return _Timer(self, name)

    def record_timing(self, name: str, ms: float) -> None:
        self._timers[name].append(ms)

    def snapshot(self) -> dict[str, Any]:
        avg_timings = {}
        for name, vals in self._timers.items():
            avg_timings[name] = {
                "count": len(vals),
                "avg_ms": sum(vals) / len(vals) if vals else 0,
                "max_ms": max(vals) if vals else 0,
            }
        return {
            "counters": dict(self._counters),
            "timings": avg_timings,
        }

    def reset(self) -> None:
        self._counters.clear()
        self._timers.clear()


class _Timer:
    def __init__(self, collector: MetricsCollector, name: str):
        self._collector = collector
        self._name = name
        self._start = 0.0

    def __enter__(self) -> "_Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args: Any) -> None:
        elapsed = (time.perf_counter() - self._start) * 1000
        self._collector.record_timing(self._name, elapsed)


class EventLogger:
    """通过 EventBus 发布结构化日志事件，供外部监听。"""

    def __init__(self, event_bus: EventPublisher, source: str = "infra"):
        self._bus = event_bus
        self._source = source

    def info(self, event: str, payload: Any = None) -> None:
        self._bus.publish(f"log.{self._source}.{event}", payload)

    def warn(self, event: str, payload: Any = None) -> None:
        self._bus.publish(f"log.{self._source}.{event}.warn", payload)

    def error(self, event: str, payload: Any = None) -> None:
        self._bus.publish(f"log.{self._source}.{event}.error", payload)