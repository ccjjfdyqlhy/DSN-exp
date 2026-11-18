# infra/eval/experiment.py
# Experiment：在同一份 Dataset 上对多个配置做对比（最小版）。
#
# ── 为什么需要「多配置」这一层？ ──
# 单次评测只能回答「这次行不行」，回答不了「哪一步改动带来的收益」。
# 但 rc0 阶段不需要完整的实验平台（消融、方差分析、统计显著性），
# 只需要一张能并排看的表：同一个数据集、同一个判官、多个 RunVersion，
# 逐指标对比。够用且不多做。
#
# 对比口径必须与 Regression 一致（同一套方向性），
# 否则会出现「回归说没退步、实验表说退步」的荒唐场面。

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from .evaluator import RunResult
from .regression import is_higher_is_better

#: 实验表里展示的指标（顺序即列顺序）。
COMPARISON_METRICS: tuple[str, ...] = (
    "pass_rate",
    "critical_pass_rate",
    "mean_score",
    "mean_cost_tokens",
    "total_cost",
    "mean_latency_ms",
    "tool_calls_total",
)


@dataclass
class Variant:
    """一个实验变体（一份配置 + 它的评测结果）。"""

    name: str
    run_version_id: str = ""
    run: Optional[RunResult] = None
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "run_version_id": self.run_version_id,
            "run_id": self.run.run_id if self.run else "",
        }


@dataclass
class VariantComparison:
    """一个变体的对比结果。"""

    name: str
    run_version_id: str = ""
    metrics: dict[str, float] = field(default_factory=dict)
    #: 相对 baseline 的带符号相对变化。
    deltas: dict[str, float] = field(default_factory=dict)
    security_violations: int = 0
    passed_cases: int = 0
    total_cases: int = 0
    failed_case_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "run_version_id": self.run_version_id,
            "metrics": dict(self.metrics),
            "deltas": dict(self.deltas),
            "security_violations": self.security_violations,
            "passed_cases": self.passed_cases,
            "total_cases": self.total_cases,
            "failed_case_ids": list(self.failed_case_ids),
        }


@dataclass
class Experiment:
    """一次实验：多个变体跑同一份数据集。"""

    id: str = ""
    dataset_id: str = ""
    dataset_hash: str = ""
    variants: list[Variant] = field(default_factory=list)
    #: 作为对比基准的变体名；空则用第一个。
    baseline: str = ""
    created_at: float = 0.0

    def baseline_variant(self) -> Optional[Variant]:
        if not self.variants:
            return None
        if self.baseline:
            for v in self.variants:
                if v.name == self.baseline:
                    return v
        return self.variants[0]

    def compare(self) -> list[VariantComparison]:
        """逐变体算出指标与相对 baseline 的差异。"""
        base = self.baseline_variant()
        base_agg = (base.run.aggregate if base and base.run else {}) or {}
        out: list[VariantComparison] = []
        for v in self.variants:
            agg = (v.run.aggregate if v.run else {}) or {}
            metrics = {m: float(agg.get(m, 0.0) or 0.0) for m in COMPARISON_METRICS}
            deltas: dict[str, float] = {}
            for m, val in metrics.items():
                base_val = float(base_agg.get(m, 0.0) or 0.0)
                if base_val == 0.0:
                    deltas[m] = 0.0
                else:
                    deltas[m] = (val - base_val) / base_val
            out.append(VariantComparison(
                name=v.name,
                run_version_id=v.run_version_id,
                metrics=metrics,
                deltas=deltas,
                security_violations=int(agg.get("security_violations", 0) or 0),
                passed_cases=int(agg.get("passed_cases", 0) or 0),
                total_cases=int(agg.get("total_cases", 0) or 0),
                failed_case_ids=list(v.run.failed_case_ids) if v.run else [],
            ))
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "dataset_id": self.dataset_id,
            "dataset_hash": self.dataset_hash,
            "baseline": self.baseline,
            "created_at": self.created_at,
            "variants": [v.to_dict() for v in self.variants],
            "comparison": [c.to_dict() for c in self.compare()],
        }


def build_experiment(
    runs: Mapping[str, RunResult],
    *,
    dataset_id: str = "",
    dataset_hash: str = "",
    baseline: str = "",
    experiment_id: str = "",
) -> Experiment:
    """用 ``{变体名: RunResult}`` 组装一个实验。"""
    variants = [
        Variant(
            name=name,
            run_version_id=(r.run_version_id if r else ""),
            run=r,
        )
        for name, r in runs.items()
    ]
    return Experiment(
        id=experiment_id or f"exp_{int(time.time() * 1000)}",
        dataset_id=dataset_id,
        dataset_hash=dataset_hash,
        variants=variants,
        baseline=baseline,
        created_at=time.time(),
    )


def format_comparison_table(experiment: Experiment) -> str:
    """把实验对比渲染成一张文本表（CLI 用）。

    列的顺序固定，指标后面带 ``↑/↓`` 表示方向 ——
    看表的人不必记得「成本是越低越好」。
    """
    comparisons = experiment.compare()
    if not comparisons:
        return "（没有可对比的变体）"
    header = ["variant"] + [f"{m}{'↑' if is_higher_is_better(m) else '↓'}" for m in COMPARISON_METRICS]
    rows = []
    for c in comparisons:
        row = [c.name]
        for m in COMPARISON_METRICS:
            row.append(f"{c.metrics.get(m, 0.0):.4g}")
        rows.append(row)
    widths = [max(len(str(r[i])) for r in [header] + rows) for i in range(len(header))]
    lines = ["  ".join(str(h).ljust(widths[i]) for i, h in enumerate(header))]
    lines.append("  ".join("-" * w for w in widths))
    for row in rows:
        lines.append("  ".join(str(v).ljust(widths[i]) for i, v in enumerate(row)))
    return "\n".join(lines)
