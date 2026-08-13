# plugins/builtin/personality_v3_plugin.py
# 人格系统 v3 插件 — POST_PROCESS 钩子，每次交互后触发 V3 情绪/亲和力判定
# UPD: 判定改为后台线程 fire-and-forget，不阻塞主管道返回 text_ready 和 TTS

from __future__ import annotations

import logging
import threading

from apps.dsn.plugins.base import Plugin, HookPoint, PluginContext
from apps.dsn.config import Config

logger = logging.getLogger("PersonalityV3Plugin")

_PERFORMANCE_MODE = getattr(Config, "PERFORMANCE_MODE", "realtime")


def _format_recent_history(history: list[dict], current_msg: str, limit: int = 8) -> str:
    """将对话历史格式化为可读文本，供判定模型理解上下文。"""
    if not history:
        return ""
    recent = history[-limit * 2:] if len(history) > limit * 2 else history
    lines = []
    for msg in recent:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "user":
            label = "用户"
        elif role == "assistant":
            label = "AI"
        else:
            continue
        truncated = content[:300] if len(content) > 300 else content
        lines.append(f"{label}: {truncated}")
    return "\n".join(lines)


class PersonalityV3Plugin(Plugin):
    """
    在 POST_PROCESS 阶段调用 PersonalitySystemV3.analyze_interaction()，
    使用性格判定模型分析用户消息和 AI 回复，更新情绪和亲密度。

    判定在后台 daemon 线程中运行，不阻塞主管道的响应延迟。

    依赖: personality_v3 (PersonalitySystemV3 实例)
    """

    name = "personality_v3"
    description = "人格系统 v3 — 性格模型判定情绪/亲和力变化 (异步)"
    hooks = [HookPoint.POST_PROCESS]
    priority = 24  # 略早于 v2 的 25

    def __init__(self, personality_v3=None):
        self._pv3 = personality_v3

    def on_load(self) -> None:
        if self._pv3 is None:
            logger.warning("PersonalityV3Plugin: personality_v3 未注入，将跳过所有操作")
        else:
            logger.info("PersonalityV3Plugin: 已加载（异步判定模式）, enabled=%s", self._pv3.enabled)

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if hook != HookPoint.POST_PROCESS:
            return ctx
        if self._pv3 is None or not self._pv3.enabled:
            logger.debug("PersonalityV3Plugin: 跳过 (pv3=%s)",
                         "absent" if self._pv3 is None else "disabled")
            return ctx

        ai_reply = ctx.reply
        if not ai_reply:
            logger.debug("PersonalityV3Plugin: 跳过 — AI 回复为空")
            return ctx

        user_message = ctx.message
        user_id = ctx.user_id
        conversation_history = _format_recent_history(ctx.history, user_message, limit=8)

        # ── fastcache 模式：挂起到 HibernateManager ──
        if _PERFORMANCE_MODE == "fastcache":
            hibernate = ctx.extra.get("_hibernate_manager")
            if hibernate:
                hibernate.push("personality_analysis", {
                    "user_id": user_id,
                    "message": user_message,
                    "reply": ai_reply,
                    "history": conversation_history,
                })
            return ctx

        def _run():
            try:
                logger.debug("PersonalityV3Plugin: [后台] 分析交互 uid=%d msglen=%d replylen=%d",
                             user_id, len(user_message), len(ai_reply))
                result = self._pv3.analyze_interaction(
                    uid=user_id,
                    user_message=user_message,
                    ai_reply=ai_reply,
                    conversation_history=conversation_history,
                )
                if result:
                    d_joy = result.new_mood.get("joy", 0.5) - result.old_mood.get("joy", 0.5)
                    d_aff = result.new_affinity - result.old_affinity
                    logger.info("PersonalityV3Plugin: [后台] 交互分析完成 uid=%d joy=%+.2f affinity=%+.1f(%s)",
                                user_id, d_joy, d_aff,
                                result.affinity_reason[:40] if result.affinity_reason else "")
            except Exception:
                logger.exception("PersonalityV3Plugin: [后台] 交互分析失败")

        t = threading.Thread(target=_run, daemon=True, name="personality-v3-judge")
        t.start()

        return ctx
