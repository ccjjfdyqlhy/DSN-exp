"""插件自动发现与加载器 — 扫描 plugin.yaml、动态导入、自动注入依赖。"""

from __future__ import annotations

import importlib
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from harness.pipeline import Plugin, AsyncPlugin
from apps.dsn.plugins.container import PluginDIContainer

logger = logging.getLogger("PluginLoader")


@dataclass
class HookDef:
    hook: str
    priority: int = 50


@dataclass
class ConditionDef:
    dependency_exists: Optional[str] = None
    dependency_missing: Optional[str] = None


@dataclass
class PluginManifest:
    name: str
    description: str
    enabled: bool
    module: str
    class_name: str
    hooks: list[HookDef] = field(default_factory=list)
    dependencies: dict[str, str] = field(default_factory=dict)
    condition: Optional[ConditionDef] = None
    yaml_path: str = ""

    @property
    def full_class_path(self) -> str:
        return f"{self.module}:{self.class_name}"

    def meets_condition(self) -> bool:
        if self.condition is None:
            return True
        if self.condition.dependency_exists:
            val = PluginDIContainer.get(self.condition.dependency_exists)
            if val is None:
                logger.info("插件 %s 条件不满足: 依赖 %s 不可用(None)",
                            self.name, self.condition.dependency_exists)
                return False
        if self.condition.dependency_missing:
            val = PluginDIContainer.get(self.condition.dependency_missing)
            if val is not None:
                logger.info("插件 %s 条件不满足: 依赖 %s 存在(期望缺失)",
                            self.name, self.condition.dependency_missing)
                return False
        return True


class PluginLoader:
    """扫描 plugin.yaml，动态加载插件实例。"""

    def __init__(self, scan_dirs: list[str]):
        self._dirs = [Path(d).resolve() for d in scan_dirs]

    def scan(self) -> list[PluginManifest]:
        manifests: list[PluginManifest] = []
        for scan_dir in self._dirs:
            if not scan_dir.exists():
                logger.warning("插件扫描目录不存在: %s", scan_dir)
                continue
            found = self._scan_dir(scan_dir)
            manifests.extend(found)
            logger.info("插件扫描 %s: 发现 %d 个", scan_dir, len(found))
        return manifests

    def _scan_dir(self, scan_dir: Path) -> list[PluginManifest]:
        manifests: list[PluginManifest] = []

        # 1. 根目录 plugin.yaml（单插件包）
        root_yaml = scan_dir / "plugin.yaml"
        if root_yaml.exists():
            m = self._load_yaml(root_yaml, scan_dir)
            if m:
                manifests.append(m)
            return manifests

        # 2. 扫描当前目录下所有 *.yaml 文件（flat 布局，如 plugins/builtin/*.yaml）
        for yaml_path in sorted(scan_dir.glob("*.yaml")):
            if yaml_path.name.startswith("."):
                continue
            m = self._load_yaml(yaml_path, scan_dir)
            if m:
                manifests.append(m)

        # 3. 扫描子目录（嵌套布局）
        for entry in sorted(scan_dir.iterdir()):
            if not entry.is_dir() or entry.name.startswith("_") or entry.name.startswith("."):
                continue
            yaml_path = entry / "plugin.yaml"
            if yaml_path.exists():
                m = self._load_yaml(yaml_path, entry)
                if m and m.name not in [x.name for x in manifests]:
                    manifests.append(m)
        return manifests

    def _load_yaml(self, yaml_path: Path, plugin_dir: Path) -> Optional[PluginManifest]:
        try:
            with open(yaml_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception as e:
            logger.warning("无法解析 %s: %s", yaml_path, e)
            return None

        if not data or not isinstance(data, dict):
            return None

        try:
            class_path = data.get("class", "")
            if ":" in class_path:
                module, class_name = class_path.split(":", 1)
            else:
                # 默认为 plugins.builtin.<name>.<class>
                module = f"plugins.builtin.{data.get('name', '')}"
                class_name = class_path

            hooks_data = data.get("hooks", []) or []
            hooks = [
                HookDef(hook=h["hook"], priority=h.get("priority", 50))
                for h in hooks_data
            ]

            cond_data = data.get("condition")
            condition = None
            if cond_data:
                condition = ConditionDef(
                    dependency_exists=cond_data.get("dependency_exists"),
                    dependency_missing=cond_data.get("dependency_missing"),
                )

            return PluginManifest(
                name=data.get("name", ""),
                description=data.get("description", ""),
                enabled=data.get("enabled", True),
                module=module,
                class_name=class_name,
                hooks=hooks,
                dependencies=data.get("dependencies", {}) or {},
                condition=condition,
                yaml_path=str(yaml_path),
            )
        except Exception as e:
            logger.warning("解析插件清单失败 %s: %s", yaml_path, e)
            return None

    def instantiate(self, manifest: PluginManifest) -> Optional[Plugin]:
        """动态导入并实例化插件，自动注入依赖。"""
        try:
            mod = importlib.import_module(manifest.module)
            cls = getattr(mod, manifest.class_name)

            # 检查是否为合法的 Plugin 子类
            if not issubclass(cls, (Plugin, AsyncPlugin)):
                logger.warning("%s 不是 Plugin/AsyncPlugin 子类，跳过", manifest.full_class_path)
                return None

            # 从 DI 容器解析依赖
            kwargs = PluginDIContainer.resolve(cls)
            instance = cls(**kwargs)
            logger.info("插件已加载: %s (hooks=%s, priority=%s)",
                        manifest.name,
                        [h.hook for h in manifest.hooks],
                        [h.priority for h in manifest.hooks])
            return instance
        except Exception as e:
            logger.error("加载插件 %s 失败: %s", manifest.full_class_path, e, exc_info=True)
            return None
