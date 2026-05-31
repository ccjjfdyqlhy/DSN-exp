# prompt/personality_v2/__init__.py
# PersonalitySystemV2 — 情绪·亲和·习性三模块人格系统

from __future__ import annotations

import json
import logging
from typing import Optional

from .emotion import (
    EmotionModule,
    EmotionalStimulus,
    MoodProfile,
    StimulusAnalyzer,
)
from .affinity import (
    AffinityModule,
    ActionClassifier,
    AFFINITY_LEVELS,
)
from .habit import (
    HabitModule,
    Habit,
    PatternObserver,
)
from .persistence import PersonalityStateStore, CREATE_PERSONALITY_TABLE

logger = logging.getLogger("PersonalitySystemV2")


class PersonalitySystemV2:
    """
    人格系统 v2 — 统一入口。

    三个模块:
      - EmotionModule: 5 种情绪向量 (JOLY/SORW/ANGR/FEAR/META)
      - AffinityModule: 0~100 好感值 + 社交行为
      - HabitModule: 先天+后天双层习性

    每个用户独立状态 (按 uid 隔离)，持久化到 SQLite。
    """

    def __init__(self, db=None, presets_dir: str | None = None):
        self._db = db
        self._presets_dir = presets_dir
        self._store = PersonalityStateStore(db)
        self._presets: dict[str, dict] = {}

        self._stimulus_rules: list[dict] = []
        self._affinity_rules: list[dict] = []

        self._user_cache: dict[int, dict] = {}

    def init_table(self) -> None:
        self._store.init_table()

    def scan_presets(self, directory: str | None = None) -> int:
        import yaml
        from pathlib import Path

        d = Path(directory or self._presets_dir or "prompt/prompts/personality")
        if not d.exists():
            return 0

        count = 0
        for f in sorted(d.glob("*.yaml")):
            try:
                preset = yaml.safe_load(f.read_text(encoding="utf-8-sig"))
                name = preset.get("name", f.stem)
                self._presets[name] = preset
                count += 1
            except Exception as e:
                logger.error("加载性格预设失败 %s: %s", f, e)

        logger.info("v2 加载了 %d 个性格预设", count)
        return count

    def load_preset(self, uid: int, name: str) -> bool:
        preset = self._presets.get(name)
        if not preset:
            logger.warning("性格预设不存在: %s", name)
            return False

        self._store.ensure_exists(uid, name)

        emotion_baseline = preset.get("emotion_baseline", {})
        emotion_inertia = preset.get("emotion_inertia", {})

        emotion = EmotionModule()
        emotion.reset(baselines=emotion_baseline, inertia=emotion_inertia)

        affinity_config = preset.get("affinity", {})
        affinity = AffinityModule()
        affinity.reset(
            initial=affinity_config.get("initial", 20.0),
            decay_enabled=affinity_config.get("decay_enabled", False),
        )

        habit = HabitModule()
        habit.load_innate(preset.get("innate_habits", {}))
        learning = preset.get("learning", {})
        habit.innate_weight = learning.get("innate_weight_init", 1.0)

        self._user_cache[uid] = {
            "emotion": emotion,
            "affinity": affinity,
            "habit": habit,
            "preset_name": name,
            "total_interactions": 0,
        }

        logger.info("用户 %d 已切换性格预设: %s", uid, preset.get("display_name", name))
        return True

    def get_or_load_user(self, uid: int) -> dict:
        if uid in self._user_cache:
            return self._user_cache[uid]

        row = self._store.load(uid)
        if row is not None:
            emotion = EmotionModule.from_dict({
                "values": {
                    "joly": row["joly"], "sorw": row["sorw"],
                    "angr": row["angr"], "fear": row["fear"], "meta": row["meta"],
                },
                "baselines": {
                    "joly": row["joly_baseline"], "sorw": row["sorw_baseline"],
                    "angr": row["angr_baseline"], "fear": row["fear_baseline"],
                    "meta": row["meta_baseline"],
                },
                "inertia": json.loads(row["emotion_inertia_json"]),
            })
            affinity = AffinityModule.from_dict({
                "value": row["affinity"],
                **json.loads(row["affinity_extra_json"]),
            })
            habit = HabitModule.from_list(json.loads(row["habits_json"]))
            habit.innate_weight = row["innate_weight"]
            habit.total_interactions = row["total_interactions"]

            user_state = {
                "emotion": emotion,
                "affinity": affinity,
                "habit": habit,
                "preset_name": row["preset_name"],
                "total_interactions": row["total_interactions"],
            }
            self._user_cache[uid] = user_state
            return user_state

        return self._create_default(uid)

    def _create_default(self, uid: int) -> dict:
        self._store.ensure_exists(uid)
        emotion = EmotionModule()
        affinity = AffinityModule()
        habit = HabitModule()

        user_state = {
            "emotion": emotion,
            "affinity": affinity,
            "habit": habit,
            "preset_name": "default",
            "total_interactions": 0,
        }
        self._user_cache[uid] = user_state
        return user_state

    def load_rules(self, stimulus_rules: list[dict] | None = None,
                   affinity_rules: list[dict] | None = None) -> None:
        if stimulus_rules:
            self._stimulus_rules = stimulus_rules
        if affinity_rules:
            self._affinity_rules = affinity_rules

    def load_rules_from_files(self, stimulus_path: str | None = None,
                               affinity_path: str | None = None) -> None:
        import yaml
        from pathlib import Path
        pkg_dir = Path(__file__).parent

        if stimulus_path:
            sp = Path(stimulus_path)
        else:
            sp = pkg_dir / "stimulus_rules.yaml"
        if sp.exists():
            try:
                data = yaml.safe_load(sp.read_text(encoding="utf-8-sig"))
                self._stimulus_rules = data.get("rules", [])
                logger.info("加载情绪刺激规则: %d 条", len(self._stimulus_rules))
            except Exception as e:
                logger.error("加载情绪刺激规则失败: %s", e)

        if affinity_path:
            ap = Path(affinity_path)
        else:
            ap = pkg_dir / "affinity_rules.yaml"
        if ap.exists():
            try:
                data = yaml.safe_load(ap.read_text(encoding="utf-8-sig"))
                self._affinity_rules = data.get("actions", [])
                logger.info("加载亲和力规则: %d 条", len(self._affinity_rules))
            except Exception as e:
                logger.error("加载亲和力规则失败: %s", e)

    def on_interaction(self, uid: int, user_message: str,
                       is_positive: bool = True) -> dict:
        """
        每次用户交互后调用。

        返回本次交互的人格变化摘要，供日志/monitor 使用。
        """
        state = self.get_or_load_user(uid)
        state["total_interactions"] += 1

        emotion: EmotionModule = state["emotion"]
        affinity: AffinityModule = state["affinity"]
        habit: HabitModule = state["habit"]

        stim_analyzer = StimulusAnalyzer(self._stimulus_rules)
        stimulus = stim_analyzer.analyze(user_message, is_positive)
        emotion.apply_stimulus(stimulus)
        mood = emotion.get_mood_profile()

        act_classifier = ActionClassifier(self._affinity_rules)
        actions = act_classifier.classify(user_message)
        affinity_deltas = []
        for action in actions:
            delta = affinity.apply_action(action)
            if abs(delta) > 0.01:
                affinity_deltas.append((action["id"], delta))

        observer = PatternObserver(window=20)
        observer.feed(user_message)
        candidates = observer.observe()
        habit.add_candidates(candidates)

        habit.increment_interactions()

        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        self._store.save(
            uid=uid,
            emotion_dict=emotion.to_dict(),
            affinity_dict=affinity.to_dict(),
            habits_list=habit.to_list(),
            preset_name=state["preset_name"],
            total_interactions=state["total_interactions"],
            innate_weight=habit.innate_weight,
            last_interaction=now_iso,
        )

        result = {
            "stimulus": stimulus.to_dict(),
            "mood": mood,
            "display_emotion": emotion.get_display_emotion(),
            "affinity_changes": affinity_deltas,
            "affinity_value": affinity.value,
            "affinity_level": affinity.get_level(),
            "total_interactions": state["total_interactions"],
        }

        level_name, _ = AFFINITY_LEVELS.get(result["affinity_level"], AFFINITY_LEVELS[0])
        deltas_str = ", ".join(f"{aid}{d:+.1f}" for aid, d in affinity_deltas) if affinity_deltas else "无变化"
        logger.info("人格交互 #%d: 心境=%s, 亲和=L%d「%s」(%.0f/100) Δ=[%s]",
                     result["total_interactions"], result["mood"]["label"],
                     result["affinity_level"], level_name,
                     result["affinity_value"], deltas_str)

        return result

    def build_prompt(self, uid: int) -> str:
        """生成自然语言人格快照，用于注入 system prompt"""
        state = self.get_or_load_user(uid)
        emotion: EmotionModule = state["emotion"]
        affinity: AffinityModule = state["affinity"]
        habit: HabitModule = state["habit"]

        mood = emotion.get_mood_profile()
        display = emotion.get_display_emotion()
        level = affinity.get_level()
        guide = affinity.get_behavior_guide()
        level_name, _ = AFFINITY_LEVELS.get(level, AFFINITY_LEVELS[0])

        sections = []

        sections.append("## 你当前的情绪状态")
        sections.append("")
        sections.append(
            f"你的心境处于【{mood['emoji']} {mood['label']}】模式。"
        )

        emo_parts = []
        for key, label in [("joly", "喜悦"), ("sorw", "悲伤"),
                            ("angr", "愤怒"), ("fear", "不安")]:
            emo_parts.append(f"{label} {display[key]:.2f}")
        sections.append("内心原始情绪 — " + " / ".join(emo_parts) + "。")

        meta_val = display["meta"]
        if meta_val > 0.85:
            meta_desc = "高度自控（几乎不流露情绪）"
        elif meta_val > 0.6:
            meta_desc = "正常调节（适度流露情绪）"
        elif meta_val > 0.3:
            meta_desc = "偏情绪化（情绪容易外显）"
        else:
            meta_desc = "失控状态（喜怒哀乐完全外显）"
        sections.append(f"自控力水平：{meta_desc}。")
        sections.append(f"行为倾向：{mood['behavior']}。")

        sections.append("")
        sections.append("## 你与用户的关系")
        sections.append("")
        sections.append(
            f"亲密度等级：L{level}「{level_name}」"
            f"(好感值 {affinity.value:.0f}/100)。"
        )
        sections.append(f"{guide}。")

        active_habits = habit.select_active(top_n=5)
        if active_habits:
            sections.append("")
            sections.append("## 你的表达习惯")
            sections.append("")
            for h in active_habits:
                src = "先天" if h.source == "innate" else "后天习得"
                sections.append(
                    f"- [{src}] {h.content} (强度 {h.strength:.2f})"
                )

        return "\n".join(sections)

    def get_state(self, uid: int) -> dict:
        """获取人格状态摘要（API 用）"""
        state = self.get_or_load_user(uid)
        emotion: EmotionModule = state["emotion"]
        affinity: AffinityModule = state["affinity"]
        habit: HabitModule = state["habit"]

        return {
            "uid": uid,
            "preset_name": state["preset_name"],
            "total_interactions": state["total_interactions"],
            "mood": emotion.get_mood_profile(),
            "display_emotion": emotion.get_display_emotion(),
            "raw_emotion": emotion.get_raw_values(),
            "affinity": {
                "value": affinity.value,
                "level": affinity.get_level(),
                "effective": affinity.get_effective_affinity(),
            },
            "habit_count": len(habit.to_list()),
            "innate_weight": habit.innate_weight,
        }

    def get_full_state(self, uid: int) -> dict:
        """获取完整人格状态（API 用）"""
        state = self.get_or_load_user(uid)
        emotion: EmotionModule = state["emotion"]
        affinity: AffinityModule = state["affinity"]
        habit: HabitModule = state["habit"]

        return {
            "uid": uid,
            "preset_name": state["preset_name"],
            "total_interactions": state["total_interactions"],
            "emotion": {
                "values": emotion.get_raw_values(),
                "baselines": emotion.get_baselines(),
                "display": emotion.get_display_emotion(),
                "mood": emotion.get_mood_profile(),
            },
            "affinity": {
                "value": affinity.value,
                "level": affinity.get_level(),
                "effective": affinity.get_effective_affinity(),
                "behavior_guide": affinity.get_behavior_guide(),
            },
            "habit": {
                "all": habit.to_list(),
                "innate_weight": habit.innate_weight,
            },
        }

    def switch_preset(self, uid: int, name: str) -> dict:
        """切换预设"""
        ok = self.load_preset(uid, name)
        if not ok:
            return {"success": False, "error": f"预设不存在: {name}"}
        return {"success": True, "preset": name}

    def list_presets(self) -> list[dict]:
        return [
            {
                "name": name,
                "display_name": p.get("display_name", name),
                "description": p.get("description", ""),
            }
            for name, p in self._presets.items()
        ]

    def flush(self) -> None:
        self._store.force_flush()


__all__ = [
    "PersonalitySystemV2",
    "EmotionModule",
    "EmotionalStimulus",
    "MoodProfile",
    "StimulusAnalyzer",
    "AffinityModule",
    "ActionClassifier",
    "AFFINITY_LEVELS",
    "HabitModule",
    "Habit",
    "PatternObserver",
    "PersonalityStateStore",
    "CREATE_PERSONALITY_TABLE",
]
