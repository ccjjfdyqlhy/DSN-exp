# harness/models/openai.py
# OpenAI 兼容接口适配器 — 通用实现，不依赖任何应用语义。
#
# 适配 DeepSeek / Zhipu GLM / OpenAI 等一切兼容 /chat/completions 的服务。

from __future__ import annotations

import json
from typing import Any, AsyncGenerator, Optional

from .base import ChatClientAdapter, ChatResponse, ToolCall


class OpenAICompatClient(ChatClientAdapter):
    """基于 openai SDK 的通用兼容客户端。"""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: Optional[str] = None,
        model: str = "gpt-4o-mini",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
        extra_headers: Optional[dict] = None,
    ):
        self.model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._timeout = timeout
        self._extra_headers = extra_headers or {}

        from openai import OpenAI  # 延迟导入，避免未安装时影响其他模块
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            default_headers=self._extra_headers or None,
        )

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
        kwargs: dict[str, Any] = {"model": self.model, "messages": msgs}
        if tools:
            kwargs["tools"] = [{"type": "function", "function": t} for t in tools]
        if temperature is not None:
            kwargs["temperature"] = temperature
        elif self._temperature is not None:
            kwargs["temperature"] = self._temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        elif self._max_tokens is not None:
            kwargs["max_tokens"] = self._max_tokens

        resp = self._client.chat.completions.create(**kwargs)
        return self._to_response(resp)

    async def stream(
        self,
        messages: list[Any],
        tools: Optional[list[dict]] = None,
        **kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        """流式输出：文本增量 yield str；工具调用增量 yield dict（见 IChatClient）。

        OpenAI 流式响应的 tool_calls 分布在多个 chunk 的 delta 中，
        按 index 累积 id/name/arguments（arguments 为字符串片段拼接）。
        """
        msgs = self._to_message_dicts(messages)
        params: dict[str, Any] = {"model": self.model, "messages": msgs, "stream": True}
        if tools:
            params["tools"] = [{"type": "function", "function": t} for t in tools]
        params.update({k: v for k, v in kwargs.items() if v is not None})

        stream = self._client.chat.completions.create(**params)
        # index -> 累积的工具调用增量
        tool_deltas: dict[int, dict] = {}
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta is None:
                continue
            if delta.content:
                yield delta.content
            tc_delta = getattr(delta, "tool_calls", None)
            if tc_delta:
                emitted = []
                for tc in tc_delta:
                    idx = getattr(tc, "index", 0)
                    acc = tool_deltas.setdefault(
                        idx, {"index": idx, "id": "", "name": "", "arguments": ""})
                    if getattr(tc, "id", None):
                        acc["id"] = tc.id
                    fn = getattr(tc, "function", None)
                    if fn is not None:
                        if getattr(fn, "name", None):
                            acc["name"] = fn.name
                        if getattr(fn, "arguments", None):
                            acc["arguments"] += fn.arguments or ""
                    emitted.append(dict(acc))
                if emitted:
                    yield {"tool_calls": emitted}

    @staticmethod
    def _to_response(resp: Any) -> ChatResponse:
        choice = resp.choices[0] if resp.choices else None
        if choice is None:
            return ChatResponse(content="", usage=dict(getattr(resp, "usage", {}) or {}),
                                model=getattr(resp, "model", None))

        content = getattr(choice.message, "content", None) or ""
        tool_calls: list[ToolCall] = []
        for tc in getattr(choice.message, "tool_calls", None) or []:
            func = tc.function
            try:
                args = json.loads(func.arguments or "{}")
            except (TypeError, ValueError):
                args = {}
            tool_calls.append(ToolCall(id=tc.id, name=func.name, arguments=args))

        return ChatResponse(
            content=content,
            tool_calls=tool_calls,
            usage=dict(getattr(resp, "usage", {}) or {}),
            model=getattr(resp, "model", None),
            finish_reason=choice.finish_reason,
        )
