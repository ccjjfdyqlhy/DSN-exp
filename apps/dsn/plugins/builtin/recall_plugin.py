# plugins/builtin/recall_plugin.py
# 动态记忆召回插件 — POST_PROCESS (priority=33)
# 解析 <recall>/<memo> 标签，调用 MemorySystem 处理
# v4.0 — 统一写入 _tag_results 供引擎层 agent 循环消费

from __future__ import annotations

import json
import logging
import re

from harness.pipeline import Plugin, HookPoint, Context as PluginContext

logger = logging.getLogger("RecallPlugin")

_RECALL_RE = re.compile(r"<recall>\s*(.*?)\s*</recall>", re.DOTALL)
_MEMO_RE = re.compile(r"<memo>(.*?)</memo>", re.DOTALL)


class RecallPlugin(Plugin):
    name = "recall"
    description = "动态记忆召回 — 解析 <recall>/<memo> 标签"
    hooks = [HookPoint.POST_PROCESS]
    priority = 33

    def __init__(self, memory_system=None):
        self._ms = memory_system

    def on_load(self) -> None:
        if self._ms is None:
            logger.warning("memory_system 未注入，RecallPlugin 将跳过所有操作")

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if hook != HookPoint.POST_PROCESS or self._ms is None:
            return ctx

        text = ctx.original_reply
        if not text:
            return ctx

        results: list[dict] = []

        # 先处理 <memo>：直接调用写 DB
        memo_count = 0
        for match in _MEMO_RE.finditer(text):
            content = match.group(1).strip()
            if content:
                self._ms.add_memo(ctx.user_id, ctx.chat_id, content)
                memo_count += 1
        if memo_count:
            results.append({
                "tag": "<memo>", "success": True,
                "summary": f"已保存 {memo_count} 条事实记忆",
            })

        # 再处理 <recall>：调用 MemorySystem 内部逻辑
        for match in _RECALL_RE.finditer(text):
            try:
                payload = json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                results.append({
                    "tag": "<recall>", "success": False,
                    "summary": "JSON 解析失败",
                })
                continue

            if isinstance(payload, dict):
                try:
                    r = self._ms._handle_recall(ctx.user_id, ctx.chat_id, payload)
                    if r:
                        results.append({
                            "tag": "<recall>", "success": True,
                            "summary": f"记忆召回: {r[:200]}",
                            "data": r,
                        })
                    else:
                        results.append({
                            "tag": "<recall>", "success": True,
                            "summary": "记忆召回: 无匹配结果",
                        })
                except Exception as e:
                    logger.error("<recall> 执行失败: %s", e)
                    results.append({
                        "tag": "<recall>", "success": False,
                        "summary": f"召回失败: {e}",
                        "error": str(e),
                    })

        # 清理标签
        ctx.reply = _MEMO_RE.sub("", ctx.reply)
        ctx.reply = _RECALL_RE.sub("", ctx.reply).strip()

        if results:
            ctx.extra.setdefault("_tag_results", []).extend(results)

        return ctx
