# skills/loader.py
# 技能加载器 — 从目录加载技能定义 (skill.yaml + prompts/*.md + tools/*.py)

from __future__ import annotations

import logging
import re
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("SkillLoader")

# frontmatter 正则
_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


@dataclass
class ToolSpec:
    """工具规格 — 定义技能中的一个工具"""
    name: str = ""
    display_name: str = ""
    description: str = ""
    module: str = ""           # "tools.search"
    class_name: str = ""       # "WebSearchTool"
    methods: list = field(default_factory=list)


@dataclass
class SkillPrompt:
    """技能内的提示词文件"""
    name: str = ""
    category: str = "skills"
    priority: int = 60
    content: str = ""
    source_file: str = ""


@dataclass
class Skill:
    """技能定义 — 提示词 + 可选工具的能力包"""
    name: str
    display_name: str = ""
    description: str = ""
    version: str = "1.0"
    author: str = "system"
    source: str = "builtin"
    enabled: bool = True
    status: str = "active"

    prompt_category: str = "skills"
    prompt_priority: int = 60

    tools: list[ToolSpec] = field(default_factory=list)
    prompts: list[SkillPrompt] = field(default_factory=list)

    activation: dict = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    skill_dir: str = ""


class SkillLoader:
    """
    技能加载器。

    职责:
    - 从技能目录读取 skill.yaml + prompts/*.md
    - 解析 tools 定义为 ToolSpec 列表
    - 构造 Skill 数据类实例
    """

    def load(self, skill_dir: str) -> Optional[Skill]:
        path = Path(skill_dir)
        yaml_file = path / "skill.yaml"

        if not yaml_file.exists():
            raise FileNotFoundError(f"skill.yaml not found in {skill_dir}")

        with open(yaml_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data or "name" not in data:
            raise ValueError("Invalid skill.yaml: missing 'name'")

        prompts = self._load_prompts(path / "prompts")
        tools = self._parse_tools(data.get("tools", []))

        return Skill(
            name=data["name"],
            display_name=data.get("display_name", data["name"]),
            description=data.get("description", ""),
            version=data.get("version", "1.0"),
            author=data.get("author", "system"),
            source=data.get("source", "builtin"),
            enabled=data.get("enabled", True),
            status=data.get("status", "active"),
            prompt_category=data.get("prompt_category", "skills"),
            prompt_priority=data.get("prompt_priority", 60),
            tools=tools,
            prompts=prompts,
            activation=data.get("activation", {}),
            dependencies=data.get("dependencies", []),
            tags=data.get("tags", []),
            skill_dir=str(path),
        )

    def _load_prompts(self, prompts_dir: Path) -> list[SkillPrompt]:
        prompts: list[SkillPrompt] = []
        if not prompts_dir.exists():
            return prompts

        for md_file in sorted(prompts_dir.glob("*.md")):
            try:
                text = md_file.read_text(encoding="utf-8")
                match = _FM_RE.match(text)
                if match:
                    meta = yaml.safe_load(match.group(1)) or {}
                    content = match.group(2).strip()
                else:
                    meta = {}
                    content = text.strip()

                prompts.append(SkillPrompt(
                    name=meta.get("name", md_file.stem),
                    category=meta.get("category", "skills"),
                    priority=meta.get("priority", 60),
                    content=content,
                    source_file=str(md_file),
                ))
            except Exception as e:
                logger.error("加载技能提示词失败 %s: %s", md_file, e)
        return prompts

    def _parse_tools(self, tools_data: list) -> list[ToolSpec]:
        specs: list[ToolSpec] = []
        for t in tools_data:
            specs.append(ToolSpec(
                name=t.get("name", ""),
                display_name=t.get("display_name", ""),
                description=t.get("description", ""),
                module=t.get("module", ""),
                class_name=t.get("class", ""),
                methods=t.get("methods", []),
            ))
        return specs
