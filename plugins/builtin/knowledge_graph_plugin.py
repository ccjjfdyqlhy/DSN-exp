# plugins/builtin/knowledge_graph_plugin.py
# 知识图谱管线插件

from __future__ import annotations

import json
import logging
import re

from plugins.base import Plugin, HookPoint, PluginContext

logger = logging.getLogger("KnowledgeGraphPlugin")


class KnowledgeGraphPlugin(Plugin):
    name = "knowledge_graph"
    description = "知识图谱 - 知识点追踪、薄弱路径分析、间隔复习"
    hooks = [HookPoint.PRE_PROCESS, HookPoint.POST_PROCESS]
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
        elif hook == HookPoint.POST_PROCESS:
            return self._post_process(ctx)
        return ctx

    def _pre_process(self, ctx: PluginContext) -> PluginContext:
        if self._engine:
            try:
                due = self._engine.recommend_review(ctx.user_id, limit=3)
                if due:
                    names = [d.get("kp_name", d.get("kp_code", "")) for d in due]
                    ctx.system_prompt += f"\n[知识图谱] 今日待复习知识点: {'、'.join(names)}。"
            except Exception as e:
                logger.warning("复习推荐失败: %s", e)

        return ctx

    def _post_process(self, ctx: PluginContext) -> PluginContext:
        reply = ctx.original_reply

        kg_update_matches = re.findall(r'<kg_update>(.*?)</kg_update>', reply, re.DOTALL)
        for match in kg_update_matches:
            try:
                params = json.loads(match.strip())
                self._store.update_user_state(
                    ctx.user_id,
                    params.get("kp_code", ""),
                    params.get("correct", True),
                )
                if params.get("correct", True) and self._engine:
                    self._engine.propagate_mastery(ctx.user_id, params.get("kp_code", ""))
            except Exception as e:
                logger.error("知识状态更新失败: %s", e)

        kg_recommend_matches = re.findall(r'<kg_recommend>(.*?)</kg_recommend>', reply, re.DOTALL)
        for match in kg_recommend_matches:
            try:
                params = json.loads(match.strip())
                kp_code = params.get("kp_code", "")
                if kp_code and self._engine:
                    related = self._engine.find_related(kp_code, depth=params.get("depth", 2))
                    ctx.extra["kg_recommend_result"] = related
                    if self._question_store and related:
                        q_kps = [r["kp_code"] for r in related[:3]]
                        questions = self._question_store.search_questions(
                            knowledge_points=q_kps, limit=5)
                        ctx.extra["kg_recommend_questions"] = questions
            except Exception as e:
                logger.error("关联推荐失败: %s", e)

        kg_build_matches = re.findall(r'<kg_build>(.*?)</kg_build>', reply, re.DOTALL)
        for match in kg_build_matches:
            try:
                from knowledge_graph.builder import KnowledgeGraphBuilder
                params = json.loads(match.strip())
                builder = KnowledgeGraphBuilder(
                    graph_store=self._store,
                    models_plugin=ctx.extra.get("_models_plugin"),
                )
                result = builder.build_from_syllabus(
                    params.get("subject", ""),
                    params.get("content", ""),
                )
                ctx.extra["kg_build_result"] = result
            except Exception as e:
                logger.error("知识图构建失败: %s", e)

        reply = re.sub(r'<kg_update>.*?</kg_update>', '', reply, flags=re.DOTALL)
        reply = re.sub(r'<kg_recommend>.*?</kg_recommend>', '', reply, flags=re.DOTALL)
        reply = re.sub(r'<kg_build>.*?</kg_build>', '', reply, flags=re.DOTALL)
        ctx.original_reply = reply
        ctx.reply = reply

        return ctx
