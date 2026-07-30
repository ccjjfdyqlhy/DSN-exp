# prompt/personality_v3/dynamic_synthesizer.py
# 动态人格合成器 — 种子噪声 + 情绪调制 + 时间漂移 + 亲密度调制

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field

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

B_EMOTIONAL_EXPRESSIVENESS_ID = "B2"
B_RESILIENCE_ID = "B3"
B6_DOMINANT_MOOD_ID = "B6"
H_PROACTIVITY_ID = "H1"
H_PATIENCE_ID = "H2"
H_RISK_TAKING_ID = "H4"
A_NEUROTICISM_ID = "A5"

D_AFFILIATION_NEED_ID = "D1"
D_SOCIAL_INITIATIVE_ID = "D3"
D_TRUST_ID = "D4"
G_INTIMACY_CAPACITY_ID = "G1"
E_VERBOSITY_ID = "E1"
E_FORMALITY_ID = "E8"


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

        joy = mood.get("joy", 0.5)
        sadness = mood.get("sadness", 0.2)
        anger = mood.get("anger", 0.1)

        result[B_EMOTIONAL_EXPRESSIVENESS_ID] = max(
            0.0, min(1.0, result.get(B_EMOTIONAL_EXPRESSIVENESS_ID, 0.5) + joy * 0.2 * volatility))
        result[B_RESILIENCE_ID] = max(
            0.0, min(1.0, result.get(B_RESILIENCE_ID, 0.5) - sadness * 0.15 * volatility))
        result[B6_DOMINANT_MOOD_ID] = max(
            0.0, min(1.0, result.get(B6_DOMINANT_MOOD_ID, 0.5) + (joy - sadness) * 0.3 * volatility))
        result[H_PROACTIVITY_ID] = max(
            0.0, min(1.0, result.get(H_PROACTIVITY_ID, 0.5) + joy * 0.15 * volatility))
        result[H_PATIENCE_ID] = max(
            0.0, min(1.0, result.get(H_PATIENCE_ID, 0.5) - anger * 0.25 * volatility))
        result[H_RISK_TAKING_ID] = max(
            0.0, min(1.0, result.get(H_RISK_TAKING_ID, 0.5) + joy * 0.1 * volatility))
        result[A_NEUROTICISM_ID] = max(
            0.0, min(1.0, result.get(A_NEUROTICISM_ID, 0.5) + sadness * 0.2 * volatility))

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

        result[D_AFFILIATION_NEED_ID] = max(
            0.0, min(1.0, result.get(D_AFFILIATION_NEED_ID, 0.5) + norm * 0.3))
        result[D_SOCIAL_INITIATIVE_ID] = max(
            0.0, min(1.0, result.get(D_SOCIAL_INITIATIVE_ID, 0.5) + norm * 0.25))
        result[D_TRUST_ID] = max(
            0.0, min(1.0, result.get(D_TRUST_ID, 0.5) + norm * 0.2))
        result[G_INTIMACY_CAPACITY_ID] = max(
            0.0, min(1.0, result.get(G_INTIMACY_CAPACITY_ID, 0.5) + norm * 0.3))
        result[E_VERBOSITY_ID] = max(
            0.0, min(1.0, result.get(E_VERBOSITY_ID, 0.5) + norm * 0.15))
        result[E_FORMALITY_ID] = max(
            0.0, min(1.0, result.get(E_FORMALITY_ID, 0.5) - norm * 0.3))

        return result
