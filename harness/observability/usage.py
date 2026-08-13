# harness/observability/usage.py
# UsageTracker — token / 缓存命中 / 成本追踪。
#
# 从 LLM 返回的 usage 计算每档模型成本，支持会话累计与预算上限。
# 计价规则可配置（每百万 token 价格）。

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from ..models.base import ChatResponse


@dataclass
class Price:
    input_cache_hit: float = 0.02      # ¥/百万 token
    input_cache_miss: float = 1.0
    output: float = 2.0


@dataclass
class UsageRecord:
    tier: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hit_input: int = 0
    cache_miss_input: int = 0
    cost: float = 0.0
    elapsed: float = 0.0
    peak_hours: bool = False

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def as_dict(self) -> dict:
        return {
            "tier": self.tier,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_hit_input": self.cache_hit_input,
            "cache_miss_input": self.cache_miss_input,
            "cost": self.cost,
            "elapsed": self.elapsed,
            "peak_hours": self.peak_hours,
        }


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


class UsageTracker:
    def __init__(self, *, prices: Optional[dict[str, Price]] = None,
                 peak_multiplier: float = 2.0, budget: Optional[float] = None):
        self._prices = prices or {"default": Price()}
        self._peak_mult = peak_multiplier
        self.budget = budget
        self.records: list[UsageRecord] = []

    def record(self, response: ChatResponse, tier: str = "flash",
               elapsed: float = 0.0, *, peak_hours: Optional[bool] = None) -> UsageRecord:
        usage = response.usage or {}
        prompt = int(usage.get("prompt_tokens", 0))
        completion = int(usage.get("completion_tokens", 0))
        details = usage.get("prompt_tokens_details") or {}
        cached = int(details.get("cached_tokens", 0)) if isinstance(details, dict) else 0
        miss = max(0, prompt - cached)

        peak = in_peak_hours() if peak_hours is None else peak_hours
        price = self._prices.get(tier, self._prices["default"])
        mult = self._peak_mult if peak else 1.0
        cost = (
            cached * price.input_cache_hit
            + miss * price.input_cache_miss
            + completion * price.output
        ) * mult / 1_000_000

        rec = UsageRecord(
            tier=tier, input_tokens=prompt, output_tokens=completion,
            cache_hit_input=cached, cache_miss_input=miss,
            cost=cost, elapsed=elapsed, peak_hours=peak,
        )
        self.records.append(rec)
        return rec

    def record_dict(self, usage: dict, tier: str = "flash",
                    elapsed: float = 0.0) -> UsageRecord:
        from ..models.base import ChatResponse
        return self.record(ChatResponse(usage=usage), tier=tier, elapsed=elapsed)

    @property
    def total_cost(self) -> float:
        return sum(r.cost for r in self.records)

    @property
    def total_input(self) -> int:
        return sum(r.input_tokens for r in self.records)

    @property
    def total_output(self) -> int:
        return sum(r.output_tokens for r in self.records)

    @property
    def total_cache_hit(self) -> int:
        return sum(r.cache_hit_input for r in self.records)

    def over_budget(self) -> bool:
        return self.budget is not None and self.total_cost >= self.budget

    def summary(self) -> dict:
        return {
            "calls": len(self.records),
            "total_cost": self.total_cost,
            "total_input": self.total_input,
            "total_output": self.total_output,
            "total_cache_hit": self.total_cache_hit,
            "over_budget": self.over_budget(),
        }

    def reset(self) -> None:
        self.records.clear()


def in_peak_hours(ranges: tuple = ((9, 12), (14, 18))) -> bool:
    h = time.localtime().tm_hour
    return any(start <= h < end for start, end in ranges)
