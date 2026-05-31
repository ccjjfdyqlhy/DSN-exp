# plugins/builtin/impression_plugin.py
# ImpressionPlugin — 用户印象注入 / 对话印象提取

from __future__ import annotations

import logging

from plugins.base import Plugin, HookPoint, PluginContext

logger = logging.getLogger("ImpressionPlugin")


class ImpressionPlugin(Plugin):
    """
    在 PRE_PROCESS 阶段注入用户印象到 system prompt，
    在 POST_PROCESS 阶段从对话中提取新印象。

    依赖: impression_manager (ImpressionManager 实例)
    """

    name = "impression"
    description = "用户印象系统 — 印象注入 + 对话提取"
    hooks = [HookPoint.PRE_PROCESS, HookPoint.POST_PROCESS]
    priority = 22

    def __init__(self, impression_manager=None):
        self._im = impression_manager

    def on_load(self) -> None:
        if self._im is None:
            logger.warning("impression_manager 未注入，ImpressionPlugin 将跳过所有操作")

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if self._im is None:
            return ctx
        if hook == HookPoint.PRE_PROCESS:
            return self._on_pre_process(ctx)
        if hook == HookPoint.POST_PROCESS:
            return self._on_post_process(ctx)
        return ctx

    def _on_pre_process(self, ctx: PluginContext) -> PluginContext:
        if ctx.system_prompt:
            imp_ctx = self._im.prompt_context(ctx.user_id, top_n=8)
            if imp_ctx:
                ctx.system_prompt += "\n\n" + imp_ctx
                ctx.extra["impression_count"] = self._im.count(ctx.user_id)
        return ctx

    def _on_post_process(self, ctx: PluginContext) -> PluginContext:
        reply = ctx.original_reply or ctx.reply or ""
        if not reply:
            return ctx

        impressions = self._parse_impressions_from_reply(reply)
        for imp in impressions:
            self._im.add(
                ctx.user_id, imp["category"], imp["content"],
                imp.get("confidence", 0.6), "inferred",
            )

        imp_count = self._im.count(ctx.user_id)
        affinity_level = ctx.extra.get("affinity_level", 0)
        if self._im.should_propose_ssp(ctx.user_id, affinity_level):
            ctx.extra["suggest_ssp"] = True

        return ctx

    @staticmethod
    def _parse_impressions_from_reply(text: str) -> list[dict]:
        import re
        results = []
        pat = re.compile(
            r"IMPRESSION\s*:\s*(.+?)\s*:\s*(.+?)\s*:\s*(\d+)",
            re.IGNORECASE,
        )
        for match in pat.finditer(text):
            results.append({
                "category": match.group(1).strip(),
                "content": match.group(2).strip(),
                "confidence": int(match.group(3)) / 100.0,
            })
        return results
