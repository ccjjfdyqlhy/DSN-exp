# plugins/builtin/knowledge_graph_plugin.py
# 知识图谱管线插件 — 仅负责上下文注入，工具执行由 SkillRegistry 统一处理

from __future__ import annotations

import logging

from plugins.base import Plugin, HookPoint, PluginContext

logger = logging.getLogger("KnowledgeGraphPlugin")


class KnowledgeGraphPlugin(Plugin):
    name = "knowledge_graph"
    description = "知识图谱 - 上下文注入（工具执行已迁移至 SkillRegistry）"
    hooks = [HookPoint.PRE_PROCESS]
    priority = 22

    def __init__(self, graph_store=None, graph_engine=None,
                 knowledge_matcher=None, question_store=None):
        self._store = graph_store
        self._engine = graph_engine
        self._matcher = knowledge_matcher
        self._question_store = question_store

    def on_load(self) -> None:
        if self._store is None:
            logger.warning("GraphStore 未注入")
        if self._engine is None:
            logger.warning("GraphEngine 未注入")

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if hook == HookPoint.PRE_PROCESS:
            return self._pre_process(ctx)
        return ctx

    def _pre_process(self, ctx: PluginContext) -> PluginContext:
        if self._engine:
            try:
                due = self._engine.recommend_review(ctx.user_id, limit=3)
                if due:
                    names = [
                        d.get("kp_name", d.get("kp_code", ""))
                        for d in due
                    ]
                    ctx.system_prompt += (
                        f"\n[知识图谱] 今日待复习知识点: {'、'.join(names)}。"
                    )
            except Exception as e:
                logger.warning("复习推荐失败: %s", e)

        return ctx
