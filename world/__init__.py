# world/__init__.py
# 叙事世界模型 — 独立模块 (v4)

from .engine import WorldEngine, ACTIVATION_PROMPT
from .state_manager import WorldStateManager
from .narrative_model import NarrativeModel
from .plugin import WorldPlugin
from .action_narrator import ActionNarrator, ActionNarrativeCollector

from .fate import Dice, DicePool, DiceResult
from .fate import ProbabilityTable, WeightedResult

__all__ = [
    "WorldEngine",
    "ACTIVATION_PROMPT",
    "WorldStateManager",
    "NarrativeModel",
    "WorldPlugin",
    "ActionNarrator",
    "ActionNarrativeCollector",
    "Dice",
    "DicePool",
    "DiceResult",
    "ProbabilityTable",
    "WeightedResult",
]
