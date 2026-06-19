# plugins/builtin/models_plugin.py
# 统一模型调用插件 — MODEL_INVOKE

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from plugins.base import Plugin, HookPoint, PluginContext

logger = logging.getLogger("ModelsPlugin")


class ModelsPlugin(Plugin):
    """
    统一管理所有 LLM 后端，负责模型的调用与回复获取。

    依赖: 通过 config/constructor 决定使用 DeepSeek 还是 LMStudio。
          可选的 complexity_analyzer 用于按复杂度自动选模型。
          db (ChatDBManager，可选) 用于保存消息。
    """

    name = "models"
    description = "统一模型调用 — DeepSeek / LMStudio 的调用与回复"
    hooks = [HookPoint.MODEL_INVOKE]
    priority = 50

    def __init__(
        self,
        model_type: str = "deepseek",
        deepseek_api_key: str | None = None,
        lmstudio_base_url: str = "http://localhost:4501",
        lmstudio_model_name: str | None = None,
        lmstudio_temperature: float = 0.7,
        lmstudio_max_tokens: int = 4096,
        lmstudio_timeout: int = 300,
        complexity_analyzer=None,
        db=None,
    ):
        self._model_type = model_type
        self._deepseek_api_key = deepseek_api_key
        self._lmstudio_base_url = lmstudio_base_url
        self._lmstudio_model_name = lmstudio_model_name
        self._lmstudio_temperature = lmstudio_temperature
        self._lmstudio_max_tokens = lmstudio_max_tokens
        self._lmstudio_timeout = lmstudio_timeout
        self._complexity = complexity_analyzer
        self._db = db

    def on_load(self) -> None:
        logger.info("模型插件已加载 — 默认类型: %s", self._model_type)

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        # 构建带系统提示词的完整历史
        system_history = [{"role": "system", "content": ctx.system_prompt}]
        full_messages = system_history + ctx.full_history

        # 时间戳消息
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        timestamped = f"[{now}] {ctx.message}"

        # 创建客户端并调用
        effective_type = ctx.model_type or self._model_type

        try:
            chat = self._create_chat(effective_type)
            chat.messages = full_messages.copy()
            reply = chat.send_message(timestamped)
            ctx.usage = getattr(chat, 'last_usage', None)
            ctx.model_name = getattr(chat, 'last_model', effective_type)
        except Exception as e:
            logger.error("模型调用失败: %s", e)
            ctx.reply = "抱歉，AI 服务暂不可用，请稍后重试。"
            ctx.original_reply = ctx.reply
            return ctx

        ctx.original_reply = reply

        # 清洗回复（移除标签）
        ctx.reply = self._clean_reply(reply)

        # 保存消息到数据库
        if self._db is not None and ctx.chat_id:
            try:
                round_index = self._db.get_next_round_index(ctx.chat_id)
                ctx.extra["round_index"] = round_index
                self._db.append_messages(
                    ctx.user_id, ctx.chat_id, chat.messages[-2:],
                    round_index=round_index,
                )
            except Exception as e:
                logger.error("保存消息失败: %s", e)

        return ctx

    # ---- 模型客户端创建 ----

    def _create_chat(self, model_type: str):
        if model_type in ("fast", "lmstudio"):
            from models import LMStudioChat
            return LMStudioChat(
                base_url=self._lmstudio_base_url,
                model_name=self._lmstudio_model_name,
                temperature=self._lmstudio_temperature,
                max_tokens=self._lmstudio_max_tokens,
                timeout=self._lmstudio_timeout,
            )
        else:
            from models import DeepSeekChat
            return DeepSeekChat(api_key=self._deepseek_api_key)

    # ---- 回复清洗 ----

    @staticmethod
    def _clean_reply(reply: str) -> str:
        import re
        cleaned = re.sub(r"<text>(.*?)</text>", r"\1", reply, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"```action\s*\n.*?```", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<task>.*?</task>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<recall>.*?</recall>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<tool>.*?</tool>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<continue\s*/>", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"<[^>]+>", "", cleaned)
        cleaned = re.sub(r"[^\S\n]+", " ", cleaned)
        cleaned = re.sub(r"\n{2,}", "\n", cleaned)
        cleaned = cleaned.strip()
        if not cleaned:
            cleaned = "…"
        return cleaned

    # ---- Agent 循环用 LLM 调用 ----

    def invoke(self, messages: list[dict], ctx: PluginContext | None = None) -> str:
        """
        供 AgentPlugin 直接调用 LLM，不修改 ctx。
        返回 LLM 生成的完整回复文本（含原始标签）。

        消息列表中应已包含 system prompt、历史、工具结果等。
        """
        effective_type = ctx.model_type if ctx and ctx.model_type else self._model_type

        chat = self._create_chat(effective_type)
        chat.messages = list(messages)
        return chat.continue_conversation()

    def describe_image(self, data_url: str, prompt: str = "请详细描述这张图片的内容") -> str:
        """
        调用本地 LMStudio 多模态模型描述图片，返回文字描述。

        始终使用 LMStudioChat，因为只有本地模型支持多模态输入。
        """
        from models import LMStudioChat

        chat = LMStudioChat(
            base_url=self._lmstudio_base_url,
            model_name=self._lmstudio_model_name,
            temperature=0.1,
            max_tokens=500,
            timeout=self._lmstudio_timeout,
        )
        return chat.describe_image(data_url, prompt)
