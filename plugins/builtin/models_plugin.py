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
        model_type: str = "openai",
        openai_api_key: str | None = None,
        openai_api_base: str | None = None,
        openai_model_name: str | None = None,
        lmstudio_base_url: str = "http://localhost:4501",
        lmstudio_model_name: str | None = None,
        lmstudio_temperature: float = 0.7,
        lmstudio_max_tokens: int = 4096,
        lmstudio_timeout: int = 300,
        complexity_analyzer=None,
        db=None,
    ):
        self._model_type = model_type
        self._openai_api_key = openai_api_key
        self._openai_api_base = openai_api_base
        self._openai_model_name = openai_model_name
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
        self._cached_tool_index = registry.get_tools_index() if registry else []

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
                       and effective_type == "openai")

        use_toolbox = getattr(Config, "TOOLBOX_ENABLED", True)
        activated = ctx.extra.get("_activated_tools", None)
        tools_schema = None
        if use_native:
            tools_schema = self._build_tools_schema(activated)
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
                # 分离 toolbox 调用和真实工具调用
                toolbox_calls = []
                real_calls = []
                for tc in chat.last_tool_calls:
                    if tc.get("function", {}).get("name") == "toolbox":
                        toolbox_calls.append(tc)
                    else:
                        real_calls.append(tc)

                # 处理 toolbox 调用 → 填充 _activated_tools
                if toolbox_calls and use_toolbox:
                    for tc in toolbox_calls:
                        try:
                            args = json.loads(tc.get("function", {}).get("arguments", "{}"))
                            ids = args.get("ids", [])
                            act = ctx.extra.setdefault("_activated_tools", [])
                            for aid in ids:
                                if aid not in act:
                                    act.append(aid)
                            logger.info("ModelsPlugin: toolbox 激活工具: %s", ids)
                        except Exception as e:
                            logger.warning("ModelsPlugin: toolbox 解析失败: %s", e)
                    # toolbox 的调用结果由 ToolPlugin 生成确认消息
                    tool_call_results = []
                    for tc in toolbox_calls:
                        try:
                            args = json.loads(tc.get("function", {}).get("arguments", "{}"))
                            ids = args.get("ids", [])
                            tool_call_results.append({
                                "function": "toolbox",
                                "tool_call_id": tc["id"],
                                "success": True,
                                "data": {"activated": ids,
                                         "message": f"已激活工具: {', '.join(ids)}"}
                            })
                        except Exception as e:
                            tool_call_results.append({
                                "function": "toolbox",
                                "tool_call_id": tc["id"],
                                "success": False,
                                "error": str(e),
                            })
                    if tool_call_results:
                        ctx.extra.setdefault("_tag_results", []).extend(tool_call_results)

                if real_calls:
                    ctx.extra["_native_tool_calls"] = real_calls
                    logger.info("ModelsPlugin: 模型返回 %d 个原生 tool_calls",
                                len(real_calls))
                else:
                    ctx.extra.pop("_native_tool_calls", None)

                # _last_tool_calls 给 agent loop 构建 assistant.tool_calls（含 toolbox）
                all_visible = toolbox_calls + real_calls
                if all_visible:
                    ctx.extra["_last_tool_calls"] = all_visible
                    logger.info("ModelsPlugin: 共 %d 个 tool_calls (含 %d 个 toolbox)",
                                len(all_visible), len(toolbox_calls))
                else:
                    ctx.extra.pop("_last_tool_calls", None)

                from models import DETAIL_ACTIONS
                if DETAIL_ACTIONS:
                    all_calls = toolbox_calls + real_calls
                    if all_calls:
                        print("\n" + "=" * 60)
                        print("📤 [模型响应] 原生 tool_calls:")
                        print("=" * 60)
                        for tc in all_calls:
                            tc_name = tc.get("function", {}).get("name", "?")
                            tc_args = tc.get("function", {}).get("arguments", "{}")
                            logger.info("  → tool_call: %s(%s)", tc_name, tc_args[:80])
                            print(f"\n  ▶ {tc['id']}")
                            print(f"  ┌─ {tc_name}")
                            print(f"  │  {json.dumps(json.loads(tc_args), ensure_ascii=False, indent=2)}")
                            print("  └─────────────")

                # 检测异步工具（仅对真实工具调用）
                if real_calls and self._skill_registry:
                    for tc in real_calls:
                        func_name = tc.get("function", {}).get("name", "")
                        parts = func_name.split("-", 2)
                        if len(parts) >= 3:
                            spec = self._skill_registry.get_tool_spec(parts[1], parts[2])
                            if spec and spec.get("async"):
                                ctx.extra["_async_detected"] = True
                                ctx.extra["_async_tool_count"] = len(real_calls)
                                logger.info("ModelsPlugin: 检测到异步工具 %s，将切入后台执行", func_name)
                                break

                # 如果仅有 toolbox 调用, 设标记让 agent 循环继续
                if real_calls or toolbox_calls:
                    pass
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

    def _build_tools_schema(self, activated: list[str] = None) -> list[dict]:
        if not self._skill_registry:
            toolbox_tool = self._build_toolbox_schema(True)
            return [toolbox_tool] if toolbox_tool else []

        use_toolbox = getattr(Config, "TOOLBOX_ENABLED", True)

        if not use_toolbox:
            return self._build_full_schema()

        if not activated:
            tb = self._build_toolbox_schema(True)
            logger.info("ModelsPlugin: 工具箱模式, 仅发送 toolbox 工具")
            return [tb] if tb else []

        tb = self._build_toolbox_schema(False)
        detail = [tb] if tb else []
        from skills.loader import SkillLoader
        loader = SkillLoader()
        for key in activated:
            spec = self._skill_registry._tool_specs.get(key)
            if spec:
                tool_spec_obj = spec.get("_tool_spec_obj")
                if tool_spec_obj:
                    schema = loader.build_function_schema(
                        spec.get("_skill_name", ""), tool_spec_obj)
                    detail.append(schema)
        logger.info("ModelsPlugin: 工具箱模式, toolbox + %d 个已激活工具 schema", len(detail) - 1)
        return detail

    def _build_toolbox_schema(self, include_index: bool = True) -> dict:
        if not self._skill_registry:
            return None
        if not hasattr(self, '_cached_tool_index') or not self._cached_tool_index:
            self._cached_tool_index = self._skill_registry.get_tools_index()
        index = self._cached_tool_index

        if include_index:
            index_desc = "\n".join(
                f"  - {item['id']}: {item['description']}"
                for item in index
            ) if index else "暂无可用工具"
            description = (
                "查看并激活你需要的工具。开始处理用户请求前，先思考可能需要哪些工具，"
                "一次调用激活全部。激活后即可在后续轮次中使用。\n\n可用工具:\n" + index_desc
            )
        else:
            description = "激活更多工具。如果处理过程中发现还需要其他工具，调用此工具补充激活。\n\n已激活列表仅供追踪，不再重复列出。"

        enum_ids = [item["id"] for item in index]
        return {
            "type": "function",
            "function": {
                "name": "toolbox",
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ids": {
                            "type": "array",
                            "items": {"type": "string", "enum": enum_ids} if enum_ids else {"type": "string"},
                            "description": "需要激活的工具 ID 列表"
                        }
                    },
                    "required": ["ids"]
                }
            }
        }

    def _build_full_schema(self) -> list[dict]:
        try:
            tools = self._skill_registry.get_tools_schema()
            if tools:
                namespaces = set()
                for t in tools:
                    ns = t["function"]["name"].split(".")[1] if "." in t["function"]["name"] else "root"
                    namespaces.add(ns)
                logger.info("ModelsPlugin: 全量模式, %d 个工具 schema (命名空间: %s)",
                            len(tools), ", ".join(sorted(namespaces)))
            else:
                logger.warning("ModelsPlugin: skill_registry.get_tools_schema() 返回空列表")
            return tools
        except Exception as e:
            logger.warning("ModelsPlugin: 加载技能工具 schema 失败: %s", e)
            return []

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
        # 多账号优先: 配置了 API 账号时使用 FailoverChat（自动回退）
        try:
            from models.api_accounts import get_api_manager
            accounts = get_api_manager().enabled_accounts()
            if accounts:
                from models.api_accounts import FailoverChat
                chat = FailoverChat(accounts)
                logger.info("ModelsPlugin: 创建 FailoverChat — %d 个账号", len(accounts))
                return chat
        except Exception as e:
            logger.warning("ModelsPlugin: 多账号初始化失败，回退单账号: %s", e)
        from models import OpenAIChat
        chat = OpenAIChat(
            api_key=self._openai_api_key,
            model=self._openai_model_name or getattr(Config, "MAIN_MODEL_NAME", "deepseek-v4-flash"),
            api_url=self._openai_api_base
        )
        logger.info("ModelsPlugin: 创建 OpenAIChat — model=%s", chat.model)
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
            use_toolbox = getattr(Config, "TOOLBOX_ENABLED", True)
            toolbox_calls = []
            real_calls = []
            for tc in chat.last_tool_calls:
                if use_toolbox and tc.get("function", {}).get("name") == "toolbox":
                    toolbox_calls.append(tc)
                else:
                    real_calls.append(tc)

            # 处理 toolbox 调用
            if toolbox_calls:
                for tc in toolbox_calls:
                    try:
                        args = json.loads(tc.get("function", {}).get("arguments", "{}"))
                        ids = args.get("ids", [])
                        act = ctx.extra.setdefault("_activated_tools", [])
                        for aid in ids:
                            if aid not in act:
                                act.append(aid)
                        logger.info("ModelsPlugin.invoke: toolbox 激活工具: %s", ids)
                    except Exception as e:
                        logger.warning("ModelsPlugin.invoke: toolbox 解析失败: %s", e)
                # 生成 toolbox 结果
                for tc in toolbox_calls:
                    try:
                        args = json.loads(tc.get("function", {}).get("arguments", "{}"))
                        ids = args.get("ids", [])
                        ctx.extra.setdefault("_tag_results", []).append({
                            "function": "toolbox",
                            "tool_call_id": tc["id"],
                            "success": True,
                            "data": {"activated": ids,
                                     "message": f"已激活工具: {', '.join(ids)}"}
                        })
                    except Exception as e:
                        ctx.extra.setdefault("_tag_results", []).append({
                            "function": "toolbox",
                            "tool_call_id": tc["id"],
                            "success": False,
                            "error": str(e),
                        })

            # 真实工具调用
            if real_calls:
                ctx.extra.setdefault("_native_tool_calls", []).extend(real_calls)

            # 全部合并给 _last_tool_calls（供 agent loop 构建 assistant message）
            all_visible = toolbox_calls + real_calls
            if all_visible:
                ctx.extra["_last_tool_calls"] = all_visible
                logger.info("ModelsPlugin.invoke: 共 %d 个 tool_calls (含 %d 个 toolbox)",
                            len(all_visible), len(toolbox_calls))
            else:
                ctx.extra.pop("_last_tool_calls", None)

            from models import DETAIL_ACTIONS
            if DETAIL_ACTIONS and all_visible:
                print("\n" + "=" * 60)
                print("📤 [Agent Loop] 原生 tool_calls:")
                print("=" * 60)
                for tc in all_visible:
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
