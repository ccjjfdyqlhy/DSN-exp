# harness/skills/__init__.py
# 通用技能层。
#
# 这里有**两套**技能抽象，名字容易混：
#
#   base.Skill / base.SkillRegistry / loader.SkillLoader
#       —— 「发现式」：按 Python 类 / 顶层函数自动发现工具。
#          历史 API，保持原样导出（tests/test_harness_coding.py 等在用）。
#
#   yaml_loader / yaml_manager / registry（YAML 声明式）
#       —— 「声明式」：skill.yaml + prompts/*.md + tools/*.py。
#          这是 apps/dsn 与 apps/dsn_study 实际使用的技能系统。
#          为了不与 base 的同名类冲突，这里以 Yaml* 前缀导出；
#          应用侧仍可直接 `from harness.skills.registry import SkillRegistry`。
#
# 2026-11 新增（"免踩坑"）：
#   * CapabilityRegistry —— 能力注册表，技能依赖注入的唯一来源
#   * SkillValidator     —— 加载期一致性校验（类/方法/参数/依赖）
#   * load_skill_envs    —— 技能私有配置 skill.env 加载
#   * bridge_skills_to_agent —— 技能工具桥接到 AgentLoop

from .base import Skill, SkillRegistry
from .loader import SkillLoader

from .capabilities import CapabilityRegistry
from .validator import SkillValidator, ValidationIssue, ValidationReport
from .env_loader import load_skill_envs, parse_skill_env
from .yaml_loader import (
    Skill as YamlSkill,
    SkillLoader as YamlSkillLoader,
    SkillPrompt,
    ToolSpec,
    resolve_tool_module_path,
)
from .yaml_manager import SkillManager
from .registry import SkillRegistry as YamlSkillRegistry
from .agent_bridge import bridge_skills_to_agent

__all__ = [
    # 发现式（历史 API）
    "Skill",
    "SkillRegistry",
    "SkillLoader",
    # 声明式（YAML）
    "YamlSkill",
    "YamlSkillLoader",
    "YamlSkillRegistry",
    "SkillManager",
    "SkillPrompt",
    "ToolSpec",
    "resolve_tool_module_path",
    # 能力与校验
    "CapabilityRegistry",
    "SkillValidator",
    "ValidationIssue",
    "ValidationReport",
    "load_skill_envs",
    "parse_skill_env",
    # 桥接
    "bridge_skills_to_agent",
]
