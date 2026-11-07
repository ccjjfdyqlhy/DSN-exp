# harness/skills/yaml_loader.py
# 技能加载器 —— **YAML 声明式**技能（skill.yaml + prompts/*.md + tools/*.py）。
#
# 下沉说明（2026-10 消除符号链接）：这套实现原先在 apps/dsn/skills/loader.py，
# apps/dsn_study 通过**符号链接**直接指向它 —— 改一处会静默影响另一个应用，
# 且在 Windows / 打包场景会直接断。现下沉到 harness/skills/，
# 两个应用各自 import 同一份实现，行为一致且无文件系统耦合。
#
# 与 harness/skills/loader.py 的区别：
#   * loader.py        —— 基于 Python 类（Skill 子类 + 顶层函数）的发现式装载
#   * yaml_loader.py  —— 基于 skill.yaml 的声明式装载（本文件）

from __future__ import annotations

import logging
import re
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("SkillLoader")

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


@dataclass
class ToolSpec:
    name: str = ""
    display_name: str = ""
    description: str = ""
    module: str = ""
    class_name: str = ""
    methods: list = field(default_factory=list)
    # 语义能力 → 实例属性名。工具类里也可以用类属性 needs 声明；
    # 两处都写时以这里的为准（插件作者不改工具源码也能声明依赖）。
    needs: dict = field(default_factory=dict)


@dataclass
class SkillPrompt:
    name: str = ""
    category: str = "skills"
    priority: int = 60
    content: str = ""
    source_file: str = ""


@dataclass
class Skill:
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
    # skill.env 解析结果（由 harness.skills.env_loader 填充）
    env: dict = field(default_factory=dict)


def _as_int(value: Any, default: int = 0) -> int:
    """宽松转 int：YAML 里写成 '70'（带引号）也能吃下，转不动就用默认值。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def resolve_tool_module_path(skill_dir: str, module_path: str) -> Optional[Path]:
    """把 skill.yaml 的 module 字段解析成工具文件路径。

    支持三种写法（都指向同一个文件时行为一致）：
      "tools.gaokzx_tools"     → <skill_dir>/tools/gaokzx_tools.py
      "tools/gaokzx_tools.py"  → <skill_dir>/tools/gaokzx_tools.py
      "gaokzx_tools.py"        → <skill_dir>/tools/gaokzx_tools.py
    """
    if not module_path:
        return None
    base = Path(skill_dir)
    if module_path.endswith(".py"):
        rel = module_path.replace("\\", "/")
        return base / rel if "/" in rel else base / "tools" / rel
    parts = module_path.split(".")
    if len(parts) == 1:
        return base / "tools" / f"{parts[0]}.py"
    sub = "/".join(parts[:-1])
    return base / sub / f"{parts[-1]}.py"


class SkillLoader:

    TYPE_MAP = {
        "string": "string", "str": "string",
        "integer": "integer", "int": "integer",
        "boolean": "boolean", "bool": "boolean",
        "array": "array", "list": "array",
        "object": "object", "dict": "object",
        "number": "number", "float": "number",
    }

    def load(self, skill_dir: str) -> Optional[Skill]:
        path = Path(skill_dir)
        yaml_file = path / "skill.yaml"
        if not yaml_file.exists():
            raise FileNotFoundError(f"skill.yaml not found in {skill_dir}")
        with open(yaml_file, "r", encoding='utf-8-sig') as f:
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
            prompt_priority=_as_int(data.get("prompt_priority", 60), 60),
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
                text = md_file.read_text(encoding='utf-8-sig')
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
            spec = ToolSpec(
                name=t.get("name", ""),
                display_name=t.get("display_name", ""),
                description=t.get("description", ""),
                module=t.get("module", ""),
                class_name=t.get("class", ""),
                methods=t.get("methods", []),
                needs=t.get("needs", {}) or {},
            )
            spec.async_mode = t.get("async", False)
            spec.estimated_duration = t.get("estimated_duration", "")
            specs.append(spec)
        return specs

    def build_function_schema(self, skill_name: str, tool_spec: ToolSpec) -> dict:
        func_name = f"skill-{skill_name}-{tool_spec.name}"
        parameters = self._extract_parameters(tool_spec)
        return {
            "type": "function",
            "function": {
                "name": func_name,
                "description": tool_spec.description,
                "parameters": parameters,
            }
        }

    def _extract_parameters(self, tool_spec: ToolSpec) -> dict:
        properties = {}
        required = []
        for method in tool_spec.methods:
            if isinstance(method, str):
                continue
            if isinstance(method, dict):
                params = method.get("parameters", {})
                if not params:
                    continue
                if isinstance(params, dict):
                    for param_name, param_def in params.items():
                        if not isinstance(param_def, dict):
                            continue
                        schema = self._param_def_to_schema(param_def)
                        properties[param_name] = schema
                        if param_def.get("required"):
                            required.append(param_name)
        result = {
            "type": "object",
            "properties": properties,
        }
        if required:
            result["required"] = required
        return result

    def _param_def_to_schema(self, param_def: dict) -> dict:
        raw_type = param_def.get("type", "string")
        schema_type = self.TYPE_MAP.get(raw_type, "string")
        schema = {"type": schema_type}
        if "description" in param_def:
            schema["description"] = param_def["description"]
        if "default" in param_def:
            schema["default"] = param_def["default"]
        if schema_type == "array":
            if "items" in param_def:
                schema["items"] = self._param_def_to_schema(param_def["items"])
            else:
                schema["items"] = {"type": "string"}
        return schema
