# skills/__init__.py
# dsn 技能包 — loader/manager/registry 全部复用 harness 的唯一实现；
# 另含本应用特有的人格蒸馏（distill）。
#
# 2026-11：loader/manager/registry 三件套都下沉到 harness/skills/，
# 两个应用共用同一份实现，行为一致。

from .loader import SkillLoader, Skill, ToolSpec, SkillPrompt
from .registry import SkillRegistry
from .manager import SkillManager
from .distill import DistillationEngine

from harness.skills.capabilities import CapabilityRegistry
from harness.skills.validator import SkillValidator, ValidationIssue, ValidationReport

__all__ = [
    "SkillLoader",
    "Skill",
    "ToolSpec",
    "SkillPrompt",
    "SkillRegistry",
    "SkillManager",
    "DistillationEngine",
    "CapabilityRegistry",
    "SkillValidator",
    "ValidationIssue",
    "ValidationReport",
]
