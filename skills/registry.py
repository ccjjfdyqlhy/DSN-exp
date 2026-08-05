# skills/registry.py
# 技能注册表 — 工具加载/调用 + 提示词聚合 + 原生 tool call schema 生成

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("SkillRegistry")


class SkillRegistry:
    def __init__(self):
        self._tool_instances: dict[str, Any] = {}
        self._tool_specs: dict[str, dict] = {}
        self._skill_prompts: dict[str, str] = {}
        self._active_skills: dict[str, "Skill"] = {}
        self._tool_class_cache: dict[str, Any] = {}

    def register_skill(self, skill: "Skill", deps: dict = None) -> None:
        self._active_skills[skill.name] = skill
        deps = deps or {}

        if skill.tools:
            for tool_spec in skill.tools:
                try:
                    instance = self._load_tool(tool_spec, skill.skill_dir, deps)
                    if instance:
                        key = f"{skill.name}.{tool_spec.name}"
                        self._tool_instances[key] = instance
                        self._tool_specs[key] = {
                            "name": tool_spec.name,
                            "display_name": tool_spec.display_name,
                            "description": tool_spec.description,
                            "module": tool_spec.module,
                            "class": tool_spec.class_name,
                            "methods": tool_spec.methods,
                            "async": getattr(tool_spec, "async_mode", False),
                            "estimated_duration": getattr(tool_spec, "estimated_duration", ""),
                            "_tool_spec_obj": tool_spec,
                            "_skill_name": skill.name,
                        }
                        logger.info("注册技能工具: %s", key)
                except Exception as e:
                    logger.error("加载工具失败 %s.%s: %s",
                                 skill.name, tool_spec.name, e)

        prompts_content: list[str] = []
        for prompt in skill.prompts:
            if prompt.content.strip():
                prompts_content.append(prompt.content)
        if prompts_content:
            self._skill_prompts[skill.name] = "\n\n".join(prompts_content)

    def unregister_skill(self, name: str) -> None:
        self._active_skills.pop(name, None)
        self._skill_prompts.pop(name, None)
        keys_to_remove = [k for k in self._tool_instances
                          if k.startswith(f"{name}.")]
        for key in keys_to_remove:
            self._tool_instances.pop(key, None)
            self._tool_specs.pop(key, None)

    def call_tool(self, skill_name: str, tool_name: str,
                  params: dict[str, Any]) -> Any:
        key = f"{skill_name}.{tool_name}"
        instance = self._tool_instances.get(key)
        if not instance:
            raise ValueError(f"工具不存在: {key}")
        method = getattr(instance, tool_name, None)
        if not method or not callable(method):
            raise ValueError(f"工具方法不存在: {key}.{tool_name}")
        return method(**params)

    def get_tool_spec(self, skill_name: str, tool_name: str) -> dict | None:
        return self._tool_specs.get(f"{skill_name}.{tool_name}")

    def get_all_tool_specs(self) -> list[dict]:
        return [{**spec, "skill": key.split(".")[0], "full_name": key}
                for key, spec in self._tool_specs.items()]

    def get_all_skill_prompts(self) -> str:
        contents = [c for c in self._skill_prompts.values() if c.strip()]
        return "\n\n".join(contents) if contents else ""

    def has_skill(self, name: str) -> bool:
        return name in self._active_skills

    def list_active_tools(self) -> list[str]:
        return list(self._tool_instances.keys())

    def list_skills(self) -> list[dict]:
        result = []
        for skill in self._active_skills.values():
            result.append({
                "name": skill.name,
                "display_name": skill.display_name,
                "description": skill.description,
                "version": skill.version,
                "author": skill.author,
                "source": skill.source,
                "enabled": skill.enabled,
                "status": skill.status,
                "tags": skill.tags,
                "has_tools": bool(skill.tools),
                "prompt_count": len(skill.prompts),
            })
        return result

    def get_skill(self, name: str) -> "Skill | None":
        return self._active_skills.get(name)

    def get_tools_index(self) -> list[dict]:
        index = []
        for key, spec in self._tool_specs.items():
            index.append({
                "id": key,
                "skill": spec.get("_skill_name", ""),
                "name": spec["name"],
                "description": spec.get("description", ""),
            })
        return index

    def get_tools_schema(self) -> list[dict]:
        from skills.loader import SkillLoader
        loader = SkillLoader()
        tools = []
        for key, spec in self._tool_specs.items():
            tool_spec_obj = spec.get("_tool_spec_obj")
            if tool_spec_obj is None:
                skill = self._active_skills.get(spec.get("_skill_name", ""))
                if skill:
                    for ts in skill.tools:
                        if ts.name == spec["name"]:
                            tool_spec_obj = ts
                            break
            if tool_spec_obj:
                schema = loader.build_function_schema(
                    spec.get("_skill_name", ""), tool_spec_obj)
                tools.append(schema)
        return tools

    def _load_tool(self, tool_spec, skill_dir: str,
                    deps: dict = None) -> Any:
        module_path = (getattr(tool_spec, "module", "")
                       or tool_spec.get("module", ""))
        class_name = (getattr(tool_spec, "class_name", "")
                      or tool_spec.get("class", ""))
        if not module_path or not class_name:
            return None

        parts = module_path.split(".")
        file_name = parts[-1] + ".py"
        sub = "/".join(parts[:-1])
        file_path = (Path(skill_dir) / sub / file_name
                     if sub else Path(skill_dir) / "tools" / file_name)
        # 类缓存键必须包含技能目录，避免不同技能声明相同的 module/class 字符串时
        # 相互污染实例（例如 system 与 plan 都声明 "tools.plan_tools.PlanTools"，
        # 但二者的 PlanTools 方法集不同）。
        cache_key = f"{Path(skill_dir).resolve()}:{module_path}:{class_name}"
        if cache_key in self._tool_class_cache:
            return self._tool_class_cache[cache_key]

        if not file_path.exists():
            logger.warning("工具文件不存在: %s", file_path)
            return None

        spec = importlib.util.spec_from_file_location(
            f"skill_tools.{module_path.replace('.', '_')}", str(file_path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cls = getattr(mod, class_name, None)
        if not cls:
            return None

        deps = deps or {}
        try:
            instance = cls(**deps)
        except TypeError:
            instance = cls()

        if hasattr(cls, "set_context") and deps:
            cls.set_context(**deps)

        self._tool_class_cache[cache_key] = instance
        return instance
