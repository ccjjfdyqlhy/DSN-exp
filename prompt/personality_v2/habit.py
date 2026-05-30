# prompt/personality_v2/habit.py
# HabitModule — 先天+后天双层习性，从用户对话学习

from __future__ import annotations

import logging
import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional

logger = logging.getLogger("HabitModule")


@dataclass
class Habit:
    """单条习性"""
    id: str
    type: Literal["catchphrase", "pattern", "tone"]
    content: str
    strength: float = 0.5
    source: Literal["innate", "learned", "mirrored"] = "innate"
    created_at: str = ""
    last_used: str | None = None
    use_count: int = 0
    decay_rate: float = 0.02
    feedback_history: list[float] = field(default_factory=list)

    @staticmethod
    def make_id(content: str) -> str:
        return hashlib.md5(content.encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "content": self.content,
            "strength": self.strength,
            "source": self.source,
            "created_at": self.created_at,
            "last_used": self.last_used,
            "use_count": self.use_count,
            "decay_rate": self.decay_rate,
            "feedback_history": self.feedback_history,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Habit:
        return cls(
            id=data.get("id", cls.make_id(data.get("content", ""))),
            type=data.get("type", "catchphrase"),
            content=data.get("content", ""),
            strength=data.get("strength", 0.5),
            source=data.get("source", "innate"),
            created_at=data.get("created_at", ""),
            last_used=data.get("last_used"),
            use_count=data.get("use_count", 0),
            decay_rate=data.get("decay_rate", 0.02),
            feedback_history=data.get("feedback_history", []),
        )


class HabitModule:
    """
    习性模块 — 管理先天+后天习性的双层模型。

    习性类型:
      - catchphrase: 口头禅 / 惯用语句
      - pattern: 结构性习惯
      - tone: 语气倾向

    学习机制:
      1. 被动观察 → 候选池 (mirrored, strength 0.1)
      2. 测试使用 → 正面反馈 → 晋升 (strength > 0.3 → learned)
      3. 衰减遗忘 → 低强度 + 长期未用 → 淘汰
    """

    MAX_HABITS = 25
    INNATE_MIN_STRENGTH = 0.1
    LEARNED_THRESHOLD = 0.3
    MIRROR_STRENGTH = 0.1
    FEEDBACK_GAIN = 0.05
    GRACE_PERIOD_HOURS = 24

    def __init__(self):
        self._habits: dict[str, Habit] = {}
        self._innate_weight: float = 1.0
        self._total_interactions: int = 0

    def load_innate(self, innate_config: dict) -> None:
        """从 YAML 预设加载先天习性"""
        catchphrases = innate_config.get("catchphrases", [])
        if isinstance(catchphrases, list):
            for item in catchphrases:
                if isinstance(item, str):
                    self._add_innate(Habit(
                        id=Habit.make_id(item),
                        type="catchphrase",
                        content=item,
                        strength=0.8,
                    ))
                elif isinstance(item, dict):
                    self._add_innate(Habit(
                        id=Habit.make_id(item.get("content", "")),
                        type="catchphrase",
                        content=item.get("content", ""),
                        strength=item.get("strength", 0.8),
                        decay_rate=item.get("decay_rate", 0.01),
                    ))

        patterns = innate_config.get("patterns", [])
        for item in patterns:
            if isinstance(item, str):
                self._add_innate(Habit(
                    id=Habit.make_id(item),
                    type="pattern",
                    content=item,
                    strength=0.8,
                ))
            elif isinstance(item, dict):
                self._add_innate(Habit(
                    id=Habit.make_id(item.get("content", "")),
                    type="pattern",
                    content=item.get("content", ""),
                    strength=item.get("strength", 0.8),
                    decay_rate=item.get("decay_rate", 0.01),
                ))

        tones = innate_config.get("tones", [])
        for item in tones:
            if isinstance(item, str):
                self._add_innate(Habit(
                    id=Habit.make_id(item),
                    type="tone",
                    content=item,
                    strength=0.7,
                ))
            elif isinstance(item, dict):
                self._add_innate(Habit(
                    id=Habit.make_id(item.get("content", "")),
                    type="tone",
                    content=item.get("content", ""),
                    strength=item.get("strength", 0.7),
                    decay_rate=item.get("decay_rate", 0.01),
                ))

        logger.info("加载了 %d 条先天习性", len([h for h in self._habits.values() if h.source == "innate"]))

    def _add_innate(self, habit: Habit) -> None:
        habit.source = "innate"
        habit.created_at = datetime.now(timezone.utc).isoformat()
        if habit.id in self._habits:
            existing = self._habits[habit.id]
            existing.strength = max(existing.strength, habit.strength)
            existing.content = habit.content
            existing.type = habit.type
        else:
            self._habits[habit.id] = habit

    def add_candidates(self, candidates: list[Habit]) -> int:
        """将候选习性加入候选池"""
        added = 0
        now = datetime.now(timezone.utc).isoformat()
        for candidate in candidates:
            if candidate.id in self._habits:
                continue
            if self._count_non_innate() + 1 > self.MAX_HABITS - self._count_innate():
                continue
            candidate.source = "mirrored"
            candidate.strength = self.MIRROR_STRENGTH
            candidate.created_at = now
            self._habits[candidate.id] = candidate
            added += 1
        if added > 0:
            logger.debug("添加了 %d 条候选习性", added)
        return added

    def record_usage(self, habit_id: str) -> None:
        """记录习性被使用"""
        habit = self._habits.get(habit_id)
        if not habit:
            return
        habit.last_used = datetime.now(timezone.utc).isoformat()
        habit.use_count += 1

    def record_feedback(self, habit_id: str, score: float) -> None:
        """
        记录用户对此习性的反馈评分。

        score: −1.0 (完全负面) ~ +1.0 (完全正面), 0.0 为中性无反馈
        """
        habit = self._habits.get(habit_id)
        if not habit:
            return
        habit.feedback_history.append(score)
        if len(habit.feedback_history) > 10:
            habit.feedback_history = habit.feedback_history[-10:]

        avg_feedback = sum(habit.feedback_history) / len(habit.feedback_history)
        delta = avg_feedback * self.FEEDBACK_GAIN
        habit.strength = max(0.0, min(1.0, habit.strength + delta))

    def try_promote(self, habit_id: str) -> bool:
        """候选习性晋升为 learned"""
        habit = self._habits.get(habit_id)
        if not habit or habit.source != "mirrored":
            return False
        if habit.strength >= self.LEARNED_THRESHOLD:
            habit.source = "learned"
            logger.info("习性晋升: %s → learned (strength=%.2f)", habit.content, habit.strength)
            return True
        return False

    def select_active(self, top_n: int = 5) -> list[Habit]:
        """按有效强度排序取 top N 活跃习性"""
        weighted = []
        for habit in self._habits.values():
            effective = habit.strength
            if habit.source == "innate":
                effective *= self._innate_weight
            else:
                effective *= (1.0 - self._innate_weight)
            weighted.append((effective, habit))

        weighted.sort(key=lambda x: x[0], reverse=True)
        return [h for _, h in weighted[:top_n] if h.strength > 0.05]

    def daily_decay(self) -> None:
        """每日衰减 + 淘汰"""
        now = datetime.now(timezone.utc)
        to_remove = []

        for habit in self._habits.values():
            if habit.last_used:
                try:
                    last = datetime.fromisoformat(habit.last_used)
                except (ValueError, TypeError):
                    last = now
            else:
                last = now
            days_since_use = (now - last).days

            if days_since_use > 0:
                habit.strength *= (habit.decay_rate ** days_since_use)
                habit.strength = max(0.0, habit.strength)

            if habit.source != "innate" and habit.strength < 0.05:
                if habit.source == "learned":
                    grace_end = datetime.fromisoformat(habit.created_at)
                    if (now - grace_end).total_seconds() < self.GRACE_PERIOD_HOURS * 3600:
                        continue
                to_remove.append(habit.id)

        for hid in to_remove:
            removed = self._habits.pop(hid, None)
            if removed:
                logger.debug("习性遗忘: %s (strength=%.3f)", removed.content, removed.strength)

    def update_innate_weight(self) -> None:
        """根据总交互次数更新先天权重"""
        self._innate_weight = max(0.3, 1.0 - self._total_interactions / 1000.0)

    def increment_interactions(self) -> None:
        self._total_interactions += 1
        self.update_innate_weight()

    def to_list(self) -> list[dict]:
        return [h.to_dict() for h in self._habits.values()]

    @classmethod
    def from_list(cls, data: list[dict]) -> HabitModule:
        inst = cls()
        for item in data:
            habit = Habit.from_dict(item)
            inst._habits[habit.id] = habit
        return inst

    @property
    def innate_weight(self) -> float:
        return self._innate_weight

    @innate_weight.setter
    def innate_weight(self, value: float) -> None:
        self._innate_weight = max(0.3, min(1.0, value))

    @property
    def total_interactions(self) -> int:
        return self._total_interactions

    @total_interactions.setter
    def total_interactions(self, value: int) -> None:
        self._total_interactions = value
        self.update_innate_weight()

    def _count_innate(self) -> int:
        return sum(1 for h in self._habits.values() if h.source == "innate")

    def _count_non_innate(self) -> int:
        return sum(1 for h in self._habits.values() if h.source != "innate")


class PatternObserver:
    """
    被动观察器 — 从用户消息中检测重复模式，生成候选习性。
    """

    def __init__(self, window: int = 20):
        self.window = window
        self._message_buffer: list[str] = []

    def feed(self, message: str) -> None:
        self._message_buffer.append(message)
        if len(self._message_buffer) > self.window * 2:
            self._message_buffer = self._message_buffer[-self.window:]

    def observe(self) -> list[Habit]:
        """观察最近消息，返回候选习性列表"""
        if len(self._message_buffer) < 5:
            return []
        recent = self._message_buffer[-self.window:]
        candidates: list[Habit] = []

        phrase_candidates = self._extract_phrases(recent)
        candidates.extend(phrase_candidates)

        tone_candidates = self._detect_tone(recent)
        candidates.extend(tone_candidates)

        return candidates

    def _extract_phrases(self, messages: list[str]) -> list[Habit]:
        phrase_counts: dict[str, int] = {}
        phrase_first: dict[str, int] = {}

        for idx, msg in enumerate(messages):
            if len(msg) < 4:
                continue
            substrings = set()
            for i in range(len(msg)):
                for j in range(i + 2, min(i + 8, len(msg) + 1)):
                    sub = msg[i:j].strip()
                    if len(sub) >= 2:
                        substrings.add(sub)

            for sub in substrings:
                phrase_counts[sub] = phrase_counts.get(sub, 0) + 1
                if sub not in phrase_first:
                    phrase_first[sub] = idx

        candidates = []
        for phrase, count in phrase_counts.items():
            if count >= 3 and len(phrase) >= 2:
                habit_id = Habit.make_id(phrase)
                candidates.append(Habit(
                    id=habit_id,
                    type="catchphrase",
                    content=phrase,
                    strength=0.1,
                    source="mirrored",
                    created_at=datetime.now(timezone.utc).isoformat(),
                    decay_rate=0.05,
                ))

        return candidates

    def _detect_tone(self, messages: list[str]) -> list[Habit]:
        candidates = []

        total_excl = sum(msg.count("!") for msg in messages)
        total_tilde = sum(msg.count("~") for msg in messages)
        total_ellipsis = sum(msg.count("...") + msg.count("。。") for msg in messages)
        total_question = sum(1 for msg in messages if "?" in msg or "？" in msg)
        total_emoji = sum(1 for msg in messages if any(
            c in msg for c in "😊😂😭🥺😡🤔👍🙏💪✨"
        ))

        n = len(messages) or 1
        tone_descriptions = []

        if total_tilde / n > 0.3:
            tone_descriptions.append("喜欢用 '~' 结尾让语气更轻松")
        if total_excl / n > 0.5:
            tone_descriptions.append("爱用感叹号表达强烈语气")
        if total_ellipsis / n > 0.3:
            tone_descriptions.append("经常用省略号，说话欲言又止")
        if total_question / n > 0.5:
            tone_descriptions.append("频繁使用反问句")
        if total_emoji / n > 0.3:
            tone_descriptions.append("喜欢用 emoji 表达情绪")

        for desc in tone_descriptions:
            candidates.append(Habit(
                id=Habit.make_id(desc),
                type="tone",
                content=desc,
                strength=0.1,
                source="mirrored",
                created_at=datetime.now(timezone.utc).isoformat(),
                decay_rate=0.03,
            ))

        return candidates

    def clear(self) -> None:
        self._message_buffer.clear()
