# plugins/builtin/memory_plugin.py
# 记忆注入 + 对话保存插件 — PRE_PROCESS + POST_PROCESS
# v3.0 — 适配 MemorySystem

from __future__ import annotations

import logging
from typing import Optional

from apps.dsn.plugins.base import Plugin, HookPoint, PluginContext
from apps.dsn.config import Config

logger = logging.getLogger("MemoryPlugin")

_PERFORMANCE_MODE = getattr(Config, "PERFORMANCE_MODE", "realtime")


class MemoryPlugin(Plugin):
    name = "memory"
    description = "记忆管理 — 上下文组装 + 对话保存与摘要"
    hooks = [HookPoint.PRE_PROCESS, HookPoint.POST_PROCESS]
    priority = 30

    def __init__(self, memory_system=None, db=None):
        self._ms = memory_system
        self._db = db

    def on_load(self) -> None:
        if self._ms is None:
            logger.warning("memory_system 未注入，MemoryPlugin 将跳过所有记忆操作")
        if self._db is None:
            logger.warning("db 未注入，MemoryPlugin 无法访问数据库")

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if hook == HookPoint.PRE_PROCESS:
            return self._on_pre_process(ctx)
        if hook == HookPoint.POST_PROCESS:
            return self._on_post_process(ctx)
        return ctx

    def _on_pre_process(self, ctx: PluginContext) -> PluginContext:
        if self._ms is not None:
            # 话题决策: 归属当前/旧话题或新建, 并计算本轮 round_index 供持久化使用
            # (调试模式不持久化, 跳过话题决策避免产生垃圾话题)
            if (self._db is not None and ctx.chat_id and not ctx.extra.get("_debug_mode")
                    and getattr(Config, "TOPIC_ENABLED", True)):
                try:
                    if ctx.extra.get("round_index") is None:
                        ctx.extra["round_index"] = self._db.get_next_round_index(ctx.chat_id)
                    decision = self._ms._topics.on_new_message(
                        ctx.user_id, ctx.chat_id, ctx.message,
                        round_idx=ctx.extra.get("round_index"),
                    )
                    ctx.extra["topic_id"] = decision.get("topic_id")
                    ctx.extra["topic_decision"] = decision
                except Exception as e:
                    logger.error("话题决策失败: %s", e)

            ctx.full_history = self._ms.assemble_context(
                ctx.user_id, ctx.history,
                cross_user_id=ctx.cross_user_id,
                chat_id=ctx.chat_id,
            )
        else:
            ctx.full_history = list(ctx.history)
        return ctx

    def _on_post_process(self, ctx: PluginContext) -> PluginContext:
        if self._ms is None or self._db is None:
            return ctx
        if ctx.extra.get("_debug_mode"):
            return ctx

        topic_id = ctx.extra.get("topic_id")
        round_index = ctx.extra.get("round_index")
        if round_index is None:
            try:
                round_index = self._db.get_next_round_index(ctx.chat_id)
            except Exception:
                round_index = None

        # 更新话题活动时间与轮次 (无论实时/挂起模式, 防止过期话题被清扫)
        if topic_id and round_index:
            try:
                self._ms._topics.store.touch_topic(topic_id, round_index)
            except Exception as exc:
                logger.error("touch topic 失败: %s", exc)

        # ── fastcache 模式：挂起到 HibernateManager ──
        if _PERFORMANCE_MODE == "fastcache":
            hibernate = ctx.extra.get("_hibernate_manager")
            if hibernate:
                try:
                    hibernate.push("memory_summarize", {
                        "user_id": ctx.user_id,
                        "chat_id": ctx.chat_id,
                        "message": ctx.message,
                        "reply": ctx.original_reply or ctx.reply or "",
                        "round_index": round_index,
                        "topic_id": topic_id,
                    })
                except Exception as e:
                    logger.error("hibernate push 失败: %s", e)
            return ctx

        try:
            self._ms.summarize_turn(
                user_id=ctx.user_id,
                chat_id=ctx.chat_id,
                round_idx=round_index,
                user_msg=ctx.message,
                assistant_reply=ctx.original_reply,
                async_mode=True,
                topic_id=topic_id,
            )
            logger.debug("记忆摘要任务已提交 (round=%s, topic=%s)", round_index, topic_id)
        except Exception as e:
            logger.error("提交记忆摘要失败: %s", e)

        return ctx
