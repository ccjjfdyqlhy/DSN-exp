# world/fate/__init__.py
# 命运引擎 — 骰子 + 概率表 + 叙事分支

from .dice import Dice, DicePool, DiceResult
from .probability_table import ProbabilityTable, WeightedResult

__all__ = [
    "Dice",
    "DicePool",
    "DiceResult",
    "ProbabilityTable",
    "WeightedResult",
]
