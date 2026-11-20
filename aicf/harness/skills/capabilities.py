# harness/skills/capabilities.py
# capability registry: the single source for skill dependency injection.
#
# Why it exists:
#   Dependency injection used to rely on a hardcoded application map:
#
#       "question_bank": dict(_store=..., _tm=..., _models=...)
#
#   That caused three problems:
#     1. A skill missing from the table lost its dependencies silently. The tool
#        kept self._store as None until a user called it, and the error pointed
#        at business logic rather than at the missing injection.
#     2. The table keys were attribute names (_store, _tm), while skill.yaml
#        declared semantic names (question_store, template_manager). The two
#        namespaces never matched, so dependencies was a dead field.
#     3. A new skill required editing the application boot module, so skills were
#        not pluggable.
#
# 现在：
#   * 应用层注册**语义能力**：register("question_store", store)
#   * 技能在 skill.yaml 的 dependencies 里声明它需要哪些语义能力；
#   * 工具类用类属性 needs = {"question_store": "_store"} 声明
#     "语义能力 → 实例属性名" 的映射，由 harness 自动注入；
#   * 能力缺失 → **显式报错**，不再静默。
#
# 兼容性：老的硬编码映射表仍然可用（inject_dependencies 走 hasattr 判断，
# 行为不变）。两套机制并存，新技能走 needs，老技能不受影响。

from __future__ import annotations

import logging
from typing import Any, Iterable

logger = logging.getLogger("SkillCapabilities")


class CapabilityRegistry:
    """能力注册表 —— 名字 → 实例的映射，支持别名。"""

    def __init__(self) -> None:
        self._capabilities: dict[str, Any] = {}
        self._aliases: dict[str, str] = {}

    # ── 注册 ──

    def register(self, name: str, instance: Any = None, *,
                 aliases: Iterable[str] = ()) -> None:
        """注册一个能力。aliases 里的名字指向同一个实例。"""
        if not name:
            raise ValueError("能力名不能为空")
        self._capabilities[name] = instance
        for alias in aliases:
            if alias and alias != name:
                self._aliases[alias] = name
        logger.debug("注册能力: %s%s", name,
                     f" (别名 {list(aliases)})" if aliases else "")

    def register_many(self, mapping: dict[str, Any], *,
                      aliases: dict[str, Iterable[str]] | None = None) -> None:
        """批量注册。mapping: {能力名: 实例}。"""
        aliases = aliases or {}
        for name, instance in mapping.items():
            self.register(name, instance, aliases=aliases.get(name, ()))

    def unregister(self, name: str) -> bool:
        existed = name in self._capabilities
        self._capabilities.pop(name, None)
        for alias, target in list(self._aliases.items()):
            if target == name:
                del self._aliases[alias]
        return existed

    # ── 查询 ──

    def get(self, name: str, default: Any = None) -> Any:
        if name in self._capabilities:
            return self._capabilities[name]
        target = self._aliases.get(name)
        if target is not None:
            return self._capabilities.get(target, default)
        return default

    def resolve(self, names: Iterable[str]) -> tuple[dict[str, Any], list[str]]:
        """解析一组能力名 → (找到的 {名: 实例}, 缺失的名字列表)。"""
        found: dict[str, Any] = {}
        missing: list[str] = []
        for name in names or ():
            if not name:
                continue
            if name in found:
                continue
            instance = self.get(name)
            if instance is None:
                missing.append(name)
            else:
                found[name] = instance
        return found, missing

    def names(self) -> list[str]:
        return sorted(self._capabilities.keys())

    def aliases(self) -> dict[str, str]:
        return dict(self._aliases)

    def snapshot(self) -> dict[str, str]:
        """诊断用：能力名 → 实例类型名。"""
        return {name: type(inst).__name__
                for name, inst in sorted(self._capabilities.items())}

    def __contains__(self, name: str) -> bool:
        return self.get(name, _MISSING) is not _MISSING

    def __len__(self) -> int:
        return len(self._capabilities)

    def __repr__(self) -> str:
        return f"<CapabilityRegistry {self.names()}>"


_MISSING = object()
