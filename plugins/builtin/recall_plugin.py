# plugins/builtin/recall_plugin.py
# 动态记忆召回插件 — POST_PROCESS (priority=33, before AgentPlugin)
# 解析 <recall> 标签，调用 MemoryRecallEngine 检索/还原记忆

from __future__ import annotations

import json
import logging
import re

from plugins.base import Plugin, HookPoint, PluginContext

logger = logging.getLogger("RecallPlugin")

_RECALL_RE = re.compile(r"<recall>\s*(.*?)\s*</recall>", re.DOTALL)


class RecallPlugin(Plugin):
    """
    动态记忆召回插件。

    POST_PROCESS 阶段 (priority=33，在 AgentPlugin (35) 之前):
    - 解析 AI 回复中的 <recall> 标签
    - 调用 MemoryRecallEngine 执行检索或细节还原
    - 将结果注入 ctx.reply，移除原始 <recall> 标签

    三种操作模式:
      关键词检索: <recall>{"keywords": [...], "count": 5}</recall>
      细节还原:   <recall>{"detail": [1, 2, 3]}</recall>
      混合模式:   <recall>{"keywords": [...], "detail": true}</recall>

    依赖: ctx.recall_engine (MemoryRecallEngine 实例)
    """

    name = "recall"
    description = "动态记忆召回 — 解析 <recall> 标签，检索/还原历史记忆"
    hooks = [HookPoint.POST_PROCESS]
    priority = 33

    def __init__(self, recall_engine=None):
        self._recall_engine = recall_engine

    def on_load(self) -> None:
        if self._recall_engine is None:
            logger.warning("recall_engine 未注入，RecallPlugin 将跳过记忆召回操作")

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if hook != HookPoint.POST_PROCESS:
            return ctx

        # 优先使用 ctx 上的 recall_engine，回退到构造时注入的
        engine = self._recall_engine
        if engine is None:
            return ctx

        original = ctx.original_reply
        if not original:
            return ctx

        recall_matches = list(_RECALL_RE.finditer(original))
        if not recall_matches:
            return ctx

        recall_results: list[str] = []

        for match in recall_matches:
            raw_json = match.group(1).strip()
            try:
                payload = json.loads(raw_json)
            except json.JSONDecodeError as e:
                logger.error("解析 <recall> JSON 失败: %s", e)
                recall_results.append(f"[记忆召回失败] JSON 解析错误: {e}")
                continue

            if not isinstance(payload, dict):
                continue

            result = engine.handle_recall(ctx.user_id, ctx.chat_id, payload)
            if result:
                recall_results.append(result)

        # 移除所有 <recall> 标签，追加召回结果
        cleaned = _RECALL_RE.sub("", ctx.reply if ctx.reply else original).strip()

        if recall_results:
            cleaned += "\n\n" + "\n\n".join(recall_results)
            ctx.extra["recall_executed"] = True
            logger.info("记忆召回执行完成: %d 个 <recall> 标签处理完毕", len(recall_matches))

        ctx.reply = cleaned
        return ctx
