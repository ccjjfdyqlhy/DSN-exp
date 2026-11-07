# harness/skills/capabilities.py
# 能力（capability）注册表 —— 技能依赖注入的**唯一来源**。
#
# 为什么要有它（2026-11 改造动机）：
#   改造前，技能的依赖注入靠应用层维护一张**硬编码**的映射表
#   （apps/dsn_study/boot.py 的 _build_skill_dep_map）：
#
#       "question_bank": dict(_store=..., _tm=..., _models=...)
#
#   三个坑：
#     1. 表里没有的技能 → 依赖**静默丢失**。工具里 self._store 一直是 None，
#        直到用户真的调它才报错，错误信息还往往指向业务逻辑而不是"依赖没注入"。
#     2. 表里的 key 是**实例属性名**（_store/_tm/_models），不是语义名。
#        skill.yaml 里的 dependencies: [question_store, template_manager]
#        写的是语义名，两套命名空间对不上 —— dependencies 字段实际上是**死字段**，
#        没有任何代码读它。
#     3. 写新技能必须去改应用的 boot.py —— 技能没法真正"插拔"。
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
