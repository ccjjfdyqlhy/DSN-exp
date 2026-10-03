# engine_support.py
# dsn_study 引擎支撑件 — 旧 dsn 管线契约的最小实现。
#
# 参考 api/scan.py 等从原 dsn 应用搬运来的代码所依赖的两个契约:
#   - PluginContext: 管线处理的消息载体（user_id/message/history/extra/reply）
#   - engine.pipeline.process(ctx): 调用主模型生成回复并写回 ctx.reply
# 以及领域层（ErrorAnalyzer/KnowledgeMatcher/Builder）期望的
# models_plugin.send_message(prompt) -> str 单文本调用接口。

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger("StudyEngineSupport")


class PluginContext:
    """轻量消息上下文（对齐 apps.dsn.plugins.base.PluginContext 的常用字段）。"""

    def __init__(self, user_id: int = 0, message: str = "", chat_id: int = 0,
                 history: Optional[list] = None, full_history: Optional[list] = None,
                 **kwargs):
        self.user_id = user_id
        self.message = message
        self.chat_id = chat_id
        self.history = history or []
        self.full_history = full_history or []
        self.extra: dict[str, Any] = {}
        self.tts_enabled = False
        self.reply = ""
        self.audio_b64 = ""
        for k, v in kwargs.items():
            setattr(self, k, v)


class LLMService:
    """把 harness IChatClient 适配成领域层期望的 models_plugin 接口。

    提供 send_message(prompt) -> str；领域代码（ErrorAnalyzer、
    KnowledgeMatcher、KnowledgeGraphBuilder、text_extract 等）只依赖该方法。
    """

    def __init__(self, chat_client):
        self._client = chat_client

    def send_message(self, prompt: str, **kwargs) -> str:
        from harness.models import ChatMessage
        resp = self._client.invoke([ChatMessage.user(prompt)])
        return resp.content or ""

    def __repr__(self):
        return f"<LLMService client={type(self._client).__name__}>"


class StudyPipeline:
    """engine.pipeline 契约的最小实现：process(ctx) → 主模型 → ctx.reply。

    供 api/scan.py 的批次总结等旧管线调用点使用。
    """

    def __init__(self, chat_client, system_prompt: str = ""):
        self._client = chat_client
        self._system_prompt = system_prompt

    async def process(self, ctx: PluginContext) -> PluginContext:
        from harness.models import ChatMessage
        messages = []
        if self._system_prompt:
            messages.append(ChatMessage.system(self._system_prompt))
        for m in (ctx.history or [])[-12:]:
            role = m.get("role") if isinstance(m, dict) else getattr(m, "role", "user")
            content = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
            if role == "user":
                messages.append(ChatMessage.user(content))
            elif role == "assistant":
                messages.append(ChatMessage.assistant(content))
        messages.append(ChatMessage.user(ctx.message))
        try:
            # 同步客户端放到线程池执行，让外层 asyncio.wait_for 超时真正可打断
            resp = await asyncio.to_thread(self._client.invoke, messages)
            ctx.reply = (resp.content or "") if hasattr(resp, "content") else str(resp)
        except Exception as e:
            logger.error("StudyPipeline 处理失败: %s", e)
            ctx.reply = ""
        return ctx
