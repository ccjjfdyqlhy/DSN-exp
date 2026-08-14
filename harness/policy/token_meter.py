# harness/policy/token_meter.py
# TokenMeter — 会话 token 成本核算（场景无关）。
#
# 从 dekacode token_counter.py 提炼并引擎化：
#   - 按模型定价表核算 缓存命中/未命中 输入与输出成本
#   - UsageRecord 记录每次调用的完整账目
#   - 会话累计（cost / tokens），供 TokenBudget 消费
#
# 定价表默认按 DeepSeek 官方价（$/M tokens）；可通过 pricing() 覆盖。

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


def pricing(*, input_cache_hit: float = 0.02, input_cache_miss: float = 1.0,
            output: float = 2.0, name: str = "default") -> dict:
    """构造定价表（$/M tokens）。"""
    return {"name": name,
            "input_cache_hit": input_cache_hit,
            "input_cache_miss": input_cache_miss,
            "output": output}


DEFAULT_PRICING = {
    "flash": pricing(input_cache_hit=0.02, input_cache_miss=1.0, output=2.0, name="flash"),
    "pro": pricing(input_cache_hit=0.025, input_cache_miss=3.0, output=6.0, name="pro"),
    "local": pricing(input_cache_hit=0.0, input_cache_miss=0.0, output=0.0, name="local"),
}


@dataclass
class UsageRecord:
    """一次模型调用的账目。"""

    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hit_input: int = 0
    cache_miss_input: int = 0
    cost: float = 0.0
    peak_hours: bool = False
    elapsed: float = 0.0
    ts: float = field(default_factory=lambda: datetime.now().timestamp())

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


class TokenMeter:
    """会话级成本核算。

    record() 从 usage dict（OpenAI 兼容响应）登记一次调用；
    cost / total_tokens / last 提供汇总视图。
    """

    def __init__(self, pricing_table: Optional[dict] = None,
                 pricing_name: str = "flash"):
        self.pricing_table = pricing_table or DEFAULT_PRICING
        self.pricing_name = pricing_name
        self.records: list[UsageRecord] = []

    def set_pricing(self, name: str) -> None:
        self.pricing_name = name

    def record(self, usage: dict, *, model: str = "", elapsed: float = 0.0,
               model_mode: Optional[str] = None) -> UsageRecord:
        usage = usage or {}
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        details = usage.get("prompt_tokens_details")
        cached = 0
        if isinstance(details, dict):
            cached = details.get("cached_tokens", 0)
        cache_miss = max(input_tokens - cached, 0)

        mode = model_mode or self.pricing_name
        table = self.pricing_table.get(mode, self.pricing_table.get("default",
                                       pricing()))
        cost = (cache_miss / 1e6 * table["input_cache_miss"]
                + cached / 1e6 * table["input_cache_hit"]
                + output_tokens / 1e6 * table["output"])

        rec = UsageRecord(
            model=model or mode,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_hit_input=cached,
            cache_miss_input=cache_miss,
            cost=cost,
            peak_hours=datetime.now().hour in tuple(
                h for rng in ((9, 12), (14, 18)) for h in range(*rng)),
            elapsed=elapsed,
        )
        self.records.append(rec)
        return rec

    # ── 汇总 ──

    @property
    def cost(self) -> float:
        return sum(r.cost for r in self.records)

    @property
    def total_tokens(self) -> int:
        return sum(r.total_tokens for r in self.records)

    @property
    def input_tokens(self) -> int:
        return sum(r.input_tokens for r in self.records)

    @property
    def output_tokens(self) -> int:
        return sum(r.output_tokens for r in self.records)

    @property
    def cache_hit_ratio(self) -> float:
        total_in = self.input_tokens
        if total_in == 0:
            return 0.0
        return sum(r.cache_hit_input for r in self.records) / total_in

    def summary(self) -> str:
        return (f"tokens={fmt_tokens(self.total_tokens)} "
                f"(in {fmt_tokens(self.input_tokens)} / out {fmt_tokens(self.output_tokens)}) "
                f"cache-hit={self.cache_hit_ratio:.0%} cost=¥{self.cost:.4f}")

    def __repr__(self) -> str:
        return f"<TokenMeter records={len(self.records)} cost={self.cost:.4f}>"
