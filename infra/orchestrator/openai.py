# infra/models/openai.py
# OpenAI 兼容接口适配器 — 通用实现，不依赖任何应用语义。
#
# 同时支持两种请求协议：
#   - chat      : /v1/chat/completions（DeepSeek / Zhipu / OpenAI 等）
#   - responses : /v1/responses（OpenAI Responses API）

from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator, Optional

from .base import ChatClientAdapter, ChatResponse, ToolCall

logger = logging.getLogger("OpenAICompatClient")


def _plain(value: Any) -> Any:
    """把 SDK 返回的 pydantic 对象递归降级成纯 Python 容器。

    为什么必须递归：`dict(usage)` 只转换**顶层**，嵌套的
    `completion_tokens_details` / `prompt_tokens_details` 仍是 pydantic
    模型实例。这些值随后被塞进 SSE 的 json.dumps，于是整条流在终态帧处抛
    "Object of type CompletionTokensDetails is not JSON serializable" ——
    前端表现为回复区空白、思考 tokens 不滚动。

    本地 llama-server 不返回这些嵌套结构，所以只有接第三方 API 时才会踩到。
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(v) for v in value]
    # pydantic v2 / v1 模型
    for attr in ("model_dump", "dict", "to_dict"):
        fn = getattr(value, attr, None)
        if callable(fn):
            try:
                return _plain(fn())
            except Exception:  # noqa: BLE001 - 降级失败则走下面的兜底
                break
    # 最后兜底：按公开属性展开（跳过 _ 开头的私有字段）
    if hasattr(value, "__dict__"):
        return {
            k: _plain(v) for k, v in vars(value).items()
            if not str(k).startswith("_")
        }
    return str(value)


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
        tool_choice: Any = "auto",
        send_tool_choice: bool = True,
        send_usage_in_stream: bool = True,
    ):
        self.model = model
        self.protocol = protocol
        #: 携带 tools 时一并发送的 tool_choice（对齐 apps/dsn：默认 "auto"）。
        #: 个别 provider 不认 tool_choice，可用 send_tool_choice=False 关闭。
        self._tool_choice = tool_choice
        self._send_tool_choice = send_tool_choice
        #: 流式时是否请求远端回传 usage（stream_options.include_usage）。
        #: 少数老网关不认 stream_options，可用 False 关闭以兼容。
        self._send_usage_in_stream = send_usage_in_stream
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

    def _apply_tools(self, params: dict[str, Any], tools: Optional[list[dict]]) -> None:
        """把工具 schema 与 tool_choice 写进请求体（invoke / stream 共用）。

        请求体形状刻意与 apps/dsn 的 OpenAIChat._call_and_append 对齐：
            params["tools"] = [{"type": "function", "function": {...}}, ...]
            params["tool_choice"] = "auto"       # 仅在有工具时携带
        工具名此时已是 wire 名（file__read），由 harness/tools.to_openai_schema 转换，
        模型回传后由 AgentLoop._resolve_tool_name 还原为内部名。
        """
        if not tools:
            return
        params["tools"] = [{"type": "function", "function": t} for t in tools]
        if self._send_tool_choice and self._tool_choice is not None:
            params["tool_choice"] = self._tool_choice

    def _apply_sampling(self, params: dict[str, Any], *,
                        temperature: Optional[float] = None,
                        max_tokens: Optional[int] = None) -> None:
        """采样参数：显式入参优先，其次实例默认。"""
        if temperature is not None:
            params["temperature"] = temperature
        elif self._temperature is not None:
            params["temperature"] = self._temperature
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
        elif self._max_tokens is not None:
            params["max_tokens"] = self._max_tokens

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
        self._apply_tools(kwargs, tools)
        self._apply_sampling(kwargs, temperature=temperature, max_tokens=max_tokens)

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
            usage=_plain(usage) if usage else {},
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
        self._apply_tools(params, tools)

        # 只透传 OpenAI 认识的标准参数。前端请求体里带着一堆 llama.cpp /
        # DSN 专有字段（samplers / dry_* / xtc_* / thinking_budget_tokens /
        # sse_ping_interval / return_progress ...），直接塞给远端网关通常
        # 会被判为非法参数而 400 —— 这也是「本地模型正常、换远端 API 就报错」
        # 的常见诱因之一。
        _STANDARD_STREAM_PARAMS = {
            "temperature", "top_p", "stop", "seed", "presence_penalty",
            "frequency_penalty", "logit_bias", "logprobs", "top_logprobs",
            "n", "response_format", "tool_choice", "parallel_tool_calls",
            "user", "max_tokens", "max_completion_tokens", "stream_options",
        }
        for key, value in kwargs.items():
            if value is not None and key in _STANDARD_STREAM_PARAMS:
                params[key] = value

        # 显式要求远端回传用量：多数 OpenAI 兼容网关在 stream=True 时默认
        # 不下发 usage，不请求的话终态用量恒为 0，前端用量环/计费显示全空。
        if self._send_usage_in_stream:
            params.setdefault("stream_options", {"include_usage": True})

        stream = await self._async_client.chat.completions.create(**params)
        async for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                yield {"usage": _plain(usage)}
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
                for pos, tc in enumerate(tc_delta):
                    fn = getattr(tc, "function", None)
                    raw_index = getattr(tc, "index", None)
                    # 部分网关省略 index（或恒为 None/0）却一次返回多个工具调用，
                    # 全部按 0 累积会把多个调用合并成一个。index 缺失时用位置兜底。
                    if raw_index is None:
                        index = pos
                    else:
                        try:
                            index = int(raw_index)
                        except (TypeError, ValueError):
                            index = pos
                    emitted.append({
                        "index": index,
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
                        yield {"usage": _plain(usage)}

    @staticmethod
    def _to_response(resp: Any) -> ChatResponse:
        choice = resp.choices[0] if resp.choices else None
        if choice is None:
            return ChatResponse(content="", usage=_plain(getattr(resp, "usage", {})) or {},
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
            usage=_plain(getattr(resp, "usage", {})) or {},
            model=getattr(resp, "model", None),
            finish_reason=choice.finish_reason,
            reasoning_content=reasoning or None,
        )
