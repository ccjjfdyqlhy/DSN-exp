# prompt/personality_v3/dynamics_engine.py
# 确定性动力学引擎 — 由结构化事件驱动情绪/亲密度演化
# 情绪: 冲量-回归模型  mood' = mood + impulse(event) − recovery·(mood − baseline)
# 亲密度: 饱和学习曲线 + 遗忘  affinity' = affinity + w·(cap−affinity)/cap − forget·affinity

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .events import (
    PerceptionRecord,
    affinity_level,
    affinity_stage_cap,
)
from .personality_judge import MoodUpdateResult

logger = logging.getLogger("DynamicsEngine")

DEFAULT_BASELINE_MOOD = {"joy": 0.5, "sadness": 0.2, "anger": 0.1, "fear": 0.15}

# 恢复速率（来自 B3 坚韧维度的映射）: 恢复率 = BASE + RANGE·B3
RECOVERY_BASE = 0.12
RECOVERY_RANGE = 0.38

# 情绪冲量缩放（sensitivity 来自角色卡 environment_sensitivity）
MOOD_GAIN_DEFAULT = 1.0

# 亲密度遗忘: 每日衰减率（仅在长期沉默时生效）
AFFINITY_FORGET_RATE = 0.004
# 遗忘启动前的宽限期（天）——短期沉默不影响关系
AFFINITY_FORGET_GRACE_DAYS = 3.0

# 单轮亲密度最大变化幅度（防止单轮剧烈跳动）
MAX_AFFINITY_DELTA = 12.0
# 单轮情绪最大变化幅度
MAX_MOOD_DELTA = 0.25


@dataclass
class DynamicsConfig:
    sensitivity: float = MOOD_GAIN_DEFAULT
    forget_rate: float = AFFINITY_FORGET_RATE
    forget_grace_days: float = AFFINITY_FORGET_GRACE_DAYS
    max_affinity_delta: float = MAX_AFFINITY_DELTA
    max_mood_delta: float = MAX_MOOD_DELTA


class DynamicsEngine:
    def __init__(self, config: DynamicsConfig | None = None):
        self._config = config or DynamicsConfig()

    def set_config(self, config: DynamicsConfig) -> None:
        self._config = config

    # === 公共入口 ===

    def apply(
        self,
        perception: PerceptionRecord,
        previous_mood: dict[str, float] | None = None,
        previous_affinity: float = 20.0,
        baseline_mood: dict[str, float] | None = None,
        recovery_rate: float | None = None,
        trait_b3: float | None = None,
        days_since_last: float = 0.0,
    ) -> MoodUpdateResult:
        """把一条语义事件推进为情绪/亲密度更新。"""
        prev_mood = dict(previous_mood or DEFAULT_BASELINE_MOOD)
        base = baseline_mood or DEFAULT_BASELINE_MOOD
        recovery = recovery_rate
        if recovery is None:
            recovery = self._recovery_from_b3(trait_b3 if trait_b3 is not None else 0.5)

        # ── 情绪: 冲量-回归 ──
        impulse = perception.mood_impulse()
        new_mood = {}
        for emo in ("joy", "sadness", "anger", "fear"):
            prev_v = prev_mood.get(emo, DEFAULT_BASELINE_MOOD.get(emo, 0.5))
            base_v = base.get(emo, DEFAULT_BASELINE_MOOD.get(emo, 0.5))
            regression = recovery * (prev_v - base_v)
            delta = impulse.get(emo, 0.0) * self._config.sensitivity - regression
            delta = max(-self._config.max_mood_delta, min(self._config.max_mood_delta, delta))
            new_mood[emo] = max(0.0, min(1.0, prev_v + delta))

        # ── 亲密度: 饱和学习曲线 + 遗忘 ──
        w = perception.affinity_weight()
        cap = affinity_stage_cap(previous_affinity)
        rule_id = "saturation_curve"
        if w >= 0:
            room = max(0.0, cap - previous_affinity)
            delta_aff = w * (room / max(cap, 1.0))
        else:
            # 负事件线性下降（不受饱和曲线约束）
            rule_id = "linear_decay"
            delta_aff = w
        delta_aff = max(-self._config.max_affinity_delta, min(self._config.max_affinity_delta, delta_aff))
        new_affinity = previous_affinity + delta_aff

        # 遗忘: 超过宽限期后按日衰减
        forget_days = max(0.0, days_since_last - self._config.forget_grace_days)
        if forget_days > 0:
            new_affinity -= new_affinity * self._config.forget_rate * forget_days
            rule_id += "+forgetting"
        new_affinity = max(0.0, new_affinity)

        # ── 校验 ──
        self._validate(new_mood, prev_mood, delta_aff)

        mood_delta = {emo: new_mood[emo] - prev_mood.get(emo, 0.5) for emo in ("joy", "sadness", "anger", "fear")}
        lvl = affinity_level(new_affinity)
        return MoodUpdateResult(
            old_mood=prev_mood,
            new_mood=new_mood,
            old_affinity=previous_affinity,
            new_affinity=new_affinity,
            analysis=perception.analysis,
            affinity_reason=(
                f"事件[{perception.event_type}/{perception.intensity}] "
                f"权重{w:+.2f} 曲线Δ{delta_aff:+.2f}"
            ),
            behavioral_advice="",
            new_level_description=lvl.get("label", ""),
            affinity_delta=new_affinity - previous_affinity,
            mood_delta=mood_delta,
            rule_id=rule_id,
        )

    # === 内部 ===

    @staticmethod
    def _recovery_from_b3(b3: float) -> float:
        """B3 坚韧(高)→恢复快。recovery = RECOVERY_BASE + RECOVERY_RANGE·B3"""
        return RECOVERY_BASE + RECOVERY_RANGE * max(0.0, min(1.0, b3))

    @staticmethod
    def _validate(new_mood: dict, prev_mood: dict, delta_aff: float) -> None:
        for emo in ("joy", "sadness", "anger", "fear"):
            delta = new_mood.get(emo, 0.5) - prev_mood.get(emo, 0.5)
            if abs(delta) > MAX_MOOD_DELTA + 1e-6:
                logger.warning("动力学校验: 情绪 %s Δ=%.3f 超出上限", emo, delta)
        if abs(delta_aff) > MAX_AFFINITY_DELTA + 1e-6:
            logger.warning("动力学校验: 亲密度 Δ=%.2f 超出上限", delta_aff)
