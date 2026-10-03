# skills/__init__.py
# dsn_study 技能包 — loader/manager 复用 apps.dsn.skills（符号链接），
# registry 为本应用本地实现；不包含 dsn 的人格蒸馏（distill）。

from .loader import SkillLoader, Skill, ToolSpec, SkillPrompt
from .registry import SkillRegistry
from .manager import SkillManager

__all__ = [
    "SkillLoader",
    "Skill",
    "ToolSpec",
    "SkillPrompt",
    "SkillRegistry",
    "SkillManager",
]
