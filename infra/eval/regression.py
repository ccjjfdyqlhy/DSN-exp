# infra/eval/regression.py
# 回归判定：当前 RunVersion 相对 baseline 的逐指标差异 + 阈值判定。
#
# ── 为什么回归一定要看「相对 baseline」而不是绝对阈值？ ──
# 因为绝对阈值会随模型、机器、评测集变化而漂移 —— 今天 800 token 是合理上限，
# 换了个更贵的模型就天天报警。相对基线才能回答真正想问的问题：
# 「这次改动让 agent 变差了吗？」
#
# ── 方向性是这里最容易出错的地方 ──
# 通过率是**越高越好**，成本/耗时是**越低越好**。
# 如果不区分方向，「成本降了 30%」会被算成「下降 30%」而误报回归。
# 所以每个指标都有方向，判定只看**变差的那一侧**。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional

#: 越高越好的指标。
HIGHER_IS_BETTER: frozenset[str] = frozenset({
    "pass_rate",
    "critical_pass_rate",
    "mean_score",
    "passed_cases",
    "critical_passed",
})

#: 越低越好的指标。
LOWER_IS_BETTER: frozenset[str] = frozenset({
    "mean_cost_tokens",
    "total_cost_tokens",
    "max_cost_tokens",
    "mean_latency_ms",
    "total_cost",
    "tool_calls_total",
    "security_violations",
})

#: 默认参与回归比较的指标。
DEFAULT_METRICS: tuple[str, ...] = (
    "pass_rate",
    "critical_pass_rate",
    "mean_score",
    "mean_cost_tokens",
    "total_cost",
    "mean_latency_ms",
)

#: 默认回归阈值：任一指标变差超过 2% 即判失败（§4.6.5）。
DEFAULT_MAX_DROP = 0.02


def is_higher_is_better(metric: str) -> bool:
    """指标方向。未知指标默认按「越高越好」处理（保守：不会漏报变差）。"""
    if metric in LOWER_IS_BETTER:
        return False
    return True


@dataclass
class MetricDelta:
    """单个指标的差异。"""

    metric: str
    baseline: float
    current: float
    #: 带符号的相对变化：(current - baseline) / baseline。
    rel_delta: float = 0.0
    #: 变坏的幅度（永远 ≥ 0）；方向正确的指标变好时为 0。
    drop: float = 0.0
    higher_is_better: bool = True
    dropped: bool = False
    threshold: float = DEFAULT_MAX_DROP

    @property
    def abs_delta(self) -> float:
        return self.current - self.baseline

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "baseline": self.baseline,
            "current": self.current,
            "abs_delta": self.abs_delta,
            "rel_delta": self.rel_delta,
            "drop": self.drop,
            "higher_is_better": self.higher_is_better,
            "dropped": self.dropped,
            "threshold": self.threshold,
        }


@dataclass
class RegressionReport:
    """回归判定结果。"""

    metrics: list[MetricDelta] = field(default_factory=list)
    threshold: float = DEFAULT_MAX_DROP
    passed: bool = True
    failures: list[str] = field(default_factory=list)
    baseline_id: str = ""
    current_id: str = ""

    @property
    def dropped_metrics(self) -> list[MetricDelta]:
        return [m for m in self.metrics if m.dropped]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "threshold": self.threshold,
            "baseline_id": self.baseline_id,
            "current_id": self.current_id,
            "failures": list(self.failures),
            "metrics": [m.to_dict() for m in self.metrics],
        }


def compare_metrics(
    baseline: Mapping[str, float],
    current: Mapping[str, float],
    *,
    metrics: Optional[Iterable[str]] = None,
    threshold: float = DEFAULT_MAX_DROP,
    directions: Optional[Mapping[str, bool]] = None,
    baseline_id: str = "",
    current_id: str = "",
) -> RegressionReport:
    """逐指标比较两组指标，输出差异与阈值判定。

    :param threshold: 允许的变差幅度（0.02 = 2%）。
    :param directions: ``{指标名: 是否越高越好}``，覆盖默认方向。
    """
    names = list(metrics) if metrics is not None else sorted(
        set(baseline.keys()) | set(current.keys())
    )
    report = RegressionReport(threshold=threshold, baseline_id=baseline_id, current_id=current_id)

    for name in names:
        base = float(baseline.get(name, 0.0) or 0.0)
        cur = float(current.get(name, 0.0) or 0.0)
        higher = directions.get(name) if directions and name in directions else is_higher_is_better(name)

        if base == 0.0:
            # 基线为 0：相对变化无意义。
            # 「从 0 涨到正数」对越低越好的指标是变差（drop=1.0 视作 100% 变差）；
            # 对越高越好的指标是从无到有，算改善。
            rel = 0.0 if cur == 0.0 else (1.0 if not higher else 0.0)
            drop = 0.0 if (higher or cur == 0.0) else 1.0
        else:
            rel = (cur - base) / base
            if higher:
                drop = max(0.0, (base - cur) / base)
            else:
                drop = max(0.0, (cur - base) / base)

        # 用 epsilon 比较：浮点误差不该把「正好 2%」判成回归
        # （0.02 在二进制里其实是 0.020000000000000018）。
        dropped = drop > threshold + 1e-9
        delta = MetricDelta(
            metric=name,
            baseline=base,
            current=cur,
            rel_delta=rel,
            drop=drop,
            higher_is_better=higher,
            dropped=dropped,
            threshold=threshold,
        )
        report.metrics.append(delta)
        if dropped:
            direction = "上升" if not higher else "下降"
            report.failures.append(
                f"{name} {direction} {drop * 100:.2f}%（baseline {base:g} → 当前 {cur:g}），"
                f"超过阈值 {threshold * 100:.2f}%"
            )
    report.passed = not report.failures
    return report
