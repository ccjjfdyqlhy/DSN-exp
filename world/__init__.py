# world/__init__.py
# 叙事世界模型 — 独立模块

from .engine import WorldEngine
from .state_manager import WorldStateManager
from .narrative_model import NarrativeModel
from .plugin import WorldPlugin

__all__ = [
    "WorldEngine",
    "WorldStateManager",
    "NarrativeModel",
    "WorldPlugin",
]
