# harness/models/openai.py
# OpenAI 兼容接口适配器 — 通用实现，不依赖任何应用语义。
#
# 同时支持两种请求协议：
#   - chat      : /v1/chat/completions（DeepSeek / Zhipu / OpenAI 等）
#   - responses : /v1/responses（OpenAI Responses API）

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
        protocol: str = "chat",
    ):
        self.model = model
        self.protocol = protocol
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
        if self.protocol == "responses":
            return self._invoke_responses(messages, tools, temperature=temperature,
                                          max_tokens=max_tokens, timeout=timeout)
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

    def _invoke_responses(
        self,
        messages: list[Any],
        tools: Optional[list[dict]] = None,
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> ChatResponse:
        params: dict[str, Any] = {
            "model": self.model,
            "input": self._messages_to_responses_input(messages),
        }
        if tools:
            params["tools"] = self._tools_to_responses(tools)
        if temperature is not None:
            params["temperature"] = temperature
        elif self._temperature is not None:
            params["temperature"] = self._temperature
        if max_tokens is not None:
            params["max_output_tokens"] = max_tokens
        elif self._max_tokens is not None:
            params["max_output_tokens"] = self._max_tokens
        if timeout is not None:
            params["timeout"] = timeout
        elif self._timeout is not None:
            params["timeout"] = self._timeout

        # invoke 是同步方法（在 AgentLoop 的线程池里执行），用同步 Responses client
        resp = self._client.responses.create(**params)
        return self._to_responses_response(resp)

    @staticmethod
    def _to_responses_response(resp: Any) -> ChatResponse:
        content_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        reasoning_parts: list[str] = []
        for item in getattr(resp, "output", []) or []:
            itype = getattr(item, "type", "")
            if itype == "message":
                for part in getattr(item, "content", []) or []:
                    text = getattr(part, "text", None)
                    if text:
                        content_parts.append(text)
            elif itype == "function_call":
                try:
                    args = json.loads(item.arguments or "{}")
                except (TypeError, ValueError):
                    args = {}
                tool_calls.append(ToolCall(
                    id=getattr(item, "call_id", None) or getattr(item, "id", "") or "",
                    name=getattr(item, "name", "") or "",
                    arguments=args,
                ))
            elif itype == "reasoning":
                for s in getattr(item, "summary", []) or []:
                    t = getattr(s, "text", "")
                    if t:
                        reasoning_parts.append(t)
                for c in getattr(item, "content", []) or []:
                    t = getattr(c, "text", "")
                    if t:
                        reasoning_parts.append(t)
        usage = getattr(resp, "usage", None)
        return ChatResponse(
            content="".join(content_parts),
            tool_calls=tool_calls,
            usage=dict(usage) if usage else {},
            model=getattr(resp, "model", None),
            finish_reason=None,
            reasoning_content="\n".join([p for p in reasoning_parts if p]) or None,
        )

    @staticmethod
    def _messages_to_responses_input(messages: list[Any]) -> list[dict]:
        """把 ChatMessage 列表转成 Responses API 的 input items。"""
        items: list[dict] = []
        for m in messages:
            if isinstance(m, dict):
                items.append(m)
                continue
            role = getattr(m, "role", "")
            content = getattr(m, "content", "") or ""
            if role == "system":
                items.append({"role": "system", "content": [{"type": "input_text", "text": content}]})
            elif role == "user":
                items.append({"role": "user", "content": [{"type": "input_text", "text": content}]})
            elif role == "assistant":
                items.append({"role": "assistant", "content": [{"type": "output_text", "text": content}]})
                for tc in (getattr(m, "tool_calls", None) or []):
                    fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                    items.append({
                        "type": "function_call",
                        "call_id": tc.get("id", "") if isinstance(tc, dict) else "",
                        "name": fn.get("name", ""),
                        "arguments": fn.get("arguments", "{}"),
                    })
            elif role == "tool":
                items.append({
                    "type": "function_call_output",
                    "call_id": getattr(m, "tool_call_id", "") or "",
                    "output": content,
                })
        return items

    @staticmethod
    def _tools_to_responses(tools: Optional[list[dict]]) -> list[dict]:
        """把 chat 协议的 tools 列表转成 Responses API 的 tools 格式。"""
        out = []
        for t in tools or []:
            out.append({
                "type": "function",
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {}),
            })
        return out

    async def stream(
        self,
        messages: list[Any],
        tools: Optional[list[dict]] = None,
        **kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        """流式输出：文本增量 yield str；工具调用增量 yield dict（见 IChatClient）。

        支持 chat.completions 与 responses 两种协议。
        """
        if self.protocol == "responses":
            async for chunk in self._stream_responses(messages, tools, **kwargs):
                yield chunk
            return

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

    async def _stream_responses(
        self,
        messages: list[Any],
        tools: Optional[list[dict]] = None,
        **kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        params: dict[str, Any] = {
            "model": self.model,
            "input": self._messages_to_responses_input(messages),
        }
        if tools:
            params["tools"] = self._tools_to_responses(tools)
        if kwargs.get("temperature") is not None:
            params["temperature"] = kwargs["temperature"]
        elif self._temperature is not None:
            params["temperature"] = self._temperature
        if kwargs.get("max_tokens") is not None:
            params["max_output_tokens"] = kwargs["max_tokens"]
        elif self._max_tokens is not None:
            params["max_output_tokens"] = self._max_tokens

        # output_index -> {id, name}（function_call 元信息来自 output_item.added）
        call_meta: dict[int, dict] = {}
        async with self._async_client.responses.stream(**params) as stream:
            async for event in stream:
                et = getattr(event, "type", "")
                if et == "response.output_text.delta":
                    yield getattr(event, "delta", "")
                elif et in ("response.reasoning_text.delta",
                            "response.reasoning_summary_text.delta"):
                    delta = getattr(event, "delta", "")
                    if delta:
                        yield {"reasoning": delta}
                elif et == "response.output_item.added":
                    item = getattr(event, "item", None)
                    if item is not None and getattr(item, "type", "") == "function_call":
                        call_meta[getattr(event, "output_index", 0)] = {
                            "id": getattr(item, "call_id", None) or getattr(item, "id", "") or "",
                            "name": getattr(item, "name", "") or "",
                        }
                elif et == "response.function_call_arguments.delta":
                    idx = getattr(event, "output_index", 0)
                    meta = call_meta.get(idx, {})
                    yield {"tool_calls": [{
                        "index": idx,
                        "id": meta.get("id", ""),
                        "name": meta.get("name", ""),
                        "arguments": getattr(event, "delta", ""),
                    }]}
                elif et == "response.completed":
                    usage = getattr(getattr(event, "response", None), "usage", None)
                    if usage:
                        yield {"usage": dict(usage)}

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
