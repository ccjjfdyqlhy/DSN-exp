# apps/dsn_ui/emotion.py
# DSN-UI 情绪动力学引擎与状态机

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("DSNUIEmotion")


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

    def dominant_emotion(self) -> Tuple[str, float]:
        """计算当前最显著外显情绪及强度。"""
        damping = max(0.2, 1.0 - (self.meta * 0.5))
        effective = {
            "开心": self.joy * damping,
            "失落": self.sorrow * damping,
            "生气": self.anger * damping,
            "担忧": self.fear * damping,
            "冷静": self.meta,
        }
        name = max(effective, key=effective.get)
        return name, round(effective[name], 2)

    def summary_text(self) -> str:
        """生成供前端悬浮栏展示的情绪摘要。"""
        dom, val = self.dominant_emotion()
        intensity = "微弱" if val < 0.3 else ("中等" if val < 0.6 else "强烈")
        return f"心情：{dom} ({intensity} {val:.2f}) · 愉悦 {int(self.joy*100)}% · 理智 {int(self.meta*100)}%"


class DSNUIEmotionEngine:
    """情绪更新与演化引擎"""

    def __init__(self, initial_state: Optional[EmotionalState] = None):
        self.state = initial_state or EmotionalState()
        self.baseline = EmotionalState(joy=0.5, sorrow=0.0, anger=0.0, fear=0.0, meta=0.7)
        self.decay_rate = 0.1

    def summary_text(self) -> str:
        """获取当前状态的文本摘要。"""
        return self.state.summary_text()

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

    def evaluate_text_stimulus(self, text: str) -> None:
        """根据用户输入文本做快速启发式情绪响应"""
        if any(w in text for w in ["开心", "哈哈", "真棒", "喜欢", "感谢", "谢谢", "太好了", "好棒", "厉害"]):
            self.apply_stimulus(delta_joy=0.15, delta_meta=0.05)
        elif any(w in text for w in ["难过", "伤心", "痛苦", "哭了", "糟透了", "失落", "郁闷"]):
            self.apply_stimulus(delta_sorrow=0.15, delta_joy=-0.1)
        elif any(w in text for w in ["笨", "讨厌", "闭嘴", "滚", "生气", "差劲", "垃圾"]):
            self.apply_stimulus(delta_anger=0.2, delta_meta=-0.1)
        elif any(w in text for w in ["害怕", "担心", "恐怖", "糟糕", "焦虑", "紧张"]):
            self.apply_stimulus(delta_fear=0.15, delta_meta=-0.05)

    def perception_prompt(self) -> str:
        """产出注入上下文的情绪提示词"""
        dom, val = self.state.dominant_emotion()
        return f"【当前内心状态】整体心境：{dom}（外显强度: {val:.2f}，愉悦度: {self.state.joy:.2f}，平静理智: {self.state.meta:.2f}）。"
