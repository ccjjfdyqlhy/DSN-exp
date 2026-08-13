# harness/skills/base.py
# 通用技能抽象 — Skill 是一组工具的封装单元。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..tools import Tool, ToolRegistry


@dataclass
class Skill:
    """一个可装卸的技能 = 一组工具。"""
    name: str
    description: str
    tools: list[Tool] = field(default_factory=list)
    version: str = "1.0"

    def install(self, registry: ToolRegistry, *, prefix: bool = True) -> None:
        for tool in self.tools:
            registry.register(tool)


class SkillRegistry:
    """技能注册表。技能可整体装卸。"""

    def __init__(self, tool_registry: ToolRegistry):
        self._skills: dict[str, Skill] = {}
        self._tools = tool_registry

    def register(self, skill: Skill, *, replace: bool = False) -> Skill:
        if skill.name in self._skills and not replace:
            raise KeyError(f"技能已注册: {skill.name}")
        self._skills[skill.name] = skill
        skill.install(self._tools)
        return skill

    def unregister(self, name: str) -> bool:
        skill = self._skills.pop(name, None)
        if skill is None:
            return False
        for tool in skill.tools:
            self._tools.unregister(tool.name)
        return True

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def names(self) -> list[str]:
        return list(self._skills.keys())

    def __len__(self) -> int:
        return len(self._skills)
