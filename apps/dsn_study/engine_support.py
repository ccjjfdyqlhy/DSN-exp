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
        from infra.models import ChatMessage
        resp = self._client.invoke([ChatMessage.user(prompt)])
        return resp.content or ""

    def describe_image(self, image, prompt: str = "请详细描述这张图片的内容") -> str:
        """图片描述（ScannerPipeline 等领域代码期望的契约）。

        image 可为本地文件路径或 data URL。

        路由（阶段 0.8 修正）：
          1. 配了 VISION_API_KEY → VisionModel（远程 VLM，推荐）；
          2. 否则回退 LMStudio 本地视觉端点。

        过去兜底把 model_name 直接取 MAIN_MODEL_NAME（默认 deepseek-v4-flash，
        **纯文本模型**），于是「发图给文本模型」——要么 400，要么返回一段
        凭空编造的描述，比直接报错更危险（题目入库会写入幻觉内容）。
        现在兜底只接受显式配置的视觉模型名，且失败时抛出可读错误，
        不再把图片喂给文本模型。
        """
        from apps.dsn_study.config import Config
        from apps.dsn_study.models.clients import (
            VisionModel, LMStudioVisionFallback,
        )
        data_url = image if (isinstance(image, str) and image.startswith("data:")) \
            else VisionModel.encode_image(image)
        if Config.VISION_API_KEY:
            return VisionModel().ask(data_url, prompt)

        # 本地兜底：只认显式的 VISION_FALLBACK_MODEL_NAME，
        # 绝不复用 MAIN_MODEL_NAME（可能是纯文本模型）。
        fallback_model = (getattr(Config, "VISION_FALLBACK_MODEL_NAME", "") or "").strip()
        if not fallback_model:
            raise RuntimeError(
                "未配置视觉模型：VISION_API_KEY 为空，且未设置 "
                "VISION_FALLBACK_MODEL_NAME（本地视觉端点的模型名）。"
                "不把图片发给纯文本模型 —— 请配置远程 VLM 或本地视觉模型。"
            )
        try:
            return LMStudioVisionFallback(model_name=fallback_model).describe_image(
                data_url, prompt)
        except Exception as exc:
            raise RuntimeError(
                "本地视觉兜底失败（model=%s, base=%s）: %s"
                % (fallback_model, getattr(Config, "LMSTUDIO_BASE_URL", "?"), exc)
            ) from exc

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
        from infra.models import ChatMessage
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
