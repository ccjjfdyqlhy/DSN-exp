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

        from openai import AsyncOpenAI, OpenAI  # 延迟导入，避免未安装时影响其他模块
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            default_headers=self._extra_headers or None,
        )
        self._async_client = AsyncOpenAI(
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

        OpenAI 流式响应的 tool_calls 分布在多个 chunk 的 delta 中。
        本方法只产出"原始增量片段"（arguments 为本 chunk 的片段，不做累积），
        由消费方（AgentLoop）按 index 拼接，避免双方各累积一次导致 JSON 损坏。
        """
        msgs = self._to_message_dicts(messages)
        params: dict[str, Any] = {"model": self.model, "messages": msgs, "stream": True}
        if tools:
            params["tools"] = [{"type": "function", "function": t} for t in tools]
        params.update({k: v for k, v in kwargs.items() if v is not None})

        stream = await self._async_client.chat.completions.create(**params)
        async for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                yield {"usage": dict(usage)}
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta is None:
                continue
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                yield {"reasoning": reasoning}
            if delta.content:
                yield delta.content
            tc_delta = getattr(delta, "tool_calls", None)
            if tc_delta:
                emitted = []
                for tc in tc_delta:
                    fn = getattr(tc, "function", None)
                    emitted.append({
                        "index": getattr(tc, "index", 0) or 0,
                        "id": getattr(tc, "id", None) or "",
                        "name": (getattr(fn, "name", None) or "") if fn is not None else "",
                        # 只带本 chunk 的片段，由 AgentLoop 负责按 index 拼接
                        "arguments": (getattr(fn, "arguments", None) or "") if fn is not None else "",
                    })
                if emitted:
                    yield {"tool_calls": emitted}

    @staticmethod
    def _to_response(resp: Any) -> ChatResponse:
        choice = resp.choices[0] if resp.choices else None
        if choice is None:
            return ChatResponse(content="", usage=dict(getattr(resp, "usage", {}) or {}),
                                model=getattr(resp, "model", None))

        content = getattr(choice.message, "content", None) or ""
        reasoning = getattr(choice.message, "reasoning_content", None) or ""
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
            reasoning_content=reasoning or None,
        )
