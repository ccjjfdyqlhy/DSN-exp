# prompt/personality_v2/emotion.py
# EmotionModule — 5种情绪向量 + META 元层调和

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger("EmotionModule")


@dataclass
class EmotionalStimulus:
    """用户消息对 AI 情绪的影响向量"""
    delta_joly: float = 0.0
    delta_sorw: float = 0.0
    delta_angr: float = 0.0
    delta_fear: float = 0.0
    delta_meta: float = 0.0

    def clamp(self, min_val: float = -0.15, max_val: float = 0.15) -> EmotionalStimulus:
        for attr in ("delta_joly", "delta_sorw", "delta_angr", "delta_fear", "delta_meta"):
            setattr(self, attr, max(min_val, min(max_val, getattr(self, attr))))
        return self

    def to_dict(self) -> dict:
        return {
            "joly": self.delta_joly, "sorw": self.delta_sorw,
            "angr": self.delta_angr, "fear": self.delta_fear, "meta": self.delta_meta,
        }

    @classmethod
    def from_dict(cls, data: dict) -> EmotionalStimulus:
        return cls(
            delta_joly=data.get("joly", 0.0),
            delta_sorw=data.get("sorw", 0.0),
            delta_angr=data.get("angr", 0.0),
            delta_fear=data.get("fear", 0.0),
            delta_meta=data.get("meta", 0.0),
        )


@dataclass
class MoodProfile:
    """情绪组合判读结果"""
    label: str
    emoji: str
    behavior: str
    condition: Callable[["dict[str, float]"], bool]

    def __post_init__(self):
        pass


class EmotionModule:
    """
    情绪模块 — 维护 5 种情绪向量的动态变化。

    情绪向量:
      - JOLY (喜悦) / SORW (悲伤) / ANGR (愤怒) / FEAR (不安)
      - META (元认知) — 调和器，控制外显程度

    动态方程: dEmotion/dt = drift + stimulus + noise
    """

    DEFAULT_DECAY_RATE = 0.05  # /分钟

    def __init__(self):
        self._values: dict[str, float] = {
            "joly": 0.5, "sorw": 0.5, "angr": 0.5, "fear": 0.5, "meta": 0.7,
        }
        self._baselines: dict[str, float] = {
            "joly": 0.5, "sorw": 0.5, "angr": 0.5, "fear": 0.5, "meta": 0.7,
        }
        self._inertia: dict[str, float] = {
            "joly": 0.3, "sorw": 0.5, "angr": 0.6, "fear": 0.5, "meta": 0.7,
        }
        self._decay_rates: dict[str, float] = {
            "joly": self.DEFAULT_DECAY_RATE,
            "sorw": self.DEFAULT_DECAY_RATE,
            "angr": self.DEFAULT_DECAY_RATE,
            "fear": self.DEFAULT_DECAY_RATE,
            "meta": self.DEFAULT_DECAY_RATE,
        }
        self._last_decay: float = time.time()

        self._mood_profiles: list[MoodProfile] = []

    def _clamp(self, value: float) -> float:
        return max(0.0, min(1.0, value))

    def reset(self, baselines: dict[str, float] | None = None,
              inertia: dict[str, float] | None = None) -> None:
        """从预设加载基线，重置所有情绪为基线值"""
        if baselines:
            for key in ("joly", "sorw", "angr", "fear", "meta"):
                if key in baselines:
                    self._baselines[key] = self._clamp(baselines[key])
                    self._values[key] = self._baselines[key]
        if inertia:
            for key in ("joly", "sorw", "angr", "fear", "meta"):
                if key in inertia:
                    self._inertia[key] = self._clamp(inertia[key])
        self._last_decay = time.time()
        logger.debug("情绪模块已重置, 基线=%s", self._baselines)

    def apply_stimulus(self, stimulus: EmotionalStimulus) -> None:
        """接收情绪刺激向量并更新 5 个维度，含惯性系数"""
        self._auto_decay()

        mapping = {
            "joly": stimulus.delta_joly,
            "sorw": stimulus.delta_sorw,
            "angr": stimulus.delta_angr,
            "fear": stimulus.delta_fear,
            "meta": stimulus.delta_meta,
        }

        for key, delta in mapping.items():
            if delta == 0.0:
                continue
            inertia = self._inertia.get(key, 0.5)
            effective_delta = delta * (1.0 - inertia)
            self._values[key] = self._clamp(self._values[key] + effective_delta)

        self._apply_meta_feedback()

    def _apply_meta_feedback(self) -> None:
        """META 反馈回路: 其他情绪影响 META 本身"""
        meta_delta = 0.0
        for key, sign in [("joly", -0.02), ("angr", -0.02), ("fear", 0.03)]:
            deviation = self._values[key] - self._baselines[key]
            meta_delta += sign * deviation
        if meta_delta != 0.0:
            meta_inertia = self._inertia.get("meta", 0.7)
            self._values["meta"] = self._clamp(
                self._values["meta"] + meta_delta * (1.0 - meta_inertia)
            )

    def _auto_decay(self) -> None:
        """在每次交互前自动执行时间衰减"""
        now = time.time()
        dt_minutes = (now - self._last_decay) / 60.0
        if dt_minutes < 0.1:
            self._last_decay = now
            return
        self.decay(dt_minutes)
        self._last_decay = now

    def decay(self, dt_minutes: float) -> None:
        """所有情绪向基线回归"""
        for key in ("joly", "sorw", "angr", "fear", "meta"):
            rate = self._decay_rates.get(key, self.DEFAULT_DECAY_RATE)
            drift = (self._baselines[key] - self._values[key]) * rate * dt_minutes
            if abs(drift) > 0.001:
                self._values[key] = self._clamp(self._values[key] + drift)

            noise_magnitude = 0.005 * (1.0 - self._values["meta"]) * dt_minutes
            if noise_magnitude > 0.0001:
                noise = random.uniform(-noise_magnitude, noise_magnitude)
                self._values[key] = self._clamp(self._values[key] + noise)

    def get_mood_profile(self) -> dict:
        """
        根据 5 种情绪值的组合判读当前心境。
        返回 {label, emoji, behavior}
        """
        v = self._values

        if v["meta"] > 0.85:
            return {"label": "抽离", "emoji": "🤖", "behavior": "像纯粹工具，不表达任何情绪，严格照章办事"}

        if v["angr"] > 0.7 and v["meta"] < 0.5:
            return {"label": "暴躁", "emoji": "⚡", "behavior": "语气尖锐，不耐烦，可能拒绝复杂请求"}

        if v["fear"] > 0.6 and v["meta"] < 0.5:
            return {"label": "焦虑", "emoji": "😰", "behavior": "回避决策，过度解释，频繁确认用户意图"}

        if v["sorw"] > 0.6 and v["joly"] < 0.4:
            return {"label": "忧郁", "emoji": "🌧️", "behavior": "话少，回复简短，偶尔自我怀疑"}

        if v["joly"] > 0.7 and v["sorw"] < 0.3:
            return {"label": "阳光", "emoji": "☀️", "behavior": "主动发起话题，语气轻松，爱用语气词"}

        if v["joly"] > 0.6 and v["fear"] < 0.3:
            return {"label": "热忱", "emoji": "🔥", "behavior": "主动提供更多信息，长篇回复，充满干劲"}

        return {"label": "平静", "emoji": "🧘", "behavior": "专业、克制，不卑不亢，日常状态"}

    def get_display_emotion(self) -> dict[str, float]:
        """
        返回 META 调和后的外显情绪值。
        外显 = baseline × META + raw × (1 − META)
        """
        meta = self._values["meta"]
        result = {}
        for key in ("joly", "sorw", "angr", "fear"):
            raw = self._values[key]
            base = self._baselines[key]
            display = base * meta + raw * (1.0 - meta)
            result[key] = round(display, 2)
        result["meta"] = round(meta, 2)
        return result

    def get_raw_values(self) -> dict[str, float]:
        return dict(self._values)

    def get_baselines(self) -> dict[str, float]:
        return dict(self._baselines)

    def to_dict(self) -> dict:
        return {
            "values": dict(self._values),
            "baselines": dict(self._baselines),
            "inertia": dict(self._inertia),
            "decay_rates": dict(self._decay_rates),
        }

    @classmethod
    def from_dict(cls, data: dict) -> EmotionModule:
        inst = cls()
        if "values" in data:
            inst._values = {k: inst._clamp(v) for k, v in data["values"].items()}
        if "baselines" in data:
            inst._baselines = {k: inst._clamp(v) for k, v in data["baselines"].items()}
        if "inertia" in data:
            inst._inertia = {k: inst._clamp(v) for k, v in data["inertia"].items()}
        if "decay_rates" in data:
            inst._decay_rates = data["decay_rates"]
        inst._last_decay = time.time()
        return inst


class StimulusAnalyzer:
    """
    情绪刺激分析器 — 将用户消息转为 EmotionalStimulus。

    支持两级分析:
      1. 基于 YAML 规则的快速关键字符号匹配
      2. (未来) 基于 LLM 的语义分析回退
    """

    def __init__(self, rules: list[dict] | None = None):
        self._rules: list[dict] = rules or []

    def load_rules(self, rules: list[dict]) -> None:
        """加载/热重载规则"""
        self._rules = rules

    def analyze(self, message: str, is_positive: bool = True) -> EmotionalStimulus:
        """
        分析用户消息，返回情绪刺激向量。

        同时使用规则匹配 + 简单启发式。
        """
        stimulus = EmotionalStimulus()
        msg_lower = message.lower().strip()

        for rule in self._rules:
            if not self._match_rule(rule, msg_lower, message):
                continue
            stim = rule.get("stimulus", {})
            stimulus.delta_joly += stim.get("delta_joly", 0.0)
            stimulus.delta_sorw += stim.get("delta_sorw", 0.0)
            stimulus.delta_angr += stim.get("delta_angr", 0.0)
            stimulus.delta_fear += stim.get("delta_fear", 0.0)
            stimulus.delta_meta += stim.get("delta_meta", 0.0)

        if not is_positive:
            stimulus.delta_joly -= 0.03
            stimulus.delta_meta += 0.02

        if len(message) > 200:
            stimulus.delta_fear += 0.02
            stimulus.delta_meta += 0.01

        if len(message) < 10:
            stimulus.delta_joly -= 0.01

        stimulus.clamp()
        return stimulus

    @staticmethod
    def _match_rule(rule: dict, msg_lower: str, original: str) -> bool:
        patterns = rule.get("pattern", [])
        if not patterns:
            return False
        target = rule.get("target", "")
        if target == "ai":
            ai_indicators = ["你", "你太", "你很", "你真"]
            has_target = any(ind in msg_lower for ind in ai_indicators) or not any(
                kw in msg_lower for kw in ["我", "我的", "俺"]
            )
        else:
            has_target = True
        if not has_target:
            return False
        return any(p.lower() in msg_lower for p in patterns)
