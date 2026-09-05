# prompt/personality_v3/state_manager.py
# 运行时状态管理 — 用户-角色卡绑定、状态缓存、交互协调
# 角色卡配置完全依赖 character_cards/ 目录下的 YAML 文件

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from .character_card import CharacterCard
from .distillation_engine import DistilledTraits
from .dynamic_synthesizer import DynamicSynthesizer, DynamicSnapshot, DEFAULT_MOOD
from .persistence import V3Persistence

logger = logging.getLogger("V3StateManager")

_DEFAULT_CHARACTER_CARD_ID = "exa"


def _default_cards_dir() -> Path:
    repo_root = Path(__file__).resolve().parent.parent.parent
    c1 = repo_root / "apps" / "dsn" / "character_cards"
    if c1.exists():
        return c1
    c2 = repo_root / "character_cards"
    if c2.exists():
        return c2
    return c1


class V3StateManager:
    def __init__(self, persistence: V3Persistence, evidence=None, cards_dir: Path | None = None):
        self._persistence = persistence
        self._evidence = evidence  # EvidenceAccumulator (可选), 用于稳定特质中心
        self._cards_dir = Path(cards_dir) if cards_dir else _default_cards_dir()
        self._cards_dir.mkdir(parents=True, exist_ok=True)
        self._synthesizer = DynamicSynthesizer()
        self._card_cache: dict[str, CharacterCard] = {}
        self._distillation_cache: dict[str, DistilledTraits] = {}
        self._snapshot_cache: dict[int, DynamicSnapshot] = {}
        self._user_bindings: dict[int, str] = {}
        logger.info("V3StateManager: 初始化完成 (cards_dir=%s)", self._cards_dir)

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
            logger.info("V3StateManager: 角色卡 %s 暂无蒸馏产物，生成默认基线蒸馏产物", card_id)
            initial_vector = card.get_adjusted_indicator_vector()
            distillation = DistilledTraits({
                "distillation_id": f"default_{card_id}",
                "card_id": card_id,
                "version": 1,
                "foundation_description": card.natural_language.combined() if card.natural_language else "",
                "indicator_vector": initial_vector,
            })
            self._distillation_cache[card_id] = distillation

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

        # 稳定特质中心: 优先使用人格演化后的证据 mu（若已累积），否则用蒸馏基线
        if self._evidence is not None:
            try:
                ev_mu = self._evidence.get_mu(card_id)
                if ev_mu:
                    snapshot.stable_indicator_vector = dict(ev_mu)
            except Exception:
                logger.warning("V3StateManager: 读取演化特质失败, 回退蒸馏基线")

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
        self._persistence.update_user_state(
            uid, card_id, interactions, new_affinity, new_mood,
            last_interaction_ts=datetime.now(timezone.utc).isoformat(),
        )
        self._invalidate_snapshot(uid)
        logger.debug("V3StateManager: on_interaction uid=%d interactions=%d affinity=%.1f",
                     uid, interactions, new_affinity)

    def get_distillation_for_card(self, card_id: str) -> DistilledTraits | None:
        dist = self._get_distillation(card_id)
        if dist:
            return dist
        # 若卡未蒸馏，以卡配置（含 manual_overrides）生成默认基线蒸馏对象供演化使用
        card = self._load_card(card_id)
        if card:
            initial_vector = card.get_adjusted_indicator_vector()
            return DistilledTraits({
                "distillation_id": f"default_{card_id}",
                "card_id": card_id,
                "version": 1,
                "foundation_description": card.natural_language.combined() if card.natural_language else "",
                "indicator_vector": initial_vector,
            })
        return None

    def invalidate_distillation(self, card_id: str) -> None:
        """consolidate 写回蒸馏产物后使缓存失效。"""
        self._distillation_cache.pop(card_id, None)
        self._snapshot_cache.clear()
        logger.debug("V3StateManager: 蒸馏缓存已失效 card_id=%s", card_id)

    def get_days_since_last(self, uid: int) -> float:
        """距上次交互的天数，用于亲密度遗忘。"""
        bind = self._persistence.get_user_active_card(uid)
        ts = (bind or {}).get("last_interaction_ts", "")
        if not ts:
            return 0.0
        try:
            from datetime import datetime as _dt, timezone as _tz
            last = _dt.fromisoformat(ts)
            if last.tzinfo is None:
                last = last.replace(tzinfo=_tz.utc)
            return max(0.0, (_dt.now(_tz.utc) - last).total_seconds() / 86400.0)
        except Exception:
            return 0.0

    def save_card(self, card: CharacterCard) -> None:
        yaml_path = self._cards_dir / f"{card.card_id}.yaml"
        card.to_yaml_file(yaml_path)
        self._card_cache[card.card_id] = card
        logger.info("V3StateManager: 角色卡已写入文件 card_id=%s path=%s", card.card_id, yaml_path)

    def save_distillation(self, traits: DistilledTraits) -> None:
        json_path = self._cards_dir / f"{traits.card_id}.distilled.json"
        json_path.write_text(traits.to_json(), encoding="utf-8")
        self._distillation_cache[traits.card_id] = traits
        logger.info("V3StateManager: 蒸馏产物已写文件 card_id=%s version=%d path=%s",
                     traits.card_id, traits.version, json_path.name)

    def list_cards(self) -> list[dict]:
        cards = []
        if not self._cards_dir.exists():
            return cards
        for yaml_path in sorted(self._cards_dir.glob("*.yaml")):
            try:
                card = CharacterCard.from_yaml_file(yaml_path)
                d = self._get_distillation(card.card_id)
                cards.append({
                    "card_id": card.card_id,
                    "name": card.name,
                    "display_name": card.display_name,
                    "version": card.version,
                    "author": card.author,
                    "distilled": d is not None,
                    "distilled_at": card.distilled_at,
                    "experience_count": len(card.experiences),
                })
            except Exception as e:
                logger.warning("V3StateManager: 解析角色卡文件失败 %s: %s", yaml_path.name, e)
        logger.debug("V3StateManager: 列出角色卡 count=%d", len(cards))
        return cards

    def load_distilled(self, card_id: str) -> DistilledTraits | None:
        return self._get_distillation(card_id)

    def _load_card(self, card_id: str) -> CharacterCard | None:
        if card_id in self._card_cache:
            return self._card_cache[card_id]
        yaml_path = self._cards_dir / f"{card_id}.yaml"
        if not yaml_path.exists():
            logger.debug("V3StateManager: 角色卡文件不存在 card_id=%s path=%s", card_id, yaml_path)
            return None
        try:
            card = CharacterCard.from_yaml_file(yaml_path)
        except Exception as e:
            logger.warning("V3StateManager: 角色卡文件解析失败 card_id=%s: %s", card_id, e)
            return None
        self._card_cache[card_id] = card
        logger.debug("V3StateManager: 角色卡已从文件加载 card_id=%s name=%s", card_id, card.name)
        return card

    def _get_distillation(self, card_id: str) -> DistilledTraits | None:
        if card_id in self._distillation_cache:
            return self._distillation_cache[card_id]
        json_path = self._cards_dir / f"{card_id}.distilled.json"
        if not json_path.exists():
            logger.debug("V3StateManager: 无蒸馏产物 card_id=%s", card_id)
            return None
        try:
            import json as _json
            data = _json.loads(json_path.read_text(encoding="utf-8"))
            traits = DistilledTraits(data)
            self._distillation_cache[card_id] = traits
            logger.debug("V3StateManager: 蒸馏产物从文件加载 card_id=%s version=%d",
                         card_id, traits.version)
            return traits
        except Exception as e:
            logger.warning("V3StateManager: 加载蒸馏文件失败 card_id=%s: %s", card_id, e)
            return None

    def _invalidate_snapshot(self, uid: int) -> None:
        self._snapshot_cache.pop(uid, None)

    def flush(self) -> None:
        logger.info("V3StateManager: flush 持久层")
        self._persistence.force_flush()
