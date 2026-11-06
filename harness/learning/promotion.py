
# harness/learning/promotion.py
# 适配器的晋级与回滚：候选 → 暂存 → 生效 → 回滚。
#
# 为什么"训练完不等于上线"：
#   一次训练可能过拟合、可能只在这一批数据上好看、可能把某项能力练坏了。
#   所以训练产物只是**候选**，必须经过评测门槛才能进暂存区，
#   再由显式的晋级动作切到生效槽位。回滚永远只回退一步
#   （上一个生效版本），并且必须保留可回退的记录。
#
# 状态机（槽位视角）：
#   (空) ──promote(候选)──▶ 生效 ──promote(新候选)──▶ 生效(新)
#                                ◀──rollback───────────┘
#
# 数据落在 infra/finetune 的存储里（finetune_jobs / finetune_slots），
# 这一层只负责**策略**：够不够好、能不能进、要不要回退。

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from infra.finetune.base import JobState, TrainJob
from infra.finetune.store import FinetuneStore

logger = logging.getLogger("harness.learning.promotion")


@dataclass
class PromotionPolicy:
    """晋级门槛。"""

    #: 评测总分下限。
    min_score: float = 0.75
    #: 评测样本数下限（样本太少的高分不可信）。
    min_samples: int = 20
    #: 是否要求本地判官层也参与（避免只靠规则就上线）。
    require_local_judge: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_score": self.min_score,
            "min_samples": self.min_samples,
            "require_local_judge": self.require_local_judge,
        }


@dataclass
class PromotionDecision:
    """晋级决策结果。"""

    allowed: bool = False
    reason: str = ""
    score: float = 0.0
    samples: int = 0
    stages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "score": round(self.score, 4),
            "samples": self.samples,
            "stages": list(self.stages),
        }


class PromotionManager:
    """晋级管理器。"""

    def __init__(self, store: FinetuneStore, *, policy: Optional[PromotionPolicy] = None):
        self._store = store
        self.policy = policy or PromotionPolicy()

    # ── 评测 ──

    def evaluate_candidate(self, job_id: str, score: float, samples: int,
                           *, layers: Optional[dict] = None) -> PromotionDecision:
        """按门槛判断一个候选能不能进暂存区。"""
        decision = PromotionDecision(score=score, samples=samples)
        job = self._store.get_job(job_id)
        if job is None:
            decision.reason = f"作业不存在: {job_id}"
            return decision
        if job.state != JobState.SUCCEEDED:
            decision.reason = f"作业未成功: {job.state.value}"
            return decision
        if samples < self.policy.min_samples:
            decision.reason = f"样本数不足（{samples} < {self.policy.min_samples}）"
            return decision
        if score < self.policy.min_score:
            decision.reason = f"评分不足（{score:.3f} < {self.policy.min_score}）"
            return decision
        if self.policy.require_local_judge:
            if not layers or "local" not in layers:
                decision.reason = "缺少本地判官层的评分"
                return decision
        decision.allowed = True
        decision.reason = "通过门槛"
        decision.stages = ["candidate", "staged"]
        return decision

    # ── 晋级 / 回滚 ──

    def promote(self, job_id: str, slot: str, *, score: Optional[float] = None,
                samples: Optional[int] = None, layers: Optional[dict] = None,
                force: bool = False) -> dict[str, Any]:
        """把作业的适配器晋级为槽位的生效版本。

        force=True 时跳过门槛（用于紧急修复场景），但会在返回值里标注。
        """
        job = self._store.get_job(job_id)
        if job is None:
            raise ValueError(f"作业不存在: {job_id}")
        if job.state != JobState.SUCCEEDED:
            raise ValueError(f"作业未成功，不能晋级: {job_id} ({job.state.value})")

        decision = None
        if not force:
            if score is None or samples is None:
                raise ValueError("晋级必须提供 score 与 samples（或使用 force=True）")
            decision = self.evaluate_candidate(job_id, score, samples, layers=layers)
            if not decision.allowed:
                raise ValueError(f"不满足晋级门槛: {decision.reason}")

        result = self._store.promote(slot, job_id)
        result["forced"] = bool(force)
        result["decision"] = decision.to_dict() if decision else None
        logger.info("晋级 %s → 槽位 %s（forced=%s）", job_id, slot, force)
        return result

    def rollback(self, slot: str) -> dict[str, Any]:
        """回滚槽位到上一个生效版本。"""
        result = self._store.rollback(slot)
        logger.info("回滚槽位 %s → %s（成功=%s）", slot, result.get("job_id"),
                    result.get("rolled_back"))
        return result

    def active(self, slot: str) -> Optional[TrainJob]:
        """当前生效的作业。"""
        job_id = self._store.active(slot)
        return self._store.get_job(job_id) if job_id else None

    def history(self, slot: str) -> list[dict[str, Any]]:
        """槽位的历史（当前生效 + 上一个）。"""
        rows = self._store.execute(
            "SELECT slot, job_id, previous_job_id, promoted_at FROM finetune_slots WHERE slot = ?",
            (slot,),
        )
        return [dict(r) for r in rows]
