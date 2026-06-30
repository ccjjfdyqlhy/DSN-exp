# plugins/builtin/question_bank_plugin.py
# 题库系统管线插件 — 仅负责上下文注入，工具执行已迁移至 SkillRegistry

from __future__ import annotations

import logging

from plugins.base import Plugin, HookPoint, PluginContext

logger = logging.getLogger("QuestionBankPlugin")


class QuestionBankPlugin(Plugin):
    name = "question_bank"
    description = "题库管理 - 上下文注入"
    hooks = [HookPoint.PRE_PROCESS]
    priority = 20

    def __init__(self, question_store=None, models_plugin=None,
                 exam_composer=None, error_analyzer=None, scanner_pipeline=None):
        self._store = question_store
        self._models = models_plugin
        self._composer = exam_composer
        self._analyzer = error_analyzer
        self._scanner = scanner_pipeline

    def on_load(self) -> None:
        if self._store is None:
            logger.warning("question_store 未注入")
        if self._models is None:
            logger.warning("models_plugin 未注入")

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if hook == HookPoint.PRE_PROCESS:
            return self._pre_process(ctx)
        return ctx

    def _pre_process(self, ctx: PluginContext) -> PluginContext:
        if self._store:
            try:
                error_count = self._store.get_total_errors(ctx.user_id)
            except Exception:
                error_count = 0

            if error_count > 0:
                context_note = (
                    f"\n[题库系统] 你有 {error_count} 道错题待复习。"
                )
                ctx.system_prompt += context_note

        scan_image = ctx.extra.get("scan_image")
        if scan_image and self._scanner:
            ctx.extra["_scan_pending"] = scan_image

        return ctx
