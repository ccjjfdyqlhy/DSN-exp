# harness/pipeline/manager.py
# 通用 PluginManager — 注册 / 启停 / 按优先级调度。

from __future__ import annotations

import asyncio
import bisect
import logging
import time
from typing import Union

from .base import HookPoint, Context, Plugin, AsyncPlugin

logger = logging.getLogger("harness.plugin")

_PluginT = Union[Plugin, AsyncPlugin]


class PluginManager:
    """管理插件生命周期，并按 HookPoint / priority 调度。"""

    def __init__(self):
        self._plugins: dict[str, _PluginT] = {}
        self._enabled: dict[str, bool] = {}
        self._hook_index: dict[HookPoint, list[_PluginT]] = {
            h: [] for h in HookPoint
        }

    # ── 注册 ──

    def register(self, plugin: _PluginT) -> _PluginT:
        if plugin.name in self._plugins:
            logger.warning("插件 %s 已注册，将被覆盖", plugin.name)
            self._unindex(plugin.name)
        self._plugins[plugin.name] = plugin
        self._enabled[plugin.name] = True
        self._index(plugin)
        logger.debug("已注册插件: %s (priority=%d)", plugin.name, plugin.priority)
        return plugin

    def unregister(self, name: str) -> bool:
        if name not in self._plugins:
            return False
        self._unindex(name)
        del self._plugins[name]
        self._enabled.pop(name, None)
        return True

    # ── 启停 ──

    def enable(self, name: str) -> bool:
        if name not in self._plugins:
            return False
        self._enabled[name] = True
        return True

    def disable(self, name: str) -> bool:
        if name not in self._plugins:
            return False
        self._enabled[name] = False
        return True

    def is_enabled(self, name: str) -> bool:
        return self._enabled.get(name, False)

    # ── 查询 ──

    def get(self, name: str) -> _PluginT | None:
        return self._plugins.get(name)

    def list_plugins(self) -> list[dict]:
        return [
            {
                "name": p.name,
                "description": p.description,
                "version": p.version,
                "hooks": [h.value for h in p.hooks],
                "priority": p.priority,
                "enabled": self._enabled.get(p.name, False),
                "is_async": isinstance(p, AsyncPlugin),
            }
            for p in self._plugins.values()
        ]

    def get_hooks_for(self, hook: HookPoint) -> list[_PluginT]:
        return list(self._hook_index[hook])

    # ── 调度 ──

    async def _call_plugin(self, plugin: _PluginT, hook: HookPoint, ctx: Context) -> Context:
        if isinstance(plugin, AsyncPlugin):
            return await plugin.on_hook(hook, ctx)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, plugin.on_hook, hook, ctx)

    async def _dispatch_filtered(self, hook: HookPoint, ctx: Context, predicate) -> Context:
        for plugin in self._hook_index[hook]:
            if not predicate(plugin):
                continue
            if not self._enabled.get(plugin.name, False):
                continue
            t0 = time.perf_counter()
            try:
                ctx = await self._call_plugin(plugin, hook, ctx)
            except Exception:
                logger.exception("插件 %s 在钩子 %s 中抛出异常", plugin.name, hook.value)
                continue
            elapsed = round((time.perf_counter() - t0) * 1000, 1)
            # 与 DSN 引擎语义一致：仅当调用方已初始化计时键时才记录（管线按需开启计时）
            timings = ctx.extra.get("_plugin_timings")
            if timings is not None:
                timings.setdefault(hook.value, []).append((plugin.name, elapsed))
            if ctx.filtered:
                logger.debug("管线在钩子 %s 被插件 %s 短路", hook.value, plugin.name)
                break
        return ctx

    async def dispatch(self, hook: HookPoint, ctx: Context) -> Context:
        return await self._dispatch_filtered(hook, ctx, lambda _: True)

    async def dispatch_except(self, hook: HookPoint, ctx: Context, skip: set[str]) -> Context:
        return await self._dispatch_filtered(hook, ctx, lambda p: p.name not in skip)

    async def dispatch_only(self, hook: HookPoint, ctx: Context, names: set[str]) -> Context:
        return await self._dispatch_filtered(hook, ctx, lambda p: p.name in names)

    # ── 内部 ──

    def _index(self, plugin: _PluginT) -> None:
        # 按 priority 升序插入：值越小越先执行（与 DSN 引擎调度约定一致；
        # dsn 插件如 help=5 在 task=40 前、todo=33 在 memory=30 后）
        for hook in plugin.hooks:
            bisect.insort(self._hook_index[hook], plugin, key=lambda p: p.priority)

    def _unindex(self, name: str) -> None:
        for hook in HookPoint:
            self._hook_index[hook] = [p for p in self._hook_index[hook] if p.name != name]
