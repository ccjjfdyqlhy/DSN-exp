# plugins/builtin/models_plugin.py
# 统一模型调用插件 — MODEL_INVOKE (原生 tool call 支持)

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from plugins.base import Plugin, HookPoint, PluginContext
from config import Config

logger = logging.getLogger("ModelsPlugin")


class ModelsPlugin(Plugin):
    name = "models"
    description = "统一模型调用 — DeepSeek / LMStudio 原生 tool call 支持"
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
        self._skill_registry = None
        self._tool_call_mode = getattr(Config, "TOOL_CALL_MODE", "native")

    def set_skill_registry(self, registry):
        self._skill_registry = registry
        tools_count = len(registry.get_tools_schema()) if registry else 0
        logger.info("ModelsPlugin: skill_registry 已注入, %d 个可用工具", tools_count)

    def on_load(self) -> None:
        logger.info("ModelsPlugin 已加载 — model_type=%s tool_call_mode=%s",
                    self._model_type, self._tool_call_mode)

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        system_history = [{"role": "system", "content": ctx.system_prompt}]
        full_messages = system_history + ctx.full_history

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        timestamped = f"[{now}] {ctx.message}"

        effective_type = ctx.model_type or self._model_type

        # 决定是否使用原生 tool call 模式
        use_native = (self._tool_call_mode in ("native", "auto")
                      and effective_type == "deepseek")

        tools_schema = None
        if use_native:
            tools_schema = self._build_tools_schema()
            logger.info("ModelsPlugin: 原生模式, 工具 schema=%d, model=%s",
                        len(tools_schema), effective_type)

        try:
            chat = self._create_chat(effective_type)
            chat.messages = full_messages.copy()

            if tools_schema:
                reply = chat.send_message(timestamped, tools=tools_schema)
                logger.info("ModelsPlugin: 已发送 %d 个工具定义到 API",
                            len(tools_schema))
            else:
                reply = chat.send_message(timestamped)
                logger.info("ModelsPlugin: 未发送工具定义 (XML 模式或无可用工具)")

            ctx.usage = getattr(chat, 'last_usage', None)
            ctx.model_name = getattr(chat, 'last_model', effective_type)

            if tools_schema is not None and hasattr(chat, 'last_tool_calls') and chat.last_tool_calls:
                ctx.extra["_native_tool_calls"] = chat.last_tool_calls
                ctx.extra["_last_tool_calls"] = chat.last_tool_calls
                logger.info("ModelsPlugin: 模型返回 %d 个原生 tool_calls",
                            len(chat.last_tool_calls))
                from models import DETAIL_ACTIONS
                if DETAIL_ACTIONS:
                    print("\n" + "=" * 60)
                    print("📤 [模型响应] 原生 tool_calls:")
                    print("=" * 60)
                for tc in chat.last_tool_calls:
                    tc_name = tc.get("function", {}).get("name", "?")
                    tc_args = tc.get("function", {}).get("arguments", "{}")
                    logger.info("  → tool_call: %s(%s)", tc_name, tc_args[:80])
                    if DETAIL_ACTIONS:
                        print(f"\n  ▶ {tc['id']}")
                        print(f"  ┌─ {tc_name}")
                        print(f"  │  {json.dumps(json.loads(tc_args), ensure_ascii=False, indent=2)}")
                        print("  └─────────────")
                # 检测是否有异步工具调用
                if self._skill_registry:
                    for tc in chat.last_tool_calls:
                        func_name = tc.get("function", {}).get("name", "")
                        parts = func_name.split("-", 2)
                        if len(parts) >= 3:
                            spec = self._skill_registry.get_tool_spec(parts[1], parts[2])
                            if spec and spec.get("async"):
                                ctx.extra["_async_detected"] = True
                                ctx.extra["_async_tool_count"] = len(chat.last_tool_calls)
                                logger.info("ModelsPlugin: 检测到异步工具 %s，将切入后台执行", func_name)
                                break
            elif tools_schema is not None and use_native:
                logger.info("ModelsPlugin: 模型未返回 tool_calls (文本回复)")
        except Exception as e:
            logger.error("模型调用失败: %s", e)
            ctx.reply = "抱歉，AI 服务暂不可用，请稍后重试。"
            ctx.original_reply = ctx.reply
            ctx.filtered = True
            return ctx

        ctx.original_reply = reply
        ctx.reply = self._clean_reply(reply)

        if self._db is not None and ctx.chat_id and not ctx.extra.get("_debug_mode"):
            try:
                round_index = self._db.get_next_round_index(ctx.chat_id)
                ctx.extra["round_index"] = round_index
                last_msgs = [m for m in chat.messages[-2:] if m.get("content")]
                if last_msgs:
                    self._db.append_messages(
                        ctx.user_id, ctx.chat_id, last_msgs,
                        round_index=round_index,
                    )
            except Exception as e:
                logger.error("保存消息失败: %s", e)

        return ctx

    def _build_tools_schema(self) -> list[dict]:
        tools = []
        if not self._skill_registry:
            logger.warning("ModelsPlugin: skill_registry 未注入, 工具 schema 为空")
            return tools

        try:
            tools = self._skill_registry.get_tools_schema()
            if tools:
                namespaces = set()
                for t in tools:
                    ns = t["function"]["name"].split(".")[1] if "." in t["function"]["name"] else "root"
                    namespaces.add(ns)
                logger.info("ModelsPlugin: 已加载 %d 个工具 schema (命名空间: %s)",
                            len(tools), ", ".join(sorted(namespaces)))
            else:
                logger.warning("ModelsPlugin: skill_registry.get_tools_schema() 返回空列表")
        except Exception as e:
            logger.warning("ModelsPlugin: 加载技能工具 schema 失败: %s", e)

        return tools

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
            chat = DeepSeekChat(api_key=self._deepseek_api_key)
            logger.info("ModelsPlugin: 创建 DeepSeekChat — model=%s", chat.model)
            return chat

    @staticmethod
    def _clean_reply(reply: str) -> str:
        import re
        cleaned = re.sub(r"<text>(.*?)</text>", r"\1", reply,
                          flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"```\w*\s*\n.*?```", "", cleaned,
                          flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<task>.*?</task>", "", cleaned,
                          flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<recall>.*?</recall>", "", cleaned,
                          flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<tool>.*?</tool>", "", cleaned,
                          flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<help>.*?</help>", "", cleaned,
                          flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<continue\s*/>", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"<[^>]+>", "", cleaned)
        cleaned = re.sub(r"[^\S\n]+", " ", cleaned)
        cleaned = re.sub(r"\n{2,}", "\n", cleaned)
        cleaned = cleaned.strip()
        if not cleaned:
            cleaned = "…"
        return cleaned

    def invoke(self, messages: list[dict], ctx: PluginContext | None = None,
               tools: list[dict] = None) -> str:
        effective_type = ctx.model_type if ctx and ctx.model_type else self._model_type
        chat = self._create_chat(effective_type)
        chat.messages = list(messages)
        kwargs = {"tools": tools, "tool_choice": "auto"} if tools else {}
        reply = chat.continue_conversation(**kwargs)

        if ctx and hasattr(chat, 'last_tool_calls') and chat.last_tool_calls:
            ctx.extra.setdefault("_native_tool_calls", []).extend(
                chat.last_tool_calls
            )
            ctx.extra["_last_tool_calls"] = chat.last_tool_calls
            logger.info("ModelsPlugin.invoke: 模型返回 %d 个 tool_calls",
                        len(chat.last_tool_calls))
            from models import DETAIL_ACTIONS
            if DETAIL_ACTIONS:
                print("\n" + "=" * 60)
                print("📤 [Agent Loop] 原生 tool_calls:")
                print("=" * 60)
                for tc in chat.last_tool_calls:
                    tc_name = tc.get("function", {}).get("name", "?")
                    tc_args = tc.get("function", {}).get("arguments", "{}")
                    print(f"  ▶ {tc['id']} ─ {tc_name}")
                    try:
                        print(json.dumps(json.loads(tc_args), ensure_ascii=False, indent=2))
                    except Exception:
                        print(f"  {tc_args}")
        return reply

    def describe_image(self, data_url: str,
                        prompt: str = "请详细描述这张图片的内容") -> str:
        from models import LMStudioChat
        chat = LMStudioChat(
            base_url=self._lmstudio_base_url,
            model_name=self._lmstudio_model_name,
            temperature=0.1,
            max_tokens=500,
            timeout=self._lmstudio_timeout,
        )
        return chat.describe_image(data_url, prompt)
