# prompt/personality_v2/affinity.py
# AffinityModule — 养成游戏式好感值系统

from __future__ import annotations

import logging
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("AffinityModule")


AFFINITY_LEVELS: dict[int, tuple[str, str]] = {
    0: ("陌生人", "正式称呼「您」，保持距离，不表达个人观点"),
    1: ("相识", "可以使用用户的名字，适度表达善意"),
    2: ("朋友", "可开玩笑，使用「咱俩」等亲近表达"),
    3: ("密友", "可引用历史对话作为「咱俩共同的经历」"),
    4: ("灵魂伴侣", "主动分享自己的「想法」，开启非请求话题"),
    5: ("不可替代", "可使用只有两人知道的内部梗，自由切换话题"),
}


class AffinityModule:
    """
    亲和力模块 — 管理用户与 AI 之间的好感值。

    模型:
      - 好感值 0~100
      - 社交行为驱动加减分
      - 冷却 / 防刷 / 反弹保护
      - 5 级关系等级解锁行为
    """

    def __init__(self):
        self._value: float = 20.0
        self._action_cooldowns: dict[str, float] = {}
        self._action_daily_counts: dict[str, int] = {}
        self._last_daily_reset: float = time.time()
        self._last_insult_time: float | None = None
        self._recent_changes: deque[float] = deque(maxlen=20)
        self._decay_enabled: bool = False
        self._last_interaction: float | None = None

    def reset(self, initial: float = 20.0, decay_enabled: bool = False) -> None:
        self._value = max(0.0, min(100.0, initial))
        self._action_cooldowns.clear()
        self._action_daily_counts.clear()
        self._last_insult_time = None
        self._recent_changes.clear()
        self._decay_enabled = decay_enabled
        logger.info("亲和力模块已重置, 初始值=%.1f", self._value)

    def apply_action(self, action: dict) -> float:
        """
        处理一个社交行为，返回本次变化的 Δ 值。

        action 格式:
          {
            "id": "P_THANK",
            "delta": +2,
            "cooldown_minutes": 10,
            "max_per_day": 10,
          }
        """
        action_id = action["id"]
        delta = action.get("delta", 0)
        cooldown_minutes = action.get("cooldown_minutes", 0)
        max_per_day = action.get("max_per_day", 999)
        rebound_minutes = action.get("rebound_minutes", 0)

        now = time.time()

        if now - self._last_daily_reset > 86400:
            self._action_daily_counts.clear()
            self._last_daily_reset = now

        if cooldown_minutes > 0:
            last = self._action_cooldowns.get(action_id, 0)
            if now - last < cooldown_minutes * 60:
                return 0.0

        daily_count = self._action_daily_counts.get(action_id, 0)
        if daily_count >= max_per_day:
            return 0.0

        effective_delta = delta
        if rebound_minutes > 0 and self._last_insult_time is not None:
            if now - self._last_insult_time < rebound_minutes * 60:
                effective_delta *= 0.5

        old_value = self._value
        self._value = max(0.0, min(100.0, self._value + effective_delta))

        self._action_cooldowns[action_id] = now
        self._action_daily_counts[action_id] = daily_count + 1
        self._last_interaction = now

        if action_id == "N_INSULT" and delta < 0:
            self._last_insult_time = now

        actual_change = self._value - old_value
        if abs(actual_change) > 0.01:
            self._recent_changes.append(actual_change)
            new_level = self.get_level()
            old_level = self._get_level_for_value(old_value)
            if new_level != old_level:
                level_name, _ = AFFINITY_LEVELS.get(new_level, AFFINITY_LEVELS[0])
                logger.info("亲和力等级变化: L%d → L%d「%s」(亲和值: %.1f → %.1f, 行为: %s)",
                             old_level, new_level, level_name, old_value, self._value, action_id)

        return actual_change

    def get_level(self) -> int:
        """返回当前亲和力等级 (0~5)"""
        return self._get_level_for_value(self.get_effective_affinity())

    def _get_level_for_value(self, v: float) -> int:
        if v < 0:
            return 0
        if v < 16:
            return 0
        if v < 31:
            return 1
        if v < 51:
            return 2
        if v < 71:
            return 3
        if v < 91:
            return 4
        return 5

    def get_effective_affinity(self) -> float:
        """返回带近期偏差的有效亲和力值"""
        base = self._value
        if len(self._recent_changes) >= 3:
            recent_avg = sum(self._recent_changes) / len(self._recent_changes)
            return base * 0.8 + recent_avg * 0.2
        return base

    def get_behavior_guide(self) -> str:
        """根据等级返回社交行为指南文本"""
        level = self.get_level()
        _, guide = AFFINITY_LEVELS.get(level, AFFINITY_LEVELS[0])
        return guide

    def decay_daily(self) -> None:
        """每日调用一次：超过 7 天无互动则缓慢衰减"""
        if not self._decay_enabled:
            return
        if self._last_interaction is None:
            return
        now = time.time()
        days_since = (now - self._last_interaction) / 86400.0
        if days_since > 7:
            decay_days = days_since - 7
            old_value = self._value
            self._value = max(0.0, self._value - decay_days * 1.0)
            logger.info("亲和力衰减: 距上次互动 %.1f 天, %.1f → %.1f", days_since, old_value, self._value)

    @property
    def value(self) -> float:
        return self._value

    def to_dict(self) -> dict:
        return {
            "value": self._value,
            "action_cooldowns": dict(self._action_cooldowns),
            "action_daily_counts": dict(self._action_daily_counts),
            "last_insult_time": self._last_insult_time,
            "recent_changes": list(self._recent_changes),
            "decay_enabled": self._decay_enabled,
            "last_interaction": self._last_interaction,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AffinityModule:
        inst = cls()
        inst._value = data.get("value", 20.0)
        inst._action_cooldowns = data.get("action_cooldowns", {})
        inst._action_daily_counts = data.get("action_daily_counts", {})
        inst._last_insult_time = data.get("last_insult_time")
        inst._recent_changes = deque(data.get("recent_changes", []), maxlen=20)
        inst._decay_enabled = data.get("decay_enabled", False)
        inst._last_interaction = data.get("last_interaction")
        return inst


class ActionClassifier:
    """
    社交行为分类器 — 将用户消息分类为亲和力行为。

    规则驱动（基于 affinity_rules.yaml），支持热重载。
    """

    _BADWORDS = {
        "sb", "傻逼", "cnm", "操", "fuck", "贱", "白痴", "智障",
        "脑残", "废物", "垃圾", "去死", "滚", "恶心",
    }

    def __init__(self, rules: list[dict] | None = None):
        self._rules: list[dict] = rules or []

    def load_rules(self, rules: list[dict]) -> None:
        self._rules = rules

    def classify(self, message: str) -> list[dict]:
        """
        分析用户消息，返回匹配的行为列表。
        每个结果是完整的 action 字典，包含 delta/冷却等。
        """
        results: list[dict] = []
        msg_lower = message.lower().strip()

        for rule in self._rules:
            action_id = rule.get("id", "")
            detection = rule.get("detection", {})

            has_patterns = bool(detection.get("pattern", []))
            if not has_patterns:
                continue

            if not self._match_detection(detection, msg_lower, message):
                continue

            results.append({
                "id": action_id,
                "delta": rule.get("delta", 0),
                "cooldown_minutes": rule.get("cooldown_minutes", 0),
                "max_per_day": rule.get("max_per_day", 999),
                "rebound_minutes": rule.get("rebound_minutes", 0),
            })

        self._apply_heuristics(message, msg_lower, results)

        return results

    def _match_detection(self, detection: dict, msg_lower: str, original: str) -> bool:
        patterns = detection.get("pattern", [])
        if not patterns:
            return True

        position = detection.get("position", "")
        for p in patterns:
            if p.lower() not in msg_lower:
                continue
            if position == "start_of_message":
                if original.startswith(p) or msg_lower.split()[0].startswith(p.lower()):
                    return True
            else:
                return True
        return False

    def _apply_heuristics(self, message: str, msg_lower: str,
                          results: list[dict]) -> None:
        for word in self._BADWORDS:
            if word in msg_lower:
                already_has = any(r["id"] == "N_INSULT" for r in results)
                if not already_has:
                    results.append({
                        "id": "N_INSULT",
                        "delta": -8,
                        "cooldown_minutes": 0,
                        "max_per_day": 999,
                        "rebound_minutes": 10,
                    })
                break

        msg_len = len(message.strip())
        if msg_len > 200 and not any(
            r["id"] == "P_SHARE" for r in results
        ):
            results.append({
                "id": "P_SHARE",
                "delta": 6,
                "cooldown_minutes": 120,
                "max_per_day": 5,
                "rebound_minutes": 0,
            })
