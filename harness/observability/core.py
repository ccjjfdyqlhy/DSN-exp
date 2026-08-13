# harness/observability.py
# 通用可观测性 — 计时器 + 计数器 + 结构化事件日志。

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

from ..pipeline.events import EventBus

logger = logging.getLogger("harness.observability")


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

    def __init__(self, event_bus: EventBus, source: str = "harness"):
        self._bus = event_bus
        self._source = source

    def info(self, event: str, payload: Any = None) -> None:
        self._bus.publish(f"log.{self._source}.{event}", payload)

    def warn(self, event: str, payload: Any = None) -> None:
        self._bus.publish(f"log.{self._source}.{event}.warn", payload)

    def error(self, event: str, payload: Any = None) -> None:
        self._bus.publish(f"log.{self._source}.{event}.error", payload)