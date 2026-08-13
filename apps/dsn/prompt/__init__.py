# prompt/__init__.py
from .library import PromptLibrary

# v2 — 当前人格系统
from .personality_v2 import (
    PersonalitySystemV2,
    EmotionModule,
    EmotionalStimulus,
    MoodProfile,
    StimulusAnalyzer,
    AffinityModule,
    ActionClassifier,
    AFFINITY_LEVELS,
    HabitModule,
    Habit,
    PatternObserver,
    PersonalityStateStore,
)

from .engine import PromptEngine, init_prompt_engine, get_system_prompt

__all__ = [
    "PersonalitySystemV2",
    "EmotionModule",
    "EmotionalStimulus",
    "MoodProfile",
    "StimulusAnalyzer",
    "AffinityModule",
    "ActionClassifier",
    "AFFINITY_LEVELS",
    "HabitModule",
    "Habit",
    "PatternObserver",
    "PersonalityStateStore",
    "PromptLibrary",
    "PromptEngine",
    "init_prompt_engine",
    "get_system_prompt",
]
