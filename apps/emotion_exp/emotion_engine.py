# apps/emotion_exp/emotion_engine.py
# 极简情绪状态机与情绪动力学引擎
# 维护五维情绪向量：joy, sorrow, anger, fear, meta

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class EmotionalState:
    joy: float = 0.5       # 愉悦 / 快乐 [0.0, 1.0]
    sorrow: float = 0.0    # 悲伤 / 失落 [0.0, 1.0]
    anger: float = 0.0     # 愤怒 / 烦躁 [0.0, 1.0]
    fear: float = 0.0      # 担忧 / 恐惧 [0.0, 1.0]
    meta: float = 0.7      # 理智 / 自省 / 平静度 [0.0, 1.0]

    def to_dict(self) -> Dict[str, float]:
        return {
            "joy": round(self.joy, 3),
            "sorrow": round(self.sorrow, 3),
            "anger": round(self.anger, 3),
            "fear": round(self.fear, 3),
            "meta": round(self.meta, 3),
        }

    def dominant_emotion(self) -> tuple[str, float]:
        """计算当前最显著外显情绪"""
        # meta 抑制极化情绪
        damping = max(0.2, 1.0 - (self.meta * 0.5))
        effective = {
            "开心": self.joy * damping,
            "失落": self.sorrow * damping,
            "生气": self.anger * damping,
            "担忧": self.fear * damping,
            "冷静": self.meta,
        }
        name = max(effective, key=effective.get)
        return name, effective[name]


class EmotionEngine:
    """情绪更新与演化引擎"""

    def __init__(self, initial_state: Optional[EmotionalState] = None):
        self.state = initial_state or EmotionalState()
        # 基线回归目标
        self.baseline = EmotionalState(joy=0.5, sorrow=0.0, anger=0.0, fear=0.0, meta=0.7)
        self.decay_rate = 0.1  # 每轮向基线回归的速率

    def decay(self) -> None:
        """向基线状态自然衰减"""
        for attr in ("joy", "sorrow", "anger", "fear", "meta"):
            cur = getattr(self.state, attr)
            base = getattr(self.baseline, attr)
            setattr(self.state, attr, cur + (base - cur) * self.decay_rate)

    def apply_stimulus(
        self,
        delta_joy: float = 0.0,
        delta_sorrow: float = 0.0,
        delta_anger: float = 0.0,
        delta_fear: float = 0.0,
        delta_meta: float = 0.0,
    ) -> None:
        """输入情绪刺激向量并限制在 [0.0, 1.0] 区间"""
        self.decay()
        self.state.joy = max(0.0, min(1.0, self.state.joy + delta_joy))
        self.state.sorrow = max(0.0, min(1.0, self.state.sorrow + delta_sorrow))
        self.state.anger = max(0.0, min(1.0, self.state.anger + delta_anger))
        self.state.fear = max(0.0, min(1.0, self.state.fear + delta_fear))
        self.state.meta = max(0.0, min(1.0, self.state.meta + delta_meta))

    def perception_prompt(self) -> str:
        """产出注入上下文的情绪提示词"""
        dom, val = self.state.dominant_emotion()
        return (
            f"【当前内心状态】整体心境：{dom}（强度: {val:.2f}）。"
            f"细分向量: 愉悦 {self.state.joy:.2f}, 悲伤 {self.state.sorrow:.2f}, "
            f"烦躁 {self.state.anger:.2f}, 担忧 {self.state.fear:.2f}, 理智 {self.state.meta:.2f}。"
            f"请自然地融入对话语气，无需机械复述数值。"
        )
