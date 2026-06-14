# prompt/personality_v3/dynamic_synthesizer.py
# 动态人格合成器 — 种子噪声 + 情绪调制 + 时间漂移 + 亲密度调制

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Optional

from .traits import TRAIT_IDS, DIMENSION_COUNT

logger = logging.getLogger("DynamicSynthesizer")


@dataclass
class DynamicSnapshot:
    card_id: str = ""
    indicator_vector: dict[str, float] = field(default_factory=dict)
    foundation_description: str = ""
    behavioral_patterns: list[dict] = field(default_factory=list)
    speech_patterns: list[dict] = field(default_factory=list)
    emotional_model: dict = field(default_factory=dict)
    relational_model: dict = field(default_factory=dict)
    trait_narrative: dict[str, str] = field(default_factory=dict)
    timestamp: float = 0.0
    mood_state: dict[str, float] = field(default_factory=dict)
    affinity_value: float = 20.0
    total_interactions: int = 0


DEFAULT_MOOD = {
    "joy": 0.5, "sadness": 0.2, "anger": 0.1,
    "fear": 0.15, "disgust": 0.05, "surprise": 0.1, "neutral": 0.5,
}

B_EMOTIONAL_EXPRESSIVENESS_IDX = 6
B_RESILIENCE_IDX = 8
B6_DOMINANT_MOOD_IDX = 11
H_PROACTIVITY_IDX = 45
H_PATIENCE_IDX = 46
H_RISK_TAKING_IDX = 49

D_AFFILIATION_NEED_IDX = 17
D_SOCIAL_INITIATIVE_IDX = 19
D_TRUST_IDX = 20
G_INTIMACY_CAPACITY_IDX = 40
E_VERBOSITY_IDX = 25
E_FORMALITY_IDX = 32


class DynamicSynthesizer:
    def __init__(self):
        logger.debug("DynamicSynthesizer: 初始化完成")

    def synthesize(
        self,
        distilled_indicator_vector: dict[str, float],
        foundation_description: str = "",
        behavioral_patterns: list[dict] | None = None,
        speech_patterns: list[dict] | None = None,
        emotional_model: dict | None = None,
        relational_model: dict | None = None,
        trait_narrative: dict[str, str] | None = None,
        seed: int = 42,
        amplitude: float = 0.12,
        volatility: float = 0.15,
        inertia: float = 0.35,
        total_interactions: int = 0,
        drift_rate: float = 0.02,
        mood_state: dict[str, float] | None = None,
        affinity_value: float = 20.0,
        card_id: str = "",
    ) -> DynamicSnapshot:
        vec = dict(distilled_indicator_vector)
        for tid in TRAIT_IDS:
            if tid not in vec:
                vec[tid] = 0.5

        mood = dict(mood_state or DEFAULT_MOOD)

        logger.debug("DynamicSynthesizer: 合成开始 card=%s interactions=%d affinity=%.0f "
                     "amplitude=%.2f volatility=%.2f drift=%.4f",
                     card_id, total_interactions, affinity_value,
                     amplitude, volatility, drift_rate)

        noise = self._generate_noise_vector(seed, amplitude)
        for tid, n in zip(TRAIT_IDS, noise):
            vec[tid] = max(0.0, min(1.0, vec[tid] + n))

        vec = self._apply_mood_modulation(vec, mood, volatility)
        vec = self._apply_temporal_drift(vec, total_interactions, drift_rate, seed)
        vec = self._apply_affinity_modulation(vec, affinity_value)

        snapshot = DynamicSnapshot(
            card_id=card_id,
            indicator_vector=vec,
            foundation_description=foundation_description,
            behavioral_patterns=behavioral_patterns or [],
            speech_patterns=speech_patterns or [],
            emotional_model=emotional_model or {},
            relational_model=relational_model or {},
            trait_narrative=trait_narrative or {},
            timestamp=time.time(),
            mood_state=mood,
            affinity_value=affinity_value,
            total_interactions=total_interactions,
        )

        logger.debug("DynamicSynthesizer: 合成完成 card=%s dims=%d",
                     card_id, len(vec))
        return snapshot

    def _generate_noise_vector(self, seed: int, amplitude: float) -> list[float]:
        period = int(time.time() // 3600)
        rng = random.Random(f"dsn_pv3_{seed}_{period}")
        noise = [rng.uniform(-amplitude, amplitude) for _ in range(DIMENSION_COUNT)]
        return noise

    def _apply_mood_modulation(
        self, vec: dict[str, float], mood: dict[str, float], volatility: float
    ) -> dict[str, float]:
        result = dict(vec)
        tids = TRAIT_IDS

        joy = mood.get("joy", 0.5)
        sadness = mood.get("sadness", 0.2)
        anger = mood.get("anger", 0.1)

        b2 = tids[B_EMOTIONAL_EXPRESSIVENESS_IDX]
        result[b2] = max(0.0, min(1.0, result[b2] + joy * 0.2 * volatility))

        b3 = tids[B_RESILIENCE_IDX]
        result[b3] = max(0.0, min(1.0, result[b3] - sadness * 0.15 * volatility))

        b6 = tids[B6_DOMINANT_MOOD_IDX]
        result[b6] = max(0.0, min(1.0, result[b6] + (joy - sadness) * 0.3 * volatility))

        h1 = tids[H_PROACTIVITY_IDX]
        result[h1] = max(0.0, min(1.0, result[h1] + joy * 0.15 * volatility))

        h2 = tids[H_PATIENCE_IDX]
        result[h2] = max(0.0, min(1.0, result[h2] - anger * 0.25 * volatility))

        h4 = tids[H_RISK_TAKING_IDX]
        result[h4] = max(0.0, min(1.0, result[h4] + joy * 0.1 * volatility))

        a5 = tids[4]
        result[a5] = max(0.0, min(1.0, result[a5] + sadness * 0.2 * volatility))

        return result

    def _apply_temporal_drift(
        self, vec: dict[str, float], total_interactions: int, drift_rate: float, seed: int
    ) -> dict[str, float]:
        result = dict(vec)
        rng = random.Random(f"dsn_drift_{seed}")
        drift_amount = drift_rate * (total_interactions ** 0.5) * 0.01
        for i, tid in enumerate(TRAIT_IDS):
            direction = rng.uniform(-0.5, 0.5)
            result[tid] = max(0.0, min(1.0, result[tid] + direction * drift_amount))
        return result

    def _apply_affinity_modulation(
        self, vec: dict[str, float], affinity_value: float
    ) -> dict[str, float]:
        result = dict(vec)
        norm = affinity_value / 100.0
        tids = TRAIT_IDS

        d1 = tids[D_AFFILIATION_NEED_IDX]
        result[d1] = max(0.0, min(1.0, result[d1] + norm * 0.3))

        d3 = tids[D_SOCIAL_INITIATIVE_IDX]
        result[d3] = max(0.0, min(1.0, result[d3] + norm * 0.25))

        d4 = tids[D_TRUST_IDX]
        result[d4] = max(0.0, min(1.0, result[d4] + norm * 0.2))

        g1 = tids[G_INTIMACY_CAPACITY_IDX]
        result[g1] = max(0.0, min(1.0, result[g1] + norm * 0.3))

        e1 = tids[E_VERBOSITY_IDX]
        result[e1] = max(0.0, min(1.0, result[e1] + norm * 0.15))

        e8 = tids[E_FORMALITY_IDX]
        result[e8] = max(0.0, min(1.0, result[e8] - norm * 0.3))

        return result
