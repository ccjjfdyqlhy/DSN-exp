# prompt/personality_v3/state_manager.py
# 运行时状态管理 — 用户-角色卡绑定、状态缓存、交互协调

from __future__ import annotations

import logging
from typing import Optional

from .character_card import CharacterCard
from .distillation_engine import DistilledTraits
from .dynamic_synthesizer import DynamicSynthesizer, DynamicSnapshot, DEFAULT_MOOD
from .persistence import V3Persistence

logger = logging.getLogger("V3StateManager")

_DEFAULT_CHARACTER_CARD_ID = "exa"


class V3StateManager:
    def __init__(self, persistence: V3Persistence):
        self._persistence = persistence
        self._synthesizer = DynamicSynthesizer()
        self._card_cache: dict[str, CharacterCard] = {}
        self._distillation_cache: dict[str, DistilledTraits] = {}
        self._snapshot_cache: dict[int, DynamicSnapshot] = {}
        self._user_bindings: dict[int, str] = {}
        logger.info("V3StateManager: 初始化完成")

    def get_or_create_binding(self, uid: int) -> CharacterCard | None:
        bind = self._persistence.get_user_active_card(uid)
        if bind:
            card_id = bind.get("card_id", "")
            if card_id:
                self._user_bindings[uid] = card_id
                logger.debug("V3StateManager: 用户 %d 已有绑定 card_id=%s", uid, card_id)
                return self._load_card(card_id)
        logger.debug("V3StateManager: 用户 %d 无绑定记录", uid)
        return None

    def bind_user(self, uid: int, card_id: str, seed: int = 42) -> bool:
        logger.info("V3StateManager: 绑定用户 uid=%d card_id=%s seed=%d", uid, card_id, seed)
        card = self._load_card(card_id)
        if not card:
            logger.warning("V3StateManager: 角色卡不可用 card_id=%s", card_id)
            return False
        distillation = self._get_distillation(card_id)
        dist_id = distillation.distillation_id if distillation else ""
        logger.info("V3StateManager: 蒸馏产物 %s", "可用" if distillation else "缺失")
        self._persistence.bind_user_card(uid, card_id, dist_id, seed)
        self._user_bindings[uid] = card_id
        self._invalidate_snapshot(uid)
        return True

    def get_current_snapshot(self, uid: int) -> DynamicSnapshot | None:
        if uid in self._snapshot_cache:
            logger.debug("V3StateManager: 从缓存获取快照 uid=%d", uid)
            return self._snapshot_cache[uid]

        card_id = self._user_bindings.get(uid)
        if not card_id:
            bind = self.get_or_create_binding(uid)
            if not bind:
                logger.warning("V3StateManager: 用户 %d 无绑定，无法生成快照", uid)
                return None
            card_id = bind.card_id

        card = self._load_card(card_id)
        if not card:
            logger.warning("V3StateManager: 角色卡 %s 不可用, 无法生成快照", card_id)
            return None

        distillation = self._get_distillation(card_id)
        if not distillation:
            logger.warning("V3StateManager: 角色卡 %s 无蒸馏产物, 无法生成快照", card_id)
            return None

        bind = self._persistence.get_user_active_card(uid)
        if not bind:
            logger.warning("V3StateManager: 数据库无用户 %d 绑定记录", uid)
            return None

        dcfg = card.dynamic_config
        mood = bind.get("mood_state_json", {}) or DEFAULT_MOOD
        affinity = bind.get("affinity_value", 20.0)
        interactions = bind.get("total_interactions", 0)
        seed = bind.get("seed", dcfg.seed)
        bias = dcfg.response_inertia

        logger.debug("V3StateManager: 合成快照 uid=%d card=%s interactions=%d affinity=%.0f",
                     uid, card_id, interactions, affinity)

        snapshot = self._synthesizer.synthesize(
            distilled_indicator_vector=distillation.indicator_vector,
            foundation_description=distillation.foundation_description,
            behavioral_patterns=distillation.behavioral_patterns,
            speech_patterns=distillation.speech_patterns,
            emotional_model=distillation.emotional_model,
            relational_model=distillation.relational_model,
            trait_narrative=distillation.trait_narrative,
            seed=seed,
            amplitude=dcfg.noise_amplitude,
            volatility=dcfg.mood_volatility,
            inertia=bias,
            total_interactions=interactions,
            drift_rate=dcfg.temporal_drift_rate,
            mood_state=mood,
            affinity_value=affinity,
            card_id=card_id,
        )

        self._snapshot_cache[uid] = snapshot
        return snapshot

    def on_interaction(self, uid: int, new_mood: dict, new_affinity: float) -> None:
        card_id = self._user_bindings.get(uid)
        if not card_id:
            logger.warning("V3StateManager: on_interaction 跳过 — 用户 %d 无绑定", uid)
            return

        bind = self._persistence.get_user_active_card(uid)
        if not bind:
            logger.warning("V3StateManager: on_interaction 跳过 — 数据库无用户 %d 记录", uid)
            return

        interactions = bind.get("total_interactions", 0) + 1
        self._persistence.update_user_state(uid, card_id, interactions, new_affinity, new_mood)
        self._invalidate_snapshot(uid)
        logger.debug("V3StateManager: on_interaction uid=%d interactions=%d affinity=%.1f",
                     uid, interactions, new_affinity)

    def get_distillation_for_card(self, card_id: str) -> DistilledTraits | None:
        return self._get_distillation(card_id)

    def save_card(self, card: CharacterCard) -> None:
        yaml_str = card.to_yaml()
        self._persistence.save_card(card.card_id, yaml_str)
        self._card_cache[card.card_id] = card
        logger.info("V3StateManager: 角色卡已缓存 card_id=%s", card.card_id)

    def save_distillation(self, traits: DistilledTraits) -> None:
        self._persistence.save_distillation(
            traits.distillation_id,
            traits.card_id,
            traits.version,
            traits.content_fingerprint,
            traits.model_used,
            traits.to_json(),
        )
        self._distillation_cache[traits.card_id] = traits
        logger.info("V3StateManager: 蒸馏产物已缓存 card_id=%s version=%d fingerprint=%s",
                     traits.card_id, traits.version, traits.content_fingerprint[:20])

    def list_cards(self) -> list[dict]:
        return self._persistence.list_cards()

    def load_distilled(self, card_id: str) -> DistilledTraits | None:
        return self._get_distillation(card_id)

    def _load_card(self, card_id: str) -> CharacterCard | None:
        if card_id in self._card_cache:
            return self._card_cache[card_id]
        yaml_str = self._persistence.load_card_yaml(card_id)
        if not yaml_str:
            logger.debug("V3StateManager: 角色卡 YAML 未找到 card_id=%s", card_id)
            return None
        card = CharacterCard.from_yaml_string(yaml_str)
        self._card_cache[card_id] = card
        logger.debug("V3StateManager: 角色卡已加载 card_id=%s name=%s", card_id, card.name)
        return card

    def _get_distillation(self, card_id: str) -> DistilledTraits | None:
        if card_id in self._distillation_cache:
            return self._distillation_cache[card_id]
        row = self._persistence.load_distillation(card_id)
        if not row:
            logger.debug("V3StateManager: 无蒸馏产物 card_id=%s", card_id)
            return None
        json_content = row.get("json_content", {})
        if isinstance(json_content, str):
            import json
            json_content = json.loads(json_content)
        traits = DistilledTraits(json_content)
        self._distillation_cache[card_id] = traits
        logger.debug("V3StateManager: 蒸馏产物已加载 card_id=%s version=%d",
                     card_id, traits.version)
        return traits

    def _invalidate_snapshot(self, uid: int) -> None:
        self._snapshot_cache.pop(uid, None)

    def flush(self) -> None:
        logger.info("V3StateManager: flush 持久层")
        self._persistence.force_flush()
