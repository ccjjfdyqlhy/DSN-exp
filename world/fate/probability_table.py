# world/fate/probability_table.py
# 概率表 — 加权随机 + 叙事分支裁决

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class WeightedResult:
    """概率表单次投掷结果"""
    value: Any                       # 选中的结果
    metadata: dict = field(default_factory=dict)   # 附带元数据
    probability: float = 0.0         # 该结果实际使用的概率
    index: int = -1                  # 在表中的索引
    label: str = ""                  # 可读标签


class ProbabilityTable:
    """
    概率表 → 按权重随机选择。

    支持：
    - 浮点权重（自动归一化）
    - 整数权重（总和无需=1）
    - 附带元数据（每个结果可携带 context）
    - 上下文修正（根据外部条件动态调整权重）
    """

    def __init__(self, entries: list, label: str = ""):
        """
         entries:  [(权重, 结果值, 可选dict元数据), ...]
         例:
           [
             (0.40, "晴朗", {"mood_shift": +1}),
             (0.30, "多云", {"mood_shift": 0}),
             (0.20, "小雨", {"mood_shift": -1}),
             (0.10, "雷暴", {"mood_shift": -2, "danger": True}),
           ]
         也支持简洁格式:
           [("晴朗", 0.40), ("多云", 0.30)]
        """
        self._label = label
        self._entries: list[tuple[float, Any, dict]] = []
        for entry in entries:
            if isinstance(entry, tuple) and len(entry) >= 2:
                if isinstance(entry[0], (int, float)):  # (权重, 值, 元数据?)
                    prob, val = entry[0], entry[1]
                    meta = entry[2] if len(entry) > 2 else {}
                elif isinstance(entry[1], (int, float)):  # (值, 权重, 元数据?)
                    val, prob = entry[0], entry[1]
                    meta = entry[2] if len(entry) > 2 else {}
                else:
                    continue
                self._entries.append((prob, val, meta))

    def roll(self, context_modifiers: Optional[dict[str, float]] = None) -> WeightedResult:
        """
        按概率投掷一次。

        context_modifiers: 上下文修正因子
          {"晴朗": +0.1, "雷暴": -0.05}  # 增加/减少特定结果的权重
        """
        weights = [e[0] for e in self._entries]
        values = [e[1] for e in self._entries]
        metas = [e[2] for e in self._entries]

        # 应用上下文修正
        if context_modifiers:
            for i, (val, meta) in enumerate(zip(values, metas)):
                key = str(val)
                if key in context_modifiers:
                    weights[i] = max(0.0, weights[i] + context_modifiers[key])

        # 归一化
        total = sum(weights)
        if total <= 0:
            weights = [1.0 / len(weights)] * len(weights)
        else:
            weights = [w / total for w in weights]

        # 随机选择
        r = random.random()
        cumulative = 0.0
        for i, w in enumerate(weights):
            cumulative += w
            if r <= cumulative:
                return WeightedResult(
                    value=values[i],
                    metadata=metas[i],
                    probability=w,
                    index=i,
                    label=self._label,
                )

        # fallback
        return WeightedResult(
            value=values[-1] if values else None,
            metadata=metas[-1] if metas else {},
            probability=weights[-1] if weights else 0.0,
            index=len(self._entries) - 1,
            label=self._label,
        )

    @property
    def entries(self) -> list[tuple[float, Any, dict]]:
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)


class WeightedChoice:
    """
    简化的单项加权选择器 — 用于"这件事有XX%概率发生"的场景。

    例：
      if WeightedChoice(0.3).roll():  # 30% 概率触发
          ...
    """

    def __init__(self, probability: float, label: str = ""):
        self._prob = max(0.0, min(1.0, probability))
        self._label = label

    def roll(self) -> bool:
        return random.random() < self._prob

    def __repr__(self) -> str:
        return f"WeightedChoice({self._prob:.1%})"
