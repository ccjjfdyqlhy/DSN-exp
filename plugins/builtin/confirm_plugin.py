# plugins/builtin/confirm_plugin.py
# （已弃用 — 保留空壳以避免 import 断裂）

from __future__ import annotations

import logging

from plugins.base import Plugin, HookPoint, PluginContext

logger = logging.getLogger("ConfirmPlugin")


class ConfirmPlugin(Plugin):
    name = "confirm"
    description = "（已弃用）"
    hooks = []
    priority = 32

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        return ctx
