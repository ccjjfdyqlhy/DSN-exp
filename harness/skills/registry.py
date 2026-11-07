# harness/skills/registry.py
# 技能注册表 —— **harness 层唯一实现**。
#
# 改造前（2026-11）：apps/dsn/skills/registry.py 与 apps/dsn_study/skills/registry.py
# 是两份**各自维护**的副本，方法集还不一样（study 侧多 call_tool_async /
# is_async_tool / inject_dependencies / get_tool_instances）。改一边不会影响另一边，
# 于是"同一个技能在两个应用里行为不一致"这类问题很难排查。
#
# 现在：两边都 import 这一份，行为一致。
#
# 本模块相对旧版的增强：
#   1. **能力（capability）注入**：工具类用类属性 needs 声明
#      {"语义能力": "实例属性名"}，由应用注册的能力自动注入；
#      能力缺失 → 该工具**不注册**并记录错误（不再静默失效）。
#   2. **加载期校验**：工具类 / 方法 / 参数与实现对不上时跳过该工具并记录诊断，
#      技能其余工具照常可用。
#   3. **提示词按优先级聚合**：skill.yaml 的 prompt_priority 现在真的生效
#      （此前被完全忽略，所有提示词按字典序拼接）。
#   4. **诊断输出**：diagnostics() 返回所有问题，可通过 REST 查。

from __future__ import annotations

import importlib.util
import inspect
import logging
from pathlib import Path
from typing import Any, Optional

from .capabilities import CapabilityRegistry
from .validator import LEVEL_ERROR, SkillValidator, ValidationReport
from .yaml_loader import resolve_tool_module_path

logger = logging.getLogger("SkillRegistry")


class SkillRegistry:
    """技能注册表：工具加载/调用 + 提示词聚合 + tool call schema 生成。"""

    def __init__(self, *, capabilities: Optional[CapabilityRegistry] = None,
                 validator: Optional[SkillValidator] = None) -> None:
        self._tool_instances: dict[str, Any] = {}
        self._tool_specs: dict[str, dict] = {}
        self._skill_prompts: dict[str, str] = {}
        self._active_skills: dict[str, "Skill"] = {}
        self._tool_class_cache: dict[str, Any] = {}
        self._capabilities = capabilities or CapabilityRegistry()
        self._validator = validator or SkillValidator(self._capabilities)
        self._reports: dict[str, ValidationReport] = {}

    # ── 能力注册 ──

    def register_capability(self, name: str, instance: Any = None, *,
                            aliases=()) -> None:
        """注册一个可供技能注入的能力（语义名 → 实例）。"""
        self._capabilities.register(name, instance, aliases=aliases)

    def register_capabilities(self, mapping: dict[str, Any], *,
                              aliases: dict[str, list] | None = None) -> None:
        self._capabilities.register_many(mapping, aliases=aliases)

    def get_capability(self, name: str, default: Any = None) -> Any:
        return self._capabilities.get(name, default)

    def capability_names(self) -> list[str]:
        return self._capabilities.names()

    # ── 注册 / 注销 ──

    def register_skill(self, skill: "Skill", deps: dict = None) -> ValidationReport:
        """注册一个技能：加载工具类 → 校验 → 实例化 → 注入能力 → 注册。"""
        report = self._validator.validate_skill(skill)
        # 先注销同名技能的旧实例 —— 重新加载（reload/enable）时，
        # 旧工具实例如果不清掉会残留在注册表里（skill.yaml 删了工具也删不掉）。
        self.unregister_skill(skill.name)
        self._active_skills[skill.name] = skill
        deps = deps or {}

        if skill.tools:
            for tool_spec in skill.tools:
                key = f"{skill.name}.{tool_spec.name}"
                try:
                    cls = self._resolve_tool_class(tool_spec, skill.skill_dir)
                    issues = self._validator.validate_tool(
                        skill.name, tool_spec, cls)
                    report.extend(issues)
                    if any(i.level == LEVEL_ERROR for i in issues):
                        logger.error("工具 %s 校验未通过，已跳过: %s",
                                     key, "; ".join(
                                         i.message for i in issues
                                         if i.level == LEVEL_ERROR))
                        continue

                    instance = self._instantiate(cls, deps)
                    if instance is None:
                        report.add(LEVEL_ERROR, "instantiate-failed",
                                   skill.name,
                                   "工具类实例化失败", tool=tool_spec.name)
                        continue

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
                    self._inject_needs(instance, cls, skill.name, tool_spec.name,
                                       report)
                    logger.info("注册技能工具: %s", key)
                except Exception as e:
                    logger.error("加载工具失败 %s.%s: %s",
                                 skill.name, tool_spec.name, e)
                    report.add(LEVEL_ERROR, "load-failed", skill.name,
                               f"加载工具失败: {e}", tool=tool_spec.name)

        prompts_content: list[str] = []
        for prompt in skill.prompts:
            if prompt.content.strip():
                prompts_content.append(prompt.content)
        if prompts_content:
            self._skill_prompts[skill.name] = "\n\n".join(prompts_content)

        self._reports[skill.name] = report
        if report.issues:
            logger.warning("技能 %s 校验: %s", skill.name, report.summary())
        return report

    def unregister_skill(self, name: str) -> None:
        self._active_skills.pop(name, None)
        self._skill_prompts.pop(name, None)
        self._reports.pop(name, None)
        keys_to_remove = [k for k in self._tool_instances
                          if k.startswith(f"{name}.")]
        for key in keys_to_remove:
            self._tool_instances.pop(key, None)
            self._tool_specs.pop(key, None)

    # ── 依赖注入 ──

    def _inject_needs(self, instance: Any, cls: Any, skill_name: str,
                      tool_name: str, report: ValidationReport) -> int:
        """按工具类的 needs 声明注入能力实例。"""
        needs = getattr(cls, "needs", None) or {}
        if not isinstance(needs, dict) or not needs:
            return 0
        count = 0
        for cap, attr in needs.items():
            value = self._capabilities.get(cap)
            if value is None:
                logger.error("技能 %s.%s 需要能力 '%s'，但应用没有注册",
                             skill_name, tool_name, cap)
                report.add(LEVEL_ERROR, "capability-missing", skill_name,
                           f"工具需要能力 '{cap}'，但应用没有注册它",
                           tool=tool_name)
                continue
            try:
                setattr(instance, attr, value)
                count += 1
            except Exception as exc:
                logger.error("技能 %s.%s 注入能力 '%s' 到属性 %r 失败: %s",
                             skill_name, tool_name, cap, attr, exc)
                report.add(LEVEL_ERROR, "inject-failed", skill_name,
                           f"注入能力 '{cap}' 到 {attr!r} 失败: {exc}",
                           tool=tool_name)
        return count

    def inject_dependencies(self, skill_name: str, **deps) -> bool:
        """旧接口：按属性名直接注入（hasattr 才注入，行为与改造前一致）。

        新写的技能请用工具类的 needs 声明 + register_capability。
        """
        skill = self._active_skills.get(skill_name)
        if not skill:
            logger.warning("技能不存在: %s", skill_name)
            return False

        count = 0
        for tool_spec in skill.tools:
            key = f"{skill_name}.{tool_spec.name}"
            instance = self._tool_instances.get(key)
            if not instance:
                continue
            for dep_name, dep_value in deps.items():
                if hasattr(instance, dep_name):
                    setattr(instance, dep_name, dep_value)
                    count += 1
                else:
                    logger.debug("工具 %s 无属性 %s，跳过", key, dep_name)
        return count > 0

    # ── 工具调用 ──

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

    async def call_tool_async(self, skill_name: str, tool_name: str,
                              params: dict[str, Any]) -> Any:
        """异步调用工具：工具方法是协程时 await，否则直接返回。"""
        key = f"{skill_name}.{tool_name}"
        instance = self._tool_instances.get(key)
        if not instance:
            raise ValueError(f"工具不存在: {key}")
        method = getattr(instance, tool_name, None)
        if not method or not callable(method):
            raise ValueError(f"工具方法不存在: {key}.{tool_name}")
        if inspect.iscoroutinefunction(method):
            return await method(**params)
        return method(**params)

    def is_async_tool(self, skill_name: str, tool_name: str) -> bool:
        """工具方法是否为协程（决定桥接时用同步还是异步 handler）。"""
        instance = self._tool_instances.get(f"{skill_name}.{tool_name}")
        if not instance:
            return False
        method = getattr(instance, tool_name, None)
        return bool(method) and inspect.iscoroutinefunction(method)

    # ── 查询 ──

    def get_tool_spec(self, skill_name: str, tool_name: str) -> dict | None:
        return self._tool_specs.get(f"{skill_name}.{tool_name}")

    def get_all_tool_specs(self) -> list[dict]:
        return [{**spec, "skill": key.split(".")[0], "full_name": key}
                for key, spec in self._tool_specs.items()]

    def get_all_skill_prompts(self) -> str:
        """聚合所有技能的提示词。

        按 skill 的 prompt_priority 降序（高优先级在前），
        同优先级按名称稳定排序。此前 priority 字段被完全忽略。
        """
        items = []
        for name, content in self._skill_prompts.items():
            if not content.strip():
                continue
            skill = self._active_skills.get(name)
            priority = getattr(skill, "prompt_priority", 60) if skill else 60
            try:
                priority = int(priority)
            except (TypeError, ValueError):
                priority = 60
            items.append((priority, name, content))
        items.sort(key=lambda x: (-x[0], x[1]))
        return "\n\n".join(content for _, _, content in items)

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
        from .yaml_loader import SkillLoader
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

    def get_tool_instances(self, skill_name: str) -> list:
        instances = []
        for key, inst in self._tool_instances.items():
            if key.startswith(f"{skill_name}."):
                instances.append(inst)
        return instances

    # ── 诊断 ──

    def diagnostics(self) -> dict:
        """所有技能的校验问题（供 REST / 日志使用）。"""
        out = []
        for name, report in self._reports.items():
            if report.issues:
                out.append({"skill": name, **report.to_dict()})
        return {
            "skills_with_issues": len(out),
            "capabilities": self._capabilities.snapshot(),
            "reports": out,
        }

    def get_report(self, skill_name: str) -> Optional[ValidationReport]:
        return self._reports.get(skill_name)

    # ── 内部 ──

    def _resolve_tool_class(self, tool_spec, skill_dir: str) -> Optional[type]:
        """定位工具类。module 支持三种写法：
           "tools.foo"     → <技能目录>/tools/foo.py
           "tools/foo.py"  → <技能目录>/tools/foo.py
           "foo.py"        → <技能目录>/tools/foo.py
        """
        module_path = (getattr(tool_spec, "module", "")
                       or tool_spec.get("module", ""))
        class_name = (getattr(tool_spec, "class_name", "")
                      or tool_spec.get("class", ""))
        if not module_path or not class_name:
            return None

        file_path = resolve_tool_module_path(skill_dir, module_path)
        if file_path is None or not file_path.exists():
            logger.warning("工具文件不存在: %s (module=%s)",
                           file_path, module_path)
            return None

        # 类缓存键必须包含技能目录，避免不同技能声明相同的 module/class 字符串时
        # 相互污染实例（例如 system 与 plan 都声明 "tools.plan_tools.PlanTools"，
        # 但二者的 PlanTools 方法集不同）。
        cache_key = f"{Path(skill_dir).resolve()}:{module_path}:{class_name}"
        if cache_key in self._tool_class_cache:
            return self._tool_class_cache[cache_key]

        spec = importlib.util.spec_from_file_location(
            f"skill_tools.{module_path.replace('.', '_').replace('/', '_')}",
            str(file_path))
        if spec is None or spec.loader is None:
            logger.warning("工具模块无法加载: %s", file_path)
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cls = getattr(mod, class_name, None)
        if cls is None:
            logger.warning("工具文件中找不到类 %s: %s", class_name, file_path)
            return None

        self._tool_class_cache[cache_key] = cls
        return cls

    def _instantiate(self, cls: type, deps: dict) -> Optional[Any]:
        deps = deps or {}
        try:
            instance = cls(**deps)
        except TypeError:
            try:
                instance = cls()
            except Exception as exc:
                logger.error("工具类 %s 实例化失败: %s", cls.__name__, exc)
                return None
        except Exception as exc:
            logger.error("工具类 %s 实例化失败: %s", cls.__name__, exc)
            return None

        if hasattr(cls, "set_context") and deps:
            try:
                cls.set_context(**deps)
            except Exception as exc:
                logger.warning("set_context 失败: %s", exc)
        return instance

