# harness/policy/budget.py
# TokenBudget — 会话预算策略（场景无关）。
#
# 创新设计：把"预算"做成可感知压力的策略对象——
#   - token 与费用双上限
#   - pressure() 返回 0..1 的预算压力（供 ModelRouter 降级决策）
#   - 超限回调（on_exceed），可挂接截断/降级/提醒

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from .token_meter import TokenMeter, fmt_tokens


@dataclass
class BudgetState:
    token_cap: Optional[int] = None
    cost_cap: Optional[float] = None
    exceeded: bool = False
    reason: str = ""


class TokenBudget:
    """会话 token/费用预算。

    用法:
        budget = TokenBudget(token_cap=200_000, cost_cap=0.5)
        meter = TokenMeter()
        budget.bind(meter)          # 记账自动流入预算
        pressure = budget.pressure()  # 0..1
        if budget.exceeded: ...
    """

    def __init__(self, *, token_cap: Optional[int] = None,
                 cost_cap: Optional[float] = None,
                 on_exceed: Optional[Callable[[BudgetState], None]] = None):
        self.token_cap = token_cap
        self.cost_cap = cost_cap
        self._on_exceed = on_exceed
        self._meter: Optional[TokenMeter] = None
        self._exceeded = False
        self._exceed_reason = ""

    def bind(self, meter: TokenMeter) -> "TokenBudget":
        """绑定 TokenMeter：meter.record() 后自动检查预算。"""
        self._meter = meter
        return self

    # ── 压力计算 ──

    def pressure(self) -> float:
        """返回 0..1 的预算压力：token 与费用占用比例的较大者。"""
        if self._meter is None:
            return 0.0
        pressures = []
        if self.token_cap:
            pressures.append(self._meter.total_tokens / self.token_cap)
        if self.cost_cap:
            pressures.append(self._meter.cost / self.cost_cap)
        return min(1.0, max(pressures)) if pressures else 0.0

    @property
    def exceeded(self) -> bool:
        return self._exceeded

    @property
    def reason(self) -> str:
        return self._exceed_reason

    def check(self) -> bool:
        """检查是否超限；首次超限触发 on_exceed 回调。"""
        if self._meter is None:
            return False
        reason = ""
        if self.token_cap and self._meter.total_tokens >= self.token_cap:
            reason = f"token 超限 ({fmt_tokens(self._meter.total_tokens)} >= {fmt_tokens(self.token_cap)})"
        elif self.cost_cap and self._meter.cost >= self.cost_cap:
            reason = f"费用超限 (¥{self._meter.cost:.4f} >= ¥{self.cost_cap:.4f})"
        if reason and not self._exceeded:
            self._exceeded = True
            self._exceed_reason = reason
            if self._on_exceed:
                try:
                    self._on_exceed(BudgetState(
                        token_cap=self.token_cap, cost_cap=self.cost_cap,
                        exceeded=True, reason=reason))
                except Exception:
                    pass
        return self._exceeded

    def reset(self) -> None:
        self._exceeded = False
        self._exceed_reason = ""

    def __repr__(self) -> str:
        return (f"<TokenBudget token_cap={self.token_cap} cost_cap={self.cost_cap} "
                f"pressure={self.pressure():.0%} exceeded={self._exceeded}>")
