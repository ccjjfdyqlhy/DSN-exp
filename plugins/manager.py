# plugins/manager.py
# 插件管理器 — 注册 / 禁用 / 启用 / 调度

from __future__ import annotations

import asyncio
import logging
from typing import Union

from .base import HookPoint, PluginContext, Plugin, AsyncPlugin

logger = logging.getLogger("PluginManager")

_PluginT = Union[Plugin, AsyncPlugin]


class PluginManager:
    """
    插件管理器。

    职责:
    - 注册 / 注销插件实例
    - 按 HookPoint 索引，按 priority 排序
    - 启用 / 禁用插件（不卸载）
    - dispatch(hook, ctx) 按优先级调度
    """

    def __init__(self):
        self._plugins: dict[str, _PluginT] = {}
        self._enabled: dict[str, bool] = {}
        self._hook_index: dict[HookPoint, list[_PluginT]] = {
            h: [] for h in HookPoint
        }

    # ---- 注册 / 注销 ----

    def register(self, plugin: _PluginT) -> None:
        """
        注册插件实例并索引其钩子。
        若同名插件已注册，弹出警告并用新实例覆盖。
        """
        if plugin.name in self._plugins:
            logger.warning("插件 %s 已注册，将被覆盖", plugin.name)
            self._unindex_hooks(plugin.name)

        self._plugins[plugin.name] = plugin
        self._enabled[plugin.name] = True
        self._index_hooks(plugin)
        logger.info("已注册插件: %s (priority=%d)", plugin.name, plugin.priority)

    def unregister(self, name: str) -> bool:
        """注销插件并从钩子索引中移除"""
        if name not in self._plugins:
            logger.warning("插件 %s 未注册", name)
            return False
        self._unindex_hooks(name)
        del self._plugins[name]
        self._enabled.pop(name, None)
        logger.info("已注销插件: %s", name)
        return True

    # ---- 启用 / 禁用 ----

    def enable(self, name: str) -> bool:
        if name not in self._plugins:
            return False
        self._enabled[name] = True
        logger.info("已启用插件: %s", name)
        return True

    def disable(self, name: str) -> bool:
        if name not in self._plugins:
            return False
        self._enabled[name] = False
        logger.info("已禁用插件: %s", name)
        return True

    def is_enabled(self, name: str) -> bool:
        return self._enabled.get(name, False)

    # ---- 查询 ----

    def get(self, name: str) -> _PluginT | None:
        return self._plugins.get(name)

    def list_plugins(self) -> list[dict]:
        """列出所有插件及状态"""
        result = []
        for name, p in self._plugins.items():
            result.append({
                "name": p.name,
                "description": p.description,
                "version": p.version,
                "hooks": [h.value for h in p.hooks],
                "priority": p.priority,
                "enabled": self._enabled.get(name, False),
                "is_async": isinstance(p, AsyncPlugin),
            })
        return result

    def get_hooks_for(self, hook: HookPoint) -> list[_PluginT]:
        """获取注册到指定钩子的插件列表（含禁用插件）"""
        return list(self._hook_index[hook])

    # ---- 调度 ----

    async def _call_plugin(self, plugin: _PluginT, hook: HookPoint,
                           ctx: PluginContext) -> PluginContext:
        """调用单个插件，返回更新后的 ctx"""
        if isinstance(plugin, AsyncPlugin):
            return await plugin.on_hook(hook, ctx)
        else:
            return await asyncio.get_event_loop().run_in_executor(
                None, plugin.on_hook, hook, ctx
            )

    async def dispatch(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        """
        按优先级依次调用该钩子下所有已启用的插件。
        遇到 ctx.filtered == True 时短路返回。
        """
        for plugin in self._hook_index[hook]:
            if not self._enabled.get(plugin.name, False):
                continue

            try:
                ctx = await self._call_plugin(plugin, hook, ctx)
            except Exception:
                logger.exception("插件 %s 在钩子 %s 中抛出异常", plugin.name, hook.value)
                continue

            if ctx.filtered:
                logger.debug("管道在钩子 %s 被插件 %s 短路", hook.value, plugin.name)
                break

        return ctx

    async def dispatch_except(self, hook: HookPoint, ctx: PluginContext,
                              skip_names: set[str]) -> PluginContext:
        """
        按优先级调度该钩子下所有已启用的插件，跳过指定名称的插件。
        用于并行分叉场景（如跳过 VisionPlugin，与其他插件并行运行）。
        """
        for plugin in self._hook_index[hook]:
            if plugin.name in skip_names:
                continue
            if not self._enabled.get(plugin.name, False):
                continue

            try:
                ctx = await self._call_plugin(plugin, hook, ctx)
            except Exception:
                logger.exception("插件 %s 在钩子 %s 中抛出异常", plugin.name, hook.value)
                continue

            if ctx.filtered:
                logger.debug("管道在钩子 %s 被插件 %s 短路", hook.value, plugin.name)
                break

        return ctx

    async def dispatch_only(self, hook: HookPoint, ctx: PluginContext,
                            names: set[str]) -> PluginContext:
        """
        只调度指定名称的插件（按优先级顺序）。
        用于并行分叉场景（如单独运行 VisionPlugin）。
        """
        for plugin in self._hook_index[hook]:
            if plugin.name not in names:
                continue
            if not self._enabled.get(plugin.name, False):
                continue

            try:
                ctx = await self._call_plugin(plugin, hook, ctx)
            except Exception:
                logger.exception("插件 %s 在钩子 %s 中抛出异常", plugin.name, hook.value)
                continue

            if ctx.filtered:
                logger.debug("管道在钩子 %s 被插件 %s 短路", hook.value, plugin.name)
                break

        return ctx

    # ---- 内部 ----

    def _index_hooks(self, plugin: _PluginT) -> None:
        for hook in plugin.hooks:
            self._hook_index[hook].append(plugin)
            self._hook_index[hook].sort(key=lambda p: p.priority)

    def _unindex_hooks(self, name: str) -> None:
        for hook in HookPoint:
            self._hook_index[hook] = [
                p for p in self._hook_index[hook] if p.name != name
            ]
