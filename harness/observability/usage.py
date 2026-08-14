# harness/observability/usage.py
# UsageTracker — token / 缓存命中 / 成本追踪（会话级，供应用层消费）。
#
# UsageRecord / fmt_tokens / in_peak_hours 与 policy.token_meter 共用一份实现，
# 本模块只保留 Price（计价规则）与 UsageTracker（聚合器）。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..models.base import ChatResponse
# 复用 policy 层唯一实现（旧本地副本已合并删除）
from ..policy.token_meter import UsageRecord, fmt_tokens, in_peak_hours

__all__ = ["Price", "UsageRecord", "fmt_tokens", "in_peak_hours", "UsageTracker"]


@dataclass
class Price:
    input_cache_hit: float = 0.02      # ¥/百万 token
    input_cache_miss: float = 1.0
    output: float = 2.0


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
            model=tier, tier=tier, input_tokens=prompt, output_tokens=completion,
            cache_hit_input=cached, cache_miss_input=miss,
            cost=cost, elapsed=elapsed, peak_hours=peak,
        )
        self.records.append(rec)
        return rec

    def record_dict(self, usage: dict, tier: str = "flash",
                    elapsed: float = 0.0) -> UsageRecord:
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
