# plugins/builtin/personality_plugin.py
# 人格系统 v2 插件 — POST_PROCESS 钩子，每次交互后更新情绪/亲和力/习性

from __future__ import annotations

import logging

from apps.dsn.plugins.base import Plugin, HookPoint, PluginContext

logger = logging.getLogger("PersonalityPlugin")


class PersonalityPlugin(Plugin):
    """
    在 POST_PROCESS 阶段调用 PersonalitySystemV2.on_interaction()，
    更新当前用户的情绪、亲和力、习性状态。

    依赖: personality_v2 (PersonalitySystemV2 实例)
    """

    name = "personality"
    description = "人格系统 v2 — 交互后情绪/亲和力/习性更新"
    hooks = [HookPoint.POST_PROCESS]
    priority = 25

    def __init__(self, personality_v2=None):
        self._pv2 = personality_v2

    def on_load(self) -> None:
        if self._pv2 is None:
            logger.warning("personality_v2 未注入，PersonalityPlugin 将跳过所有操作")

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if hook != HookPoint.POST_PROCESS:
            return ctx
        if self._pv2 is None:
            return ctx

        try:
            sentiment = ctx.extra.get("sentiment", True)
            self._pv2.on_interaction(
                ctx.user_id, ctx.message,
                is_positive=sentiment,
            )
            logger.debug("人格v2交互更新: uid=%d message_len=%d", ctx.user_id, len(ctx.message))
        except Exception:
            logger.exception("PersonalityPlugin 交互更新失败")

        return ctx
