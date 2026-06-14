# plugins/builtin/personality_v3_plugin.py
# 人格系统 v3 插件 — POST_PROCESS 钩子，每次交互后触发 V3 情绪/亲和力判定

from __future__ import annotations

import logging

from plugins.base import Plugin, HookPoint, PluginContext

logger = logging.getLogger("PersonalityV3Plugin")


class PersonalityV3Plugin(Plugin):
    """
    在 POST_PROCESS 阶段调用 PersonalitySystemV3.analyze_interaction()，
    使用性格判定模型分析用户消息和 AI 回复，更新情绪和亲密度。

    依赖: personality_v3 (PersonalitySystemV3 实例)
    """

    name = "personality_v3"
    description = "人格系统 v3 — 性格模型判定情绪/亲和力变化"
    hooks = [HookPoint.POST_PROCESS]
    priority = 24  # 略早于 v2 的 25

    def __init__(self, personality_v3=None):
        self._pv3 = personality_v3

    def on_load(self) -> None:
        if self._pv3 is None:
            logger.warning("PersonalityV3Plugin: personality_v3 未注入，将跳过所有操作")
        else:
            logger.info("PersonalityV3Plugin: 已加载, enabled=%s", self._pv3.enabled)

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if hook != HookPoint.POST_PROCESS:
            return ctx
        if self._pv3 is None or not self._pv3.enabled:
            logger.debug("PersonalityV3Plugin: 跳过 (pv3=%s)", "absent" if self._pv3 is None else "disabled")
            return ctx

        ai_reply = ctx.reply
        if not ai_reply:
            logger.debug("PersonalityV3Plugin: 跳过 — AI 回复为空")
            return ctx

        try:
            logger.debug("PersonalityV3Plugin: 分析交互 uid=%d msg_len=%d reply_len=%d",
                         ctx.user_id, len(ctx.message), len(ai_reply))
            result = self._pv3.analyze_interaction(
                uid=ctx.user_id,
                user_message=ctx.message,
                ai_reply=ai_reply,
            )
            if result:
                d_joy = result.new_mood.get("joy", 0.5) - result.old_mood.get("joy", 0.5)
                d_aff = result.new_affinity - result.old_affinity
                logger.info("PersonalityV3Plugin: 交互分析完成 uid=%d joy=%+.2f affinity=%+.1f(%s)",
                            ctx.user_id, d_joy, d_aff,
                            result.affinity_reason[:40] if result.affinity_reason else "")
        except Exception:
            logger.exception("PersonalityV3Plugin: 交互分析失败")

        return ctx
