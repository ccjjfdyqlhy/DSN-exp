# apps/dsn_study/skills/loader.py
# 声明式（YAML）技能加载器 —— 复用 harness 的唯一实现。
#
# 去重说明（2026-10 消除符号链接）：本文件原先是指向 apps/dsn/skills/loader.py 的
# **符号链接**。改 dsn 那一侧会静默改变 dsn_study 的行为，且在 Windows /
# 打包场景直接失效。现在两边都从 harness 的唯一实现导入，行为一致且无耦合。

from __future__ import annotations

from harness.skills.yaml_loader import (  # noqa: F401
    Skill,
    SkillLoader,
    SkillPrompt,
    ToolSpec,
)

__all__ = ["Skill", "SkillLoader", "SkillPrompt", "ToolSpec"]
