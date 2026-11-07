# skills/__init__.py
# dsn_study 技能包 — loader/manager/registry 全部复用 harness 的唯一实现；
# 不包含 dsn 的人格蒸馏（distill）。
#
# 2026-11：loader/manager/registry 三件套都下沉到 harness/skills/，
# 两个应用共用同一份实现，行为一致（此前 dsn 与 dsn_study 各有一份
# registry 副本，方法集还不一样）。

from .loader import SkillLoader, Skill, ToolSpec, SkillPrompt
from .registry import SkillRegistry
from .manager import SkillManager

from harness.skills.capabilities import CapabilityRegistry
from harness.skills.validator import SkillValidator, ValidationIssue, ValidationReport

__all__ = [
    "SkillLoader",
    "Skill",
    "ToolSpec",
    "SkillPrompt",
    "SkillRegistry",
    "SkillManager",
    "CapabilityRegistry",
    "SkillValidator",
    "ValidationIssue",
    "ValidationReport",
]
