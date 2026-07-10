"""依赖注入容器 — 按参数名自动匹配全局组件到插件构造函数。"""

from __future__ import annotations

import inspect
import logging
from typing import Any

logger = logging.getLogger("PluginDI")


class PluginDIContainer:
    _instances: dict[str, Any] = {}

    @classmethod
    def register(cls, name: str, instance: Any) -> None:
        cls._instances[name] = instance
        logger.debug("DI 注册: %s = %s", name, type(instance).__name__ if instance else None)

    @classmethod
    def register_all(cls, **kwargs) -> None:
        """批量注册: PluginDIContainer.register_all(db=db, task_manager=tm, ...)"""
        for name, instance in kwargs.items():
            cls.register(name, instance)

    @classmethod
    def get(cls, name: str, default=None) -> Any:
        return cls._instances.get(name, default)

    @classmethod
    def has(cls, name: str) -> bool:
        return name in cls._instances

    @classmethod
    def resolve(cls, plugin_class: type) -> dict[str, Any]:
        """根据插件 __init__ 签名自动匹配已注册的依赖。

        匹配规则:
          - 参数名在容器中 → 注入
          - 参数不在容器中但有默认值 → 跳过（使用默认值）
          - 参数不在容器中且无默认值 → 报错
        """
        sig = inspect.signature(plugin_class.__init__)
        kwargs: dict[str, Any] = {}
        missing: list[str] = []

        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue
            if param_name in cls._instances:
                kwargs[param_name] = cls._instances[param_name]
            elif param.default is not inspect.Parameter.empty:
                # 有默认值的可选依赖，跳过
                pass
            else:
                missing.append(param_name)

        if missing:
            raise RuntimeError(
                f"插件 {plugin_class.__name__} 缺少必要依赖: {', '.join(missing)}。"
                f"可用依赖: {', '.join(cls._instances.keys())}"
            )
        return kwargs

    @classmethod
    def clear(cls) -> None:
        cls._instances.clear()
