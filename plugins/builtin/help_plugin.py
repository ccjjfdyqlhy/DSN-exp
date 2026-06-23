# plugins/builtin/help_plugin.py
# HelpPlugin — <help> 标签检测与检索插件

from __future__ import annotations

import re
import logging
from typing import Optional

from plugins.base import Plugin, HookPoint, PluginContext

logger = logging.getLogger("HelpPlugin")

_HELP_RE = re.compile(r"<help>(.*?)</help>", re.DOTALL | re.IGNORECASE)


class HelpPlugin(Plugin):
    """
    <help> 标签检测与检索插件。
    
    当 AI 输出 <help>query</help> 标签时：
    1. 检测标签并提取查询内容
    2. 从 prompt_cache 表检索相关提示词
    3. 将检索结果注入到回复中（作为系统消息）
    4. 重新触发 LLM 调用，让 AI 基于检索结果继续
    
    POST_PROCESS (priority=5): 在任务解析之前处理
    """

    name = "help"
    description = "<help> 标签检测与检索"
    hooks = [HookPoint.POST_PROCESS]
    priority = 5  # 在任务解析之前处理

    def __init__(self, prompt_cache=None):
        self._prompt_cache = prompt_cache

    def on_load(self) -> None:
        if self._prompt_cache is None:
            logger.warning("prompt_cache 未注入，HelpPlugin 将跳过 <help> 检索")

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if self._prompt_cache is None or hook != HookPoint.POST_PROCESS:
            return ctx

        text = ctx.original_reply
        if not text:
            return ctx

        results: list[dict] = []

        for match in _HELP_RE.finditer(text):
            query = match.group(1).strip()
            if not query:
                continue

            logger.info("检测到 <help> 标签，查询: %s", query[:50])

            search_results = self._prompt_cache.search(
                uid=ctx.user_id,
                chat_id=ctx.chat_id,
                query=query,
                limit=3,
            )

            if search_results:
                summary = self._format_summary(search_results)
                results.append({
                    "tag": "<help>", "success": True,
                    "summary": f"检索「{query[:30]}」→ {summary}",
                    "data": search_results,
                    "query": query,
                })
                logger.info("检索到 %d 条相关提示词", len(search_results))
            else:
                results.append({
                    "tag": "<help>", "success": True,
                    "summary": f"检索「{query[:30]}」→ 无结果",
                    "data": [],
                    "query": query,
                })

        ctx.reply = _HELP_RE.sub("", ctx.reply).strip()

        if results:
            ctx.extra.setdefault("_tag_results", []).extend(results)

        return ctx

    def _format_summary(self, results: list[dict]) -> str:
        items = []
        for r in results:
            source = r.get("source_file", "").split("/")[-1]
            content = r.get("content", "")[:100]
            items.append(f"{source}: {content}")
        return "; ".join(items[:3])
