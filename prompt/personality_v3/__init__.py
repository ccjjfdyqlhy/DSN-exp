# prompt/personality_v3/__init__.py
# PersonalitySystemV3 — 角色卡 · 蒸馏 · 动态生成

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional
import threading

from .character_card import CharacterCard, NaturalLanguage, CorpusEntry, ExperienceEntry, DynamicConfig
from .experience_importer import ExperienceImporter
from .distillation_engine import DistillationEngine, DistilledTraits
from .dynamic_synthesizer import DynamicSynthesizer, DynamicSnapshot, DEFAULT_MOOD
from .personality_generator import PersonalityPromptGenerator, DEFAULT_FALLBACK_PROMPT
from .personality_judge import PersonalityJudge, MoodUpdateResult
from .dynamics_engine import DynamicsEngine, DynamicsConfig
from .evidence_accumulator import EvidenceAccumulator
from .audit import AuditLogger, AuditEntry
from .state_manager import V3StateManager
from .persistence import V3Persistence
from .events import (
    PerceptionRecord,
    affinity_level as _shared_affinity_level,
    AFFINITY_THRESHOLDS as _AFFINITY_THRESHOLDS,
)
from .traits import (
    ALL_DIMENSIONS, TRAIT_MAP, TRAIT_IDS, CATEGORIES,
    default_indicator_vector, clamp_vector, deviant_dimensions, format_deviant_dimensions,
)

logger = logging.getLogger("PersonalitySystemV3")


class PersonalitySystemV3:
    def __init__(
        self,
        db=None,
        personality_model_chat=None,
        distillation_chat=None,
        fast_distillation_chat=None,
        default_card_path: str | None = None,
    ):
        logger.info("V3: 初始化 PersonalitySystemV3 (db=%s)", "available" if db else "none")
        self.db = db
        self._persistence = V3Persistence(db)
        self._evidence = EvidenceAccumulator(db)
        self._audit = AuditLogger(db)
        self._state_manager = V3StateManager(self._persistence, evidence=self._evidence)

        have_pm = personality_model_chat is not None
        logger.info("V3: 性格模型可用=%s", have_pm)
        self._generator = PersonalityPromptGenerator(personality_model_chat)
        self._judge = PersonalityJudge(personality_model_chat)
        self._dynamics = DynamicsEngine()

        have_dc = distillation_chat is not None
        have_fc = fast_distillation_chat is not None
        logger.info("V3: 蒸馏模型 main=%s fast=%s", have_dc, have_fc)
        self._distillation_engine = DistillationEngine(distillation_chat, fast_distillation_chat)
        self._experience_importer = ExperienceImporter(fast_distillation_chat or distillation_chat)

        self._default_card_path = default_card_path or str(
            Path(__file__).parent.parent.parent / "character_cards" / "exa.yaml"
        )
        logger.info("V3: 默认角色卡路径=%s", self._default_card_path)
        self._cards_dir = Path(__file__).parent.parent.parent / "character_cards"

        self._enabled = True
        self._distillation_pending: dict[str, bool] = {}
        self._distill_lock = threading.Lock()

    def init_tables(self) -> None:
        logger.info("V3: 开始初始化持久层表...")
        self._persistence.init_tables()
        self._evidence.init_tables()
        self._audit.init_tables()
        logger.info("V3: 持久层表初始化完成")

    def set_personality_model(self, chat) -> None:
        logger.info("V3: 设置性格模型客户端")
        self._generator.set_chat(chat)
        self._judge.set_chat(chat)

    def set_distillation_model(self, main_chat=None, fast_chat=None) -> None:
        logger.info("V3: 设置蒸馏模型 main=%s fast=%s", main_chat is not None, fast_chat is not None)
        self._distillation_engine.set_chats(main_chat, fast_chat)
        self._experience_importer.set_chat(fast_chat or main_chat)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        logger.info("V3: enabled=%s", value)
        self._enabled = value

    # === 角色卡管理 ===

    def load_default_card(self) -> CharacterCard | None:
        logger.info("V3: 加载默认角色卡 %s...", self._default_card_path)
        try:
            card = CharacterCard.from_yaml_file(self._default_card_path)
            logger.info("V3: 默认角色卡已加载 card_id=%s name=%s", card.card_id, card.name)
            return card
        except FileNotFoundError:
            logger.warning("V3: 默认角色卡文件不存在: %s", self._default_card_path)
            return None
        except Exception as e:
            logger.error("V3: 加载默认角色卡失败: %s", e, exc_info=True)
            return None

    def upload_card(self, card: CharacterCard) -> bool:
        logger.info("V3: 上传角色卡 card_id=%s name=%s", card.card_id, card.name)
        errors = card.validate()
        if errors:
            logger.error("V3: 角色卡校验失败: %s", errors)
            return False
        yaml_path = self._cards_dir / f"{card.card_id}.yaml"
        card.to_yaml_file(yaml_path)
        logger.info("V3: 角色卡已写入文件 card_id=%s path=%s", card.card_id, yaml_path)
        return True

    def get_card(self, card_id: str) -> CharacterCard | None:
        yaml_path = self._cards_dir / f"{card_id}.yaml"
        if not yaml_path.exists():
            logger.debug("V3: 角色卡文件不存在 card_id=%s path=%s", card_id, yaml_path)
            return None
        try:
            card = CharacterCard.from_yaml_file(yaml_path)
        except Exception as e:
            logger.warning("V3: 角色卡文件解析失败 card_id=%s: %s", card_id, e)
            return None
        logger.debug("V3: 角色卡已从文件加载 card_id=%s", card_id)
        return card

    def list_cards(self) -> list[dict]:
        cards = self._state_manager.list_cards()
        logger.debug("V3: 列出角色卡 count=%d", len(cards))
        return cards

    # === 蒸馏 ===

    def distill(self, card_id: str, model_name: str = "openai") -> DistilledTraits | None:
        logger.info("V3: 开始蒸馏 card_id=%s model=%s", card_id, model_name)

        self.import_pending_materials(card_id)

        card = self.get_card(card_id)
        if not card:
            logger.error("V3: 蒸馏失败 — 角色卡不存在 card_id=%s", card_id)
            return None

        existing = self._state_manager.load_distilled(card_id)
        fingerprint = card.compute_fingerprint()
        if existing and existing.content_fingerprint == fingerprint:
            logger.info("V3: 角色卡 %s 内容未变 (fingerprint=%s)，跳过蒸馏", card_id, fingerprint[:20])
            return existing

        logger.info("V3: 角色卡指纹已变 (new=%s)，执行蒸馏...", fingerprint[:20])

        # 蒸馏前备份
        self._backup_card(card)

        distilled = self._distillation_engine.run(card, model_name=model_name)
        self._state_manager.save_distillation(distilled)

        if distilled.foundation_description:
            card.distilled_description = distilled.foundation_description[:800]
        from datetime import datetime as _dt, timezone as _tz
        card.distilled_at = _dt.now(_tz.utc).isoformat()
        self.upload_card(card)

        self._generator.invalidate_cache()
        logger.info("V3: 蒸馏完成 distillation_id=%s version=%d dims=%d",
                     distilled.distillation_id, distilled.version,
                     len(distilled.indicator_vector))
        return distilled

    def get_distillation(self, card_id: str) -> DistilledTraits | None:
        d = self._state_manager.load_distilled(card_id)
        if d:
            logger.debug("V3: 获取蒸馏产物 card_id=%s version=%d", card_id, d.version)
        return d

    # === 经历素材导入 ===

    def import_experience(self, card_id: str, text: str, source: str = "") -> ExperienceEntry | None:
        logger.info("V3: 导入经历素材 card_id=%s source=%s len=%d", card_id, source, len(text))
        card = self.get_card(card_id)
        if not card:
            logger.error("V3: 导入失败 — 角色卡不存在 card_id=%s", card_id)
            return None

        entry = self._experience_importer.import_text(text, source)
        card.experiences.append(entry)
        self.upload_card(card)
        with self._distill_lock:
            self._distillation_pending[card_id] = True
        logger.info("V3: 素材已导入 card_id=%s total_experiences=%d distillation_pending=True",
                     card_id, len(card.experiences))
        return entry

    def import_pending_materials(self, card_id: str) -> int:
        materials_dir = self._cards_dir / "materials" / card_id
        if not materials_dir.exists():
            return 0
        card = self.get_card(card_id)
        if not card:
            return 0
        imported_files = {e.file for e in card.experiences if e.file}
        count = 0
        for f in sorted(materials_dir.glob("*.txt")):
            if str(f) in imported_files:
                continue
            logger.info("V3: 发现新素材 %s/%s", card_id, f.name)
            try:
                entry = self._experience_importer.import_file(str(f))
                card.experiences.append(entry)
                count += 1
            except Exception as e:
                logger.error("V3: 导入素材文件失败 %s: %s", f.name, e)
        if count > 0:
            self.upload_card(card)
            with self._distill_lock:
                self._distillation_pending[card_id] = True
            logger.info("V3: %s 导入了 %d 个素材文件，标记蒸馏待处理", card_id, count)
        return count

    def is_distillation_needed(self, card_id: str = None) -> bool:
        with self._distill_lock:
            if card_id:
                return self._distillation_pending.get(card_id, False)
            return any(self._distillation_pending.values())

    def mark_distillation_needed(self, card_id: str) -> None:
        with self._distill_lock:
            self._distillation_pending[card_id] = True

    def mark_distillation_done(self, card_id: str) -> None:
        with self._distill_lock:
            self._distillation_pending[card_id] = False

    # === 蒸馏回滚 ===

    def _backup_card(self, card) -> None:
        import json as _json
        from datetime import datetime as _dt, timezone as _tz
        backup_dir = Path(__file__).parent.parent.parent / "character_cards" / "backups" / card.card_id
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = _dt.now(_tz.utc).strftime("%Y%m%d_%H%M%S")
        yaml_path = backup_dir / f"{ts}.yaml"
        yaml_path.write_text(card.to_yaml(), encoding="utf-8")
        existing = self.get_distillation(card.card_id)
        if existing:
            json_path = backup_dir / f"{ts}.distilled.json"
            json_path.write_text(existing.to_json(), encoding="utf-8")
        logger.info("V3: 角色卡已备份 card_id=%s ts=%s", card.card_id, ts)

    def list_backups(self, card_id: str) -> list[dict]:
        from datetime import datetime as _dt
        backup_dir = Path(__file__).parent.parent.parent / "character_cards" / "backups" / card_id
        if not backup_dir.exists():
            return []
        results = []
        seen = set()
        for f in sorted(backup_dir.glob("*.yaml"), reverse=True):
            ts = f.stem
            if ts in seen:
                continue
            seen.add(ts)
            stat = f.stat()
            results.append({
                "timestamp": ts,
                "size": stat.st_size,
                "time": _dt.fromtimestamp(stat.st_mtime).isoformat(),
                "yaml": str(f),
            })
        return results

    def restore_backup(self, card_id: str, timestamp: str) -> bool:
        backup_dir = Path(__file__).parent.parent.parent / "character_cards" / "backups" / card_id
        yaml_path = backup_dir / f"{timestamp}.yaml"
        if not yaml_path.exists():
            logger.error("V3: 备份文件不存在: %s", yaml_path)
            return False
        try:
            from .character_card import CharacterCard
            card = CharacterCard.from_yaml_file(str(yaml_path))
            self.upload_card(card)
            self._generator.invalidate_cache()
            with self._distill_lock:
                self._distillation_pending[card_id] = True
            logger.info("V3: 角色卡已回滚 card_id=%s ts=%s", card_id, timestamp)
            return True
        except Exception as e:
            logger.error("V3: 回滚失败: %s", e)
            return False

    # === 用户绑定 ===

    def ensure_user_bound(self, uid: int) -> bool:
        bind = self._state_manager.get_or_create_binding(uid)
        if bind:
            logger.debug("V3: 用户已绑定角色卡 uid=%d card_id=%s", uid, bind.card_id)
            return True

        logger.info("V3: 用户 %d 未绑定角色卡，开始自动绑定默认卡...", uid)
        default = self.load_default_card()
        if not default:
            logger.error("V3: 无法绑定 — 默认角色卡不可用")
            return False

        self.upload_card(default)

        distilled = self._state_manager.load_distilled(default.card_id)
        if not distilled:
            logger.info("V3: 默认角色卡未有蒸馏产物，执行首次蒸馏...")
            try:
                distilled = self._distillation_engine.run(default)
                self._state_manager.save_distillation(distilled)
                if distilled.foundation_description:
                    default.distilled_description = distilled.foundation_description[:800]
                from datetime import datetime as _dt, timezone as _tz
                default.distilled_at = _dt.now(_tz.utc).isoformat()
                self.upload_card(default)
                logger.info("V3: 默认角色卡首次蒸馏完成 distillation_id=%s", distilled.distillation_id)
            except Exception as e:
                logger.warning("V3: 默认角色卡蒸馏失败 (将在首次使用性格模型时重试): %s", e)
                # 即使蒸馏失败也绑定用户，后续 generate/analyze 会回退

        self._state_manager.bind_user(uid, default.card_id, default.dynamic_config.seed)
        logger.info("V3: 用户 %d 已自动绑定默认角色卡 card_id=%s seed=%d (蒸馏=%s)",
                     uid, default.card_id, default.dynamic_config.seed,
                     "成功" if distilled else "待完成")
        return True

    def bind_user_card(self, uid: int, card_id: str) -> bool:
        logger.info("V3: 用户 %d 绑定角色卡 card_id=%s", uid, card_id)
        card = self.get_card(card_id)
        if not card:
            logger.warning("V3: 绑定失败 — 角色卡不存在 card_id=%s", card_id)
            return False
        ok = self._state_manager.bind_user(uid, card_id, card.dynamic_config.seed)
        logger.info("V3: 用户 %d 绑定角色卡结果=%s", uid, ok)
        return ok

    # === 性格提示词生成（主入口） ===

    def generate_personality_prompt(self, uid: int) -> str:
        if not self._enabled:
            logger.debug("V3: generate_personality_prompt 跳过 (enabled=False)")
            return ""

        self.ensure_user_bound(uid)

        snapshot = self._state_manager.get_current_snapshot(uid)
        if not snapshot:
            logger.warning("V3: 无法生成性格提示词 uid=%d — 无快照数据", uid)
            return DEFAULT_FALLBACK_PROMPT

        logger.debug("V3: 生成性格提示词 uid=%d card_id=%s interactions=%d affinity=%.0f",
                     uid, snapshot.card_id, snapshot.total_interactions, snapshot.affinity_value)
        result = self._generator.generate(snapshot)
        logger.debug("V3: 性格提示词已生成 uid=%d len=%d", uid, len(result))
        return result

    # === 交互分析（事件分类 + 确定性动力学 + 证据累积） ===

    def analyze_interaction(
        self,
        uid: int,
        user_message: str,
        ai_reply: str,
        conversation_history: str = "",
    ) -> MoodUpdateResult | None:
        if not self._enabled:
            logger.debug("V3: analyze_interaction 跳过 (enabled=False)")
            return None

        self.ensure_user_bound(uid)

        snapshot = self._state_manager.get_current_snapshot(uid)
        if not snapshot:
            logger.warning("V3: 无法分析交互 uid=%d — 无快照数据", uid)
            return None

        prev_mood = snapshot.mood_state
        prev_affinity = snapshot.affinity_value
        interactions = snapshot.total_interactions

        character_brief = snapshot.foundation_description[:1200]

        emotional_triggers = ""
        if snapshot.emotional_model:
            triggers = snapshot.emotional_model.get("triggers", [])
            emotional_triggers = "\n".join(
                f"- {t.get('stimulus','')} → {t.get('response','')}" for t in triggers[:8]
            )

        relation_dynamics = snapshot.relational_model.get("description", "") if snapshot.relational_model else ""

        rel_stage_label = self._affinity_level(prev_affinity).get("label", "")

        context_header = ""
        if rel_stage_label:
            context_header = f"当前与用户的关系阶段: {rel_stage_label}（亲密度 {prev_affinity:.0f}/100）\n"
        if conversation_history:
            context_header += conversation_history

        logger.debug("V3: 判定交互 uid=%d msglen=%d replylen=%d prev_affinity=%.1f",
                     uid, len(user_message), len(ai_reply), prev_affinity)

        # 1. LLM 只负责事件分类（语义判断，不产生数值）
        perception = self._judge.classify(
            user_message=user_message,
            ai_reply=ai_reply,
            previous_mood=prev_mood,
            previous_affinity=prev_affinity,
            interaction_count=interactions,
            character_brief=character_brief,
            emotional_triggers=emotional_triggers,
            relation_dynamics=relation_dynamics,
            conversation_history=context_header,
        )

        # 2. 确定性动力学引擎推演情绪/亲密度
        card = self.get_card(snapshot.card_id)
        trait_b3 = None
        baseline = None
        if card:
            distilled = self._state_manager.get_distillation_for_card(snapshot.card_id)
            if distilled:
                vec = distilled.indicator_vector or {}
                trait_b3 = vec.get("B3")
                b6 = vec.get("B6", 0.5)
                baseline = {
                    "joy": 0.2 + 0.6 * b6,
                    "sadness": 0.4 - 0.3 * b6,
                    "anger": 0.1,
                    "fear": 0.1,
                }

        days_since_last = self._state_manager.get_days_since_last(uid)
        result = self._dynamics.apply(
            perception=perception,
            previous_mood=prev_mood,
            previous_affinity=prev_affinity,
            baseline_mood=baseline,
            trait_b3=trait_b3,
            days_since_last=days_since_last,
        )

        # 3. 证据累积 → 缓慢演化 50 维特质
        self._accumulate_evidence(snapshot, perception)

        # 4. 审计日志: 记录本轮状态变化，可复盘/定位动力学问题
        self._audit.record(AuditEntry(
            event_type=perception.event_type,
            intensity=perception.intensity,
            signal=f"affinity_w={perception.affinity_weight():+.2f}",
            rule_id=result.rule_id,
            old_value=result.old_affinity,
            new_value=result.new_affinity,
            mood_before=result.old_mood,
            mood_after=result.new_mood,
            affinity_delta=result.affinity_delta,
            mood_delta=result.mood_delta,
            uid=uid,
            card_id=snapshot.card_id,
            analysis=perception.analysis,
        ))

        self._state_manager.on_interaction(uid, result.new_mood, result.new_affinity)

        # 5. 定期 consolidate 写回蒸馏产物
        self._maybe_consolidate(snapshot.card_id)

        d_joy = result.new_mood.get("joy", 0.5) - prev_mood.get("joy", 0.5)
        d_aff = result.new_affinity - prev_affinity
        logger.info(
            "V3: 人格交互 #%d uid=%d — 事件=%s/%s joy=%.2f→%.2f (%+.2f) affinity=%.1f→%.1f (%+.1f) %s",
            interactions + 1, uid,
            perception.event_type, perception.intensity,
            prev_mood.get("joy", 0.5), result.new_mood.get("joy", 0.5), d_joy,
            prev_affinity, result.new_affinity, d_aff,
            perception.analysis[:60] if perception.analysis else "",
        )

        return result

    def _accumulate_evidence(self, snapshot: DynamicSnapshot, perception: PerceptionRecord) -> None:
        card_id = snapshot.card_id
        distilled = self._state_manager.get_distillation_for_card(card_id)
        base_vector = (distilled.indicator_vector if distilled else {}) or {}
        self._evidence.add_evidence(card_id, perception, base_vector)
        if getattr(self._evidence, "_db", None) is not None:
            self._evidence.flush_card(card_id)

    def _maybe_consolidate(self, card_id: str) -> None:
        if not self._evidence.should_consolidate(card_id):
            return
        distilled_json_path = (
            Path(__file__).parent.parent.parent / "character_cards" / f"{card_id}.distilled.json"
        )
        merged = self._evidence.consolidate(card_id, distilled_json_path)
        if merged:
            self._state_manager.invalidate_distillation(card_id)
            self._generator.invalidate_cache()
            logger.info("V3: 人格演化已固化 card=%s（%d 条证据）", card_id,
                        self._evidence.get_total(card_id))

    # === 获取状态 ===

    def get_recent_events(self, uid: int = 0, card_id: str = "", limit: int = 30) -> list[dict]:
        """最近的人格状态变化事件流（审计）。"""
        try:
            return self._audit.recent(uid=uid, card_id=card_id, limit=limit)
        except Exception:
            return []

    def get_personality_status(self, uid: int) -> dict:
        self.ensure_user_bound(uid)
        snapshot = self._state_manager.get_current_snapshot(uid)
        if not snapshot:
            return {"uid": uid, "status": "no_data"}

        from .traits import vector_to_labels

        evidence_total = self._evidence.get_total(snapshot.card_id)
        plasticity = self._evidence.get_plasticity(snapshot.card_id)
        maturity = 1.0 - (sum(plasticity.values()) / len(plasticity) if plasticity else 1.0)

        return {
            "uid": uid,
            "card_id": snapshot.card_id,
            "total_interactions": snapshot.total_interactions,
            "mood": snapshot.mood_state,
            "affinity_value": snapshot.affinity_value,
            "affinity_level": self._affinity_level(snapshot.affinity_value),
            "labels": vector_to_labels(snapshot.indicator_vector),
            "evidence_total": evidence_total,
            "plasticity_avg": round(sum(plasticity.values()) / len(plasticity), 4) if plasticity else None,
            "maturity": round(maturity, 4),
            "recent_events": self.get_recent_events(uid=uid, limit=10),
        }

    def get_personality_full(self, uid: int) -> dict:
        self.ensure_user_bound(uid)
        snapshot = self._state_manager.get_current_snapshot(uid)
        if not snapshot:
            return {"uid": uid, "status": "no_data"}

        return {
            "uid": uid,
            "card_id": snapshot.card_id,
            "total_interactions": snapshot.total_interactions,
            "indicator_vector": snapshot.indicator_vector,
            "mood": snapshot.mood_state,
            "affinity_value": snapshot.affinity_value,
            "affinity_level": self._affinity_level(snapshot.affinity_value),
            "foundation_description": snapshot.foundation_description[:500],
            "behavioral_patterns": [
                {"name": p.get("name", ""), "description": p.get("description", "")}
                for p in snapshot.behavioral_patterns[:5]
            ],
            "speech_patterns": [
                {"name": p.get("name", ""), "description": p.get("description", "")}
                for p in snapshot.speech_patterns[:5]
            ],
        }

    def flush(self) -> None:
        logger.info("V3: flush 持久层")
        self._state_manager.flush()
        for card_id in list(getattr(self._evidence, "_mu", {}).keys()):
            self._evidence.flush_card(card_id)

    @staticmethod
    def _affinity_level(value: float) -> dict:
        """游戏式等级系统: 等级越高, 升级所需亲密度越多。上不封顶。"""
        return _shared_affinity_level(value)


__all__ = [
    "PersonalitySystemV3",
    "CharacterCard",
    "NaturalLanguage",
    "CorpusEntry",
    "ExperienceEntry",
    "DynamicConfig",
    "DistillationEngine",
    "DistilledTraits",
    "DynamicSynthesizer",
    "DynamicSnapshot",
    "DEFAULT_MOOD",
    "PersonalityPromptGenerator",
    "DEFAULT_FALLBACK_PROMPT",
    "PersonalityJudge",
    "MoodUpdateResult",
    "DynamicsEngine",
    "DynamicsConfig",
    "EvidenceAccumulator",
    "PerceptionRecord",
    "AuditLogger",
    "AuditEntry",
    "V3StateManager",
    "V3Persistence",
    "ExperienceImporter",
    "ALL_DIMENSIONS",
    "TRAIT_MAP",
    "TRAIT_IDS",
    "CATEGORIES",
    "default_indicator_vector",
    "clamp_vector",
    "deviant_dimensions",
    "format_deviant_dimensions",
]
