# harness/skills/loader.py
# SkillLoader — 从模块/包自动发现并注册技能。
#
# 支持两种来源：
#   - 普通函数 → 经 tool_from_function 自动生成 Tool
#   - harness.skills.base.Skill 子类 → 安装其 tools
#
# 用法:
#     loader = SkillLoader()
#     loader.install_package("myapp.skills", registry, namespace="fs")

from __future__ import annotations

import importlib
import inspect
import logging
from pathlib import Path
from typing import Any, Optional

from ..tools import ToolRegistry
from ..tools.function_tool import tool_from_function
from .base import Skill

logger = logging.getLogger("harness.skills")


class SkillLoader:
    """技能自动发现器。"""

    def install_module(self, module, registry: ToolRegistry, *,
                       namespace: str = "",
                       include: Optional[list[str]] = None,
                       init_kwargs: Optional[dict] = None) -> list[str]:
        """从模块发现函数与 Skill 子类，注册进 registry。返回安装的工具名。"""
        if isinstance(module, str):
            module = importlib.import_module(module)
        init_kwargs = init_kwargs or {}
        installed: list[str] = []

        for name, obj in inspect.getmembers(module, inspect.isclass):
            if name.startswith("_"):
                continue
            if obj is Skill:
                continue
            if not (isinstance(obj, type) and issubclass(obj, Skill)):
                continue
            if include and name not in include:
                continue
            try:
                skill = obj(**init_kwargs)
                skill.install(registry)
                installed.extend(t.name for t in skill.tools)
            except Exception:
                logger.exception("技能 %s 实例化失败", name)

        # 顶层函数 → Tool
        for name, obj in inspect.getmembers(module, inspect.isfunction):
            if name.startswith("_"):
                continue
            if include and name not in include:
                continue
            try:
                tool = tool_from_function(obj, namespace=namespace)
                registry.register(tool)
                installed.append(tool.name)
            except (ValueError, TypeError):
                continue
        return installed

    def install_package(self, package: str, registry: ToolRegistry, *,
                        namespace: str = "",
                        exclude: Optional[list[str]] = None) -> list[str]:
        """递归发现包内所有 py 模块的技能。"""
        fs_path = Path(package.replace(".", "/"))
        if not fs_path.exists():
            logger.warning("包目录不存在: %s", fs_path)
            return []
        exclude = set(exclude or [])
        installed: list[str] = []
        for py_file in sorted(fs_path.rglob("*.py")):
            if py_file.name.startswith("_"):
                continue
            rel = py_file.relative_to(fs_path)
            module = package + "." + str(rel).replace("\\", "/").replace("/", ".")[:-3]
            if any(x in module for x in exclude):
                continue
            installed.extend(self.install_module(module, registry, namespace=namespace))
        return installed
