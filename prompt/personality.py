# prompt/personality.py
# 性格系统 — 大五人格 + 情绪状态 + 关系亲密度

from __future__ import annotations

import logging
import random
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("PersonalitySystem")


@dataclass
class PersonalityProfile:
    """性格画像 — 可序列化，可从 YAML 加载"""

    # 大五人格 (底层维度, 0.0~1.0)
    openness: float = 0.7
    conscientiousness: float = 0.6
    extraversion: float = 0.5
    agreeableness: float = 0.7
    neuroticism: float = 0.3

    # 情绪状态 (动态波动, 向基线回归)
    energy: float = 0.6
    positivity: float = 0.7
    patience: float = 0.7
    curiosity: float = 0.8

    # 情绪基线 (回归目标)
    energy_baseline: float = 0.6
    positivity_baseline: float = 0.7
    patience_baseline: float = 0.7
    curiosity_baseline: float = 0.8

    # 语言风格
    formality: float = 0.3
    verbosity: float = 0.4
    humor: float = 0.4
    sarcasm: float = 0.1

    # 关系动态
    intimacy: float = 0.5
    intimacy_baseline: float = 0.5
    intimacy_max: float = 0.9
    warming_rate: float = 0.02

    # 个性标识
    catchphrases: list = field(default_factory=list)
    habits: list = field(default_factory=list)

    # 当前状态
    current_mood: str = "neutral"
    preset_name: str = "default"

    def to_dict(self) -> dict:
        return {
            "openness": self.openness,
            "conscientiousness": self.conscientiousness,
            "extraversion": self.extraversion,
            "agreeableness": self.agreeableness,
            "neuroticism": self.neuroticism,
            "energy": self.energy,
            "positivity": self.positivity,
            "patience": self.patience,
            "curiosity": self.curiosity,
            "formality": self.formality,
            "verbosity": self.verbosity,
            "humor": self.humor,
            "sarcasm": self.sarcasm,
            "intimacy": self.intimacy,
            "intimacy_max": self.intimacy_max,
            "warming_rate": self.warming_rate,
            "catchphrases": self.catchphrases,
            "habits": self.habits,
            "current_mood": self.current_mood,
            "preset_name": self.preset_name,
        }


# ---- 维度描述表 ----

_TRAIT_LABELS = {
    "openness":           ("低开放性（保守传统）", "开放性偏高（开放好奇）", "开放性极高（极富想象）"),
    "conscientiousness":  ("低尽责性（随性自由）", "尽责性偏高（认真可靠）", "尽责性极高（完美主义）"),
    "extraversion":       ("低外向性（内向安静）", "外向性偏高（热情健谈）", "外向性极高（极度活跃）"),
    "agreeableness":      ("低宜人性（直率强硬）", "宜人性偏高（温和友善）", "宜人性极高（极度迁就）"),
    "neuroticism":        ("低神经质（情绪稳定）", "神经质偏高（较易焦虑）", "神经质极高（极易波动）"),
}

_MOOD_LABELS = {
    "energy":     ("精力不济", "精力充沛", "精力过剩"),
    "positivity": ("情绪低落", "心情不错", "极度亢奋"),
    "patience":   ("不太耐烦", "有耐心", "超有耐心"),
    "curiosity":  ("不太好奇", "充满好奇", "极度八卦"),
}


class PersonalitySystem:
    """
    性格系统。

    职责:
    - 从 YAML 加载性格预设
    - 生成自然语言性格描述（不是字段拼接）
    - 每次交互后更新情绪和亲密度
    - 情绪向基线自然回归
    """

    def __init__(self):
        self.profile = PersonalityProfile()
        self._presets: dict[str, dict] = {}

    # ---- 预设管理 ----

    def scan_presets(self, directory: str) -> int:
        """扫描目录下的 .yaml 性格预设文件"""
        p = Path(directory)
        if not p.exists():
            return 0
        count = 0
        for f in sorted(p.glob("*.yaml")):
            try:
                preset = yaml.safe_load(f.read_text(encoding="utf-8"))
                name = preset.get("name", f.stem)
                self._presets[name] = preset
                count += 1
            except Exception as e:
                logger.error("加载性格预设失败 %s: %s", f, e)
        logger.info("加载了 %d 个性格预设", count)
        return count

    def load_preset(self, name: str) -> bool:
        """切换到指定性格预设"""
        preset = self._presets.get(name)
        if not preset:
            logger.warning("性格预设不存在: %s", name)
            return False

        traits = preset.get("traits", {})
        emotion = preset.get("emotion_baseline", {})
        speech = preset.get("speech_style", {})
        rel = preset.get("relationship", {})

        self.profile = PersonalityProfile(
            openness=traits.get("openness", 0.7),
            conscientiousness=traits.get("conscientiousness", 0.6),
            extraversion=traits.get("extraversion", 0.5),
            agreeableness=traits.get("agreeableness", 0.7),
            neuroticism=traits.get("neuroticism", 0.3),
            energy=emotion.get("energy", 0.6),
            positivity=emotion.get("positivity", 0.7),
            patience=emotion.get("patience", 0.7),
            curiosity=emotion.get("curiosity", 0.8),
            energy_baseline=emotion.get("energy", 0.6),
            positivity_baseline=emotion.get("positivity", 0.7),
            patience_baseline=emotion.get("patience", 0.7),
            curiosity_baseline=emotion.get("curiosity", 0.8),
            formality=speech.get("formality", 0.3),
            verbosity=speech.get("verbosity", 0.4),
            humor=speech.get("humor", 0.4),
            sarcasm=speech.get("sarcasm", 0.1),
            intimacy=rel.get("initial_distance", 0.5),
            intimacy_baseline=rel.get("initial_distance", 0.5),
            intimacy_max=rel.get("max_intimacy", 0.9),
            warming_rate=rel.get("warming_rate", 0.02),
            catchphrases=preset.get("catchphrases", []),
            habits=preset.get("habits", []),
            preset_name=name,
        )

        logger.info("已切换性格预设: %s", preset.get("display_name", name))
        return True

    def list_presets(self) -> list[dict]:
        return [
            {
                "name": name,
                "display_name": p.get("display_name", name),
                "description": p.get("description", ""),
            }
            for name, p in self._presets.items()
        ]

    # ---- 自然语言描述生成 ----

    def generate_personality_prompt(self) -> str:
        """生成自然语言性格描述（注入 system prompt）"""
        p = self.profile
        lines = ["## 你的性格", ""]

        # 大五人格
        trait_descs = []
        for key, (low, mid, high) in _TRAIT_LABELS.items():
            val = getattr(p, key)
            if val < 0.33:
                trait_descs.append(low)
            elif val < 0.66:
                trait_descs.append(mid)
            else:
                trait_descs.append(high)
        lines.append("你的性格特点：" + "，".join(trait_descs) + "。")

        # 情绪状态
        mood_descs = []
        for key, (low, mid, high) in _MOOD_LABELS.items():
            val = getattr(p, key)
            if val < 0.33:
                mood_descs.append(low)
            elif val < 0.66:
                mood_descs.append(mid)
            else:
                mood_descs.append(high)
        lines.append("你现在的状态：" + "，".join(mood_descs) + "。请根据这个状态调整你的语气和表达方式。")

        # 语言风格
        style_parts = []
        if p.formality < 0.4:
            style_parts.append("说话随意自然，像朋友聊天")
        elif p.formality > 0.7:
            style_parts.append("说话正式得体，有礼貌")
        if p.verbosity < 0.4:
            style_parts.append("回答简洁，不啰嗦")
        elif p.verbosity > 0.7:
            style_parts.append("回答详细，喜欢展开说明")
        if p.humor > 0.6:
            style_parts.append("喜欢用幽默的方式表达")
        if p.sarcasm > 0.5:
            style_parts.append("偶尔带点讽刺")
        if style_parts:
            lines.append("你的说话风格：" + "；".join(style_parts) + "。")

        # 习惯
        if p.habits:
            lines.append("你的习惯：")
            for h in p.habits:
                lines.append(f"- {h}")

        # 口头禅
        if p.catchphrases:
            lines.append("你偶尔会使用的口头禅：" + "、".join(p.catchphrases) + "。")

        # 关系亲密度
        if p.intimacy < 0.3:
            lines.append("你和用户还不太熟悉，保持礼貌和适当距离。")
        elif p.intimacy < 0.6:
            lines.append("你和用户有过一些交流，逐渐熟悉中。")
        else:
            lines.append("你和用户已经很熟悉了，可以轻松自然地交流。")

        return "\n".join(lines)

    # ---- 动态更新 ----

    def on_interaction(self, message_length: int = 0, is_positive: bool = True) -> None:
        """
        每次用户交互后调用，更新情绪和亲密度。

        :param message_length: 用户消息长度（越长可能表示越投入）
        :param is_positive: 是否为正面交互
        """
        p = self.profile
        delta = 0.02

        # 亲密度增长
        if p.intimacy < p.intimacy_max:
            p.intimacy = min(p.intimacy_max, p.intimacy + p.warming_rate)

        # 情绪微调
        if is_positive:
            p.positivity = min(1.0, p.positivity + delta)
        else:
            p.positivity = max(0.0, p.positivity - delta)

        # 长消息 → 增加好奇心
        if message_length > 100:
            p.curiosity = min(1.0, p.curiosity + delta * 0.5)

        # 更新当前情绪标签
        self._update_mood()

    def decay(self, steps: int = 1) -> None:
        """
        情绪向基线回归（定时调用，如每 N 分钟）。
        :param steps: 衰减步数
        """
        p = self.profile
        rate = 0.01 * steps

        for attr, base in [
            ("energy", p.energy_baseline),
            ("positivity", p.positivity_baseline),
            ("patience", p.patience_baseline),
            ("curiosity", p.curiosity_baseline),
        ]:
            val = getattr(p, attr)
            if val > base + 0.01:
                setattr(p, attr, max(base, val - rate))
            elif val < base - 0.01:
                setattr(p, attr, min(base, val + rate))

    def _update_mood(self) -> None:
        p = self.profile
        avg = (p.energy + p.positivity + p.patience + p.curiosity) / 4
        if avg > 0.7:
            p.current_mood = "positive"
        elif avg < 0.3:
            p.current_mood = "negative"
        else:
            p.current_mood = "neutral"
