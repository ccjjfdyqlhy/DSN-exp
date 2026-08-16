# harness/models/lmstudio.py
# LMStudioChat — 本地 LMStudio（OpenAI 兼容 /v1/chat/completions）客户端。
#
# 从 DSN 应用的 LMStudioChat 广义化移植：
#   - 实现 IChatClient 契约（invoke/stream），原生 JSON tool call
#   - 流式：SSE 逐 token（文本增量 yield str；工具调用增量 yield dict）
#   - 模型加载管理：无模型错误自动加载重试；可选接入 ModelScheduler
#     （scheduler.use(model_name) 上下文管理器）获得多模型编排
#   - 应用专属能力（视觉/描述/历史管理）由应用层子类扩展，不在此层

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Optional

import requests

from .base import ChatClientAdapter, ChatResponse, ToolCall

logger = logging.getLogger("LMStudioChat")


def is_no_model_error(response) -> bool:
    """检查 HTTP 400 错误是否因 'No models loaded' 导致。"""
    if response is None or response.status_code != 400:
        return False
    try:
        body = response.text or ""
        return "no model" in body.lower() or "No models loaded" in body
    except Exception:
        return False


def post_json(session: requests.Session, url: str, headers: dict,
              payload: dict, timeout: int | float) -> dict:
    """通过可复用会话提交 JSON 请求并解码响应。"""
    response = session.post(url, headers=headers, json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def load_lmstudio_model(base_url: str, model_name: str, label: str,
                        timeout: int = 180) -> bool:
    """向 LMStudio 发送模型加载请求，返回是否成功。"""
    if not model_name:
        logger.error("未配置 model_name，无法自动加载 %s", label)
        return False
    try:
        logger.info("正在加载 %s: %s", label, model_name)
        load_resp = requests.post(
            f"{base_url}/api/v1/models/load",
            json={"model": model_name},
            timeout=timeout,
        )
        load_resp.raise_for_status()
        result = load_resp.json()
        logger.info("%s 加载完成 (%.1fs): %s", label,
                    result.get("load_time_seconds", 0), model_name)
        return True
    except Exception as e:
        logger.error("自动加载 %s 失败 (%s): %s", label, model_name, e)
        return False


def unload_lmstudio_model(base_url: str, model_name: str) -> bool:
    """卸载 LMStudio 模型，返回是否成功。

    兼容两种请求体：instance_id（LMStudio 新版）与 model（旧版）。
    """
    if not model_name:
        return False
    try:
        resp = requests.post(
            f"{base_url}/api/v1/models/unload",
            json={"instance_id": model_name, "model": model_name},
            timeout=30,
        )
        resp.raise_for_status()
        logger.info("已卸载模型: %s", model_name)
        return True
    except Exception as e:
        logger.error("卸载模型 %s 失败: %s", model_name, e)
        return False


class LMStudioChat(ChatClientAdapter):
    """本地 LMStudio 聊天客户端（OpenAI 兼容 /v1/chat/completions）。

    scheduler 可选：提供 use(model_name) 上下文管理器的对象
    （如 harness.models.scheduler.ModelScheduler），用于多模型编排。
    """

    def __init__(
        self,
        base_url: str = "http://localhost:4501",
        model_name: Optional[str] = None,
        timeout: int = 300,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        scheduler: Optional[Any] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.model: str = model_name or "lmstudio"
        self.last_usage = None
        self.last_model = self.model
        self._scheduler = scheduler
        self._http_session = requests.Session()

    # ── 底层调用 ──

    def _call_chat_api(self, payload: dict) -> dict:
        """调用 /v1/chat/completions；接入了 scheduler 时经 scheduler.use 获取使用权。"""
        if self._scheduler is not None and self.model_name:
            with self._scheduler.use(self.model_name, timeout=self.timeout):
                return self._do_call_chat_api(payload)
        return self._do_call_chat_api(payload)

    def _do_call_chat_api(self, payload: dict) -> dict:
        """原始 HTTP 调用，含自动加载重试（未接入 scheduler 时的回退路径）。"""
        url = f"{self.base_url}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        for attempt in range(2):
            try:
                result = post_json(self._http_session, url, headers,
                                   payload, self.timeout)
                self.last_usage = result.get("usage")
                self.last_model = result.get("model", self.model_name)
                return result
            except requests.exceptions.HTTPError as e:
                if attempt == 0 and is_no_model_error(e.response):
                    logger.info("检测到 LMStudio 未加载模型，自动加载后重试……")
                    if self._ensure_model_loaded():
                        continue
                raise

    def _ensure_model_loaded(self) -> bool:
        return load_lmstudio_model(self.base_url, self.model_name,
                                   "LMStudio 模型")

    # ── IChatClient 契约 ──

    def invoke(
        self,
        messages: list[Any],
        tools: Optional[list[dict]] = None,
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> ChatResponse:
        msgs = self._to_message_dicts(messages)
        payload: dict[str, Any] = {
            "messages": msgs,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
            "stream": False,
        }
        if self.model_name:
            payload["model"] = self.model_name
        if tools:
            payload["tools"] = [{"type": "function", "function": t} for t in tools]

        result = self._call_chat_api(payload)
        choice = (result.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content") or ""

        tool_calls: list[ToolCall] = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except (TypeError, ValueError):
                args = {}
            tool_calls.append(ToolCall(
                id=tc.get("id", ""), name=fn.get("name", ""), arguments=args))

        return ChatResponse(
            content=content,
            tool_calls=tool_calls,
            usage=self.last_usage or {},
            model=self.last_model or self.model,
            finish_reason=choice.get("finish_reason"),
        )

    async def stream(
        self,
        messages: list[Any],
        tools: Optional[list[dict]] = None,
        **kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        """SSE 流式：文本增量 yield str；工具调用增量 yield dict（原始片段，由消费方按 index 拼接）。"""
        msgs = self._to_message_dicts(messages)
        payload: dict[str, Any] = {
            "messages": msgs,
            "temperature": kwargs.get("temperature", self.temperature),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "stream": True,
        }
        if self.model_name:
            payload["model"] = self.model_name
        if tools:
            payload["tools"] = [{"type": "function", "function": t} for t in tools]

        def _request():
            url = f"{self.base_url}/v1/chat/completions"
            headers = {"Content-Type": "application/json"}
            return self._http_session.post(
                url, headers=headers, json=payload, timeout=self.timeout,
                stream=True)

        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, _request)
        resp.raise_for_status()

        for raw in resp.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data:"):
                continue
            data = raw[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except (TypeError, ValueError):
                continue
            if not chunk.get("choices"):
                continue
            delta = chunk["choices"][0].get("delta") or {}
            if delta.get("content"):
                yield delta["content"]
            tc_delta = delta.get("tool_calls")
            if tc_delta:
                emitted = []
                for tc in tc_delta:
                    fn = tc.get("function") or {}
                    emitted.append({
                        "index": tc.get("index", 0) or 0,
                        "id": tc.get("id", "") or "",
                        "name": fn.get("name", "") or "",
                        # 只带本 chunk 的片段，由 AgentLoop 负责按 index 拼接
                        "arguments": fn.get("arguments", "") or "",
                    })
                if emitted:
                    yield {"tool_calls": emitted}
        resp.close()
