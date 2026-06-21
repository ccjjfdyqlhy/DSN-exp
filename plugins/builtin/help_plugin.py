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
        if self._prompt_cache is None:
            return ctx

        # 检测 <help> 标签
        text = ctx.reply if ctx.reply else ctx.original_reply
        match = _HELP_RE.search(text)
        if not match:
            return ctx

        query = match.group(1).strip()
        if not query:
            logger.info("<help> 标签为空，跳过检索")
            return ctx

        logger.info("检测到 <help> 标签，查询: %s", query[:50])

        # 从 prompt_cache 检索
        results = self._prompt_cache.search(
            uid=ctx.user_id,
            chat_id=ctx.chat_id,
            query=query,
            limit=3,
        )

        if not results:
            logger.info("未找到相关提示词")
            # 移除 <help> 标签
            ctx.reply = _HELP_RE.sub("", text).strip()
            if not ctx.reply:
                ctx.reply = "…"
            return ctx

        # 格式化检索结果
        help_content = self._format_results(results)
        logger.info("检索到 %d 条相关提示词", len(results))

        # 将检索结果注入到回复中
        # 移除 <help> 标签，并在回复前添加检索结果
        clean_reply = _HELP_RE.sub("", text).strip()
        if not clean_reply:
            clean_reply = "…"

        ctx.reply = f"{help_content}\n\n{clean_reply}"
        
        # 标记需要重新处理
        ctx.extra["_help_retrieved"] = True
        ctx.extra["_help_content"] = help_content

        return ctx

    def _format_results(self, results: list[dict]) -> str:
        """格式化检索结果"""
        lines = ["【相关提示词】"]
        for i, r in enumerate(results, 1):
            category = r.get("category", "unknown")
            source = r.get("source_file", "").split("/")[-1]  # 只取文件名
            content = r.get("content", "")
            similarity = r.get("similarity", 0)
            
            # 截断过长的内容
            if len(content) > 500:
                content = content[:500] + "..."
            
            lines.append(f"\n[{i}] 类别: {category} | 来源: {source} | 相似度: {similarity:.2f}")
            lines.append(content)
        
        return "\n".join(lines)
