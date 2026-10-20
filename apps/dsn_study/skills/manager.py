# apps/dsn_study/skills/manager.py
# 声明式（YAML）技能管理器 —— 复用 harness 的唯一实现。
#
# 去重说明（2026-10 消除符号链接）：原先是指向 apps/dsn/skills/manager.py 的符号链接。

from __future__ import annotations

from harness.skills.yaml_manager import SkillManager  # noqa: F401

__all__ = ["SkillManager"]
