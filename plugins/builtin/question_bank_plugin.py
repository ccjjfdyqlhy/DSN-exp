# plugins/builtin/question_bank_plugin.py
# 题库系统管线插件

from __future__ import annotations

import json
import logging
import re

from plugins.base import Plugin, HookPoint, PluginContext

logger = logging.getLogger("QuestionBankPlugin")


class QuestionBankPlugin(Plugin):
    name = "question_bank"
    description = "题库管理 - 题目入库/查询/组卷/错题分析"
    hooks = [HookPoint.PRE_PROCESS, HookPoint.POST_PROCESS]
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
        elif hook == HookPoint.POST_PROCESS:
            return self._post_process(ctx)
        return ctx

    def _pre_process(self, ctx: PluginContext) -> PluginContext:
        # 注入用户错题统计和今日推荐
        if self._store:
            try:
                error_count = self._store.get_total_errors(ctx.user_id)
            except Exception:
                error_count = 0

            if error_count > 0:
                context_note = f"\n[题库系统] 你有 {error_count} 道错题待复习。"
                ctx.system_prompt += context_note

        scan_image = ctx.extra.get("scan_image")
        if scan_image and self._scanner:
            ctx.extra["_scan_pending"] = scan_image

        return ctx

    def _post_process(self, ctx: PluginContext) -> PluginContext:
        reply = ctx.original_reply

        # 处理扫描入题
        if ctx.extra.get("_scan_pending") and self._scanner:
            try:
                scan_result = self._scanner.process_scan(
                    ctx.extra["_scan_pending"], ctx.user_id
                )
                ctx.extra["scan_result"] = scan_result
            except Exception as e:
                logger.error("扫描处理失败: %s", e)

        # 解析 <qb_query> 标签
        query_matches = re.findall(r'<qb_query>(.*?)</qb_query>', reply, re.DOTALL)
        for match in query_matches:
            try:
                params = json.loads(match.strip())
                results = self._store.search_questions(**params)
                ctx.extra["qb_query_results"] = results
            except Exception as e:
                logger.error("题目查询失败: %s", e)

        # 解析 <qb_store> 标签
        store_matches = re.findall(r'<qb_store>(.*?)</qb_store>', reply, re.DOTALL)
        for match in store_matches:
            try:
                data = json.loads(match.strip())
                # 如果是数组，逐条入库
                if isinstance(data, list):
                    for item in data:
                        self._store.create_question(item)
                else:
                    self._store.create_question(data)
                logger.info("题目入库完成")
            except Exception as e:
                logger.error("题目入库失败: %s", e)

        # 解析 <qb_compose> 标签
        compose_matches = re.findall(r'<qb_compose>(.*?)</qb_compose>', reply, re.DOTALL)
        for match in compose_matches:
            try:
                from question_bank.composer import ComposeParams
                params = json.loads(match.strip())
                compose_params = ComposeParams(
                    subject=params.get("subject", "math"),
                    count=params.get("count", 10),
                    difficulty_dist=params.get("difficulty_dist"),
                    type_dist=params.get("type_dist"),
                    knowledge_points=params.get("knowledge_points"),
                )
                result = self._composer.compose(compose_params)
                ctx.extra["qb_compose_result"] = result
            except Exception as e:
                logger.error("组卷失败: %s", e)

        # 解析 <qb_analyze> 标签
        analyze_matches = re.findall(r'<qb_analyze>(.*?)</qb_analyze>', reply, re.DOTALL)
        for match in analyze_matches:
            try:
                params = json.loads(match.strip())
                analysis = self._analyzer.analyze_error(
                    ctx.user_id,
                    params.get("question_id", 0),
                    params.get("user_answer", ""),
                )
                ctx.extra["qb_analysis_result"] = analysis
            except Exception as e:
                logger.error("错题分析失败: %s", e)

        # 清理标签
        reply = re.sub(r'<qb_query>.*?</qb_query>', '', reply, flags=re.DOTALL)
        reply = re.sub(r'<qb_store>.*?</qb_store>', '', reply, flags=re.DOTALL)
        reply = re.sub(r'<qb_compose>.*?</qb_compose>', '', reply, flags=re.DOTALL)
        reply = re.sub(r'<qb_analyze>.*?</qb_analyze>', '', reply, flags=re.DOTALL)
        ctx.original_reply = reply
        ctx.reply = reply

        return ctx
