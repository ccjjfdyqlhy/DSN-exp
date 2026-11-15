# infra/orchestrator/anthropic.py
# Anthropic Messages API 适配器 — 与 OpenAICompatClient 同构的第三个协议。
#
# 支持：
#   - POST /v1/messages（Anthropic 原生协议）
#   - 流式 SSE（content_block_delta / tool_use 等事件）
#   - 工具调用（tool_use → ToolCall；tool_result 回喂）
#   - system 提取（Anthropic 把 system 作为独立参数，不在 messages 里）
#
# 设计约束：与 IChatClient 契约一致 —— 流式 yield str（文本增量）
# 或 dict（reasoning / tool_calls / usage），由 AgentLoop 统一消费。

from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator, Optional

from .base import ChatClientAdapter, ChatResponse, ToolCall

logger = logging.getLogger("infra.anthropic")

#: 用户级 effort 档位 -> Anthropic 扩展思考预算（budget_tokens）。
#: 客户端在 wire 边界统一应用这一个映射表。
_EFFORT_BUDGETS: dict[str, int] = {
    "low": 2_048, "medium": 4_096, "high": 8_192, "xhigh": 12_288,
    "max": 16_384, "ultra": 24_576,
}


def effort_thinking_budget(effort: Optional[str], max_tokens: Optional[int]) -> Optional[dict]:
    """Map a user effort dial onto Anthropic extended thinking params.

    Returns the ``thinking`` request dict, or None when thinking must not
    be requested: no effort given, or the Messages API window
    (1024 <= budget_tokens < max_tokens) cannot be satisfied.

    Args:
        effort: user-facing dial name (low ... ultra).
        max_tokens: the request's max_tokens; the budget must stay below it.

    Returns:
        ``{"type": "enabled", "budget_tokens": <int>}`` or None.
    """
    if not effort:
        return None
    budget = _EFFORT_BUDGETS.get(str(effort).lower(), 4_096)
    ceiling = (max_tokens or 0) - 1    # budget must be < max_tokens
    if ceiling < 1_024:
        return None
    budget = max(1_024, min(budget, ceiling))
    if budget >= (max_tokens or 0):
        return None
    return {"type": "enabled", "budget_tokens": budget}


class AnthropicCompatClient(ChatClientAdapter):
    """基于 anthropic SDK 的 Messages API 客户端。"""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: Optional[str] = None,
        model: str = "claude-3-5-sonnet-latest",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
        extra_headers: Optional[dict] = None,
        http_client: Any = None,
        async_http_client: Any = None,
        max_retries: Optional[int] = None,
        tool_choice: Any = None,
        effort: Optional[str] = None,
    ):
        self.model = model
        self._temperature = temperature
        # Anthropic 的 max_tokens 是**必填**参数；缺省给一个合理下限，
        # 避免远端直接 400。
        self._max_tokens = max_tokens or 4096
        self._timeout = timeout
        self._extra_headers = extra_headers or {}
        # tool_choice / effort 都是**可选**能力：默认 None 时不进请求体，
        # 现有调用方的请求形状完全不变。
        self._tool_choice = tool_choice
        self._effort = effort

        from anthropic import Anthropic, AsyncAnthropic  # 延迟导入
        # SDK 两端要求的 httpx 类型不同：同步端 httpx.Client，异步端 httpx.AsyncClient
        sync_common: dict[str, Any] = {
            "api_key": api_key,
            "base_url": base_url,
            "timeout": timeout,
            "default_headers": self._extra_headers or None,
        }
        async_common: dict[str, Any] = dict(sync_common)
        if http_client is not None:
            sync_common["http_client"] = http_client
        if async_http_client is not None:
            async_common["http_client"] = async_http_client
        if max_retries is not None:
            # SDK 默认 max_retries=2；调用方要自己做"流创建重试 + retry 事件"
            # 时显式传 0 快失败，避免两层重试叠加。
            sync_common["max_retries"] = max_retries
            async_common["max_retries"] = max_retries
        self._client = Anthropic(**sync_common)
        self._async_client = AsyncAnthropic(**async_common)

    def _apply_thinking(self, params: dict[str, Any], effort: Optional[str] = None) -> None:
        """按 effort 档位请求扩展思考（两处调用：invoke / stream）。"""
        thinking = effort_thinking_budget(effort or self._effort, params.get("max_tokens"))
        if thinking is not None:
            params["thinking"] = thinking

    # ── 消息转换 ──

    @staticmethod
    def _split_system(messages: list[Any]) -> tuple[str, list[dict]]:
        """Anthropic 要求 system 单独传参，且 messages 里不能有 system。

        把连续的 system 合并成一个字符串，其余消息按 Anthropic 结构转换。
        """
        system_parts: list[str] = []
        out: list[dict] = []

        for m in messages:
            if hasattr(m, "to_dict") and callable(m.to_dict):
                d = m.to_dict()
            elif isinstance(m, dict):
                d = m
            else:
                d = {"role": getattr(m, "role", "user"),
                     "content": getattr(m, "content", "")}

            role = d.get("role", "user")
            content = d.get("content", "")

            if role == "system":
                if isinstance(content, str):
                    system_parts.append(content)
                elif isinstance(content, list):
                    system_parts.append("\n".join(
                        p.get("text", "") for p in content
                        if isinstance(p, dict)
                    ))
                continue

            # 工具结果 → Anthropic 的 tool_result 内容块
            if role == "tool":
                out.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": d.get("tool_call_id") or "",
                        "content": str(content or ""),
                    }],
                })
                continue

            # assistant 的 tool_calls → tool_use 内容块
            tool_calls = d.get("tool_calls") or []
            if role == "assistant" and tool_calls:
                blocks: list[dict] = []
                if content:
                    blocks.append({"type": "text", "text": str(content)})
                for tc in tool_calls:
                    fn = tc.get("function") or {}
                    raw_args = fn.get("arguments") or "{}"
                    try:
                        parsed = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except (TypeError, ValueError):
                        parsed = {}
                    blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id") or "",
                        "name": fn.get("name") or "",
                        "input": parsed,
                    })
                out.append({"role": "assistant", "content": blocks})
                continue

            # 普通消息：多模态 content 数组需要转成 Anthropic 结构
            if isinstance(content, list):
                blocks = []
                for p in content:
                    if not isinstance(p, dict):
                        continue
                    ptype = p.get("type")
                    if ptype == "text":
                        blocks.append({"type": "text", "text": p.get("text", "")})
                    elif ptype == "image_url":
                        image = p.get("image_url") or {}
                        # Files API 预上传的图：按 id 引用（对话协议约定
                        # {"image_url": {"file_id": ...}}，与 responses 转换器一致）
                        if image.get("file_id"):
                            blocks.append({
                                "type": "image",
                                "source": {"type": "file",
                                           "file_id": image["file_id"]},
                            })
                            continue
                        url = image.get("url", "")
                        if url.startswith("data:"):
                            # data:<media>;base64,<payload>
                            try:
                                header, b64 = url.split(",", 1)
                                media = header.split(":", 1)[1].split(";", 1)[0]
                            except (ValueError, IndexError):
                                media, b64 = "image/png", ""
                            blocks.append({
                                "type": "image",
                                "source": {"type": "base64",
                                           "media_type": media or "image/png",
                                           "data": b64},
                            })
                        elif url:
                            blocks.append({
                                "type": "image",
                                "source": {"type": "url", "url": url},
                            })
                out.append({"role": role, "content": blocks or ""})
                continue

            out.append({"role": role, "content": str(content or "")})

        return "\n\n".join(p for p in system_parts if p), _merge_alternating(out)

    @staticmethod
    def _tools_to_anthropic(tools: Optional[list[dict]]) -> list[dict]:
        """harness 扁平工具 schema → Anthropic tools 结构。"""
        if not tools:
            return []
        out = []
        for t in tools:
            out.append({
                "name": t.get("name") or "",
                "description": t.get("description") or "",
                "input_schema": t.get("parameters") or {"type": "object", "properties": {}},
            })
        return out

    def invoke(
        self,
        messages: list[Any],
        tools: Optional[list[dict]] = None,
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> ChatResponse:
        system, msgs = self._split_system(messages)
        params: dict[str, Any] = {
            "model": self.model,
            "messages": msgs,
            "max_tokens": max_tokens or self._max_tokens,
        }
        if system:
            params["system"] = system
        anth_tools = self._tools_to_anthropic(tools)
        if anth_tools:
            params["tools"] = anth_tools
            if self._tool_choice is not None:
                params["tool_choice"] = self._tool_choice
        if temperature is not None:
            params["temperature"] = temperature
        elif self._temperature is not None:
            params["temperature"] = self._temperature
        self._apply_thinking(params)

        resp = self._client.messages.create(**params)
        return self._to_response(resp)

    @staticmethod
    def _to_response(resp: Any) -> ChatResponse:
        content_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in getattr(resp, "content", None) or []:
            btype = getattr(block, "type", "")
            if btype == "text":
                content_parts.append(getattr(block, "text", "") or "")
            elif btype == "tool_use":
                tool_calls.append(ToolCall(
                    id=getattr(block, "id", "") or "",
                    name=getattr(block, "name", "") or "",
                    arguments=dict(getattr(block, "input", None) or {}),
                ))
            elif btype == "thinking":
                # 扩展思考块 → reasoning
                pass

        usage_obj = getattr(resp, "usage", None)
        usage = {}
        if usage_obj is not None:
            usage = {
                "prompt_tokens": getattr(usage_obj, "input_tokens", 0),
                "completion_tokens": getattr(usage_obj, "output_tokens", 0),
            }

        stop = getattr(resp, "stop_reason", None)
        finish = "tool_calls" if stop == "tool_use" else "stop"

        # Anthropic 的 thinking 块单独提取为 reasoning_content
        reasoning = ""
        for block in getattr(resp, "content", None) or []:
            if getattr(block, "type", "") == "thinking":
                reasoning += getattr(block, "thinking", "") or ""

        return ChatResponse(
            content="".join(content_parts),
            tool_calls=tool_calls,
            usage=usage,
            model=getattr(resp, "model", None),
            finish_reason=finish,
            reasoning_content=reasoning or None,
        )

    # ── 流式 ──

    async def stream(
        self,
        messages: list[Any],
        tools: Optional[list[dict]] = None,
        **kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        system, msgs = self._split_system(messages)
        params: dict[str, Any] = {
            "model": self.model,
            "messages": msgs,
            "max_tokens": kwargs.get("max_tokens") or self._max_tokens,
        }
        if system:
            params["system"] = system
        anth_tools = self._tools_to_anthropic(tools)
        if anth_tools:
            params["tools"] = anth_tools
            if self._tool_choice is not None:
                params["tool_choice"] = self._tool_choice
        if kwargs.get("temperature") is not None:
            params["temperature"] = kwargs["temperature"]
        elif self._temperature is not None:
            params["temperature"] = self._temperature
        self._apply_thinking(params, effort=kwargs.get("effort"))

        # Anthropic 的 tool_use 参数是**增量 JSON 字符串**（input_json_delta），
        # 需要在块级别累积后按 index 输出片段，交给 AgentLoop 拼接。
        block_index = 0
        stop_reason: Optional[str] = None
        async with self._async_client.messages.stream(**params) as stream:
            async for event in stream:
                etype = getattr(event, "type", "")

                if etype == "content_block_start":
                    block = getattr(event, "content_block", None)
                    if block is not None and getattr(block, "type", "") == "tool_use":
                        block_index = getattr(event, "index", 0) or 0
                        yield {"tool_calls": [{
                            "index": block_index,
                            "id": getattr(block, "id", "") or "",
                            "name": getattr(block, "name", "") or "",
                            "arguments": "",
                        }]}
                    elif block is not None and getattr(block, "type", "") == "thinking":
                        pass

                elif etype == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    dtype = getattr(delta, "type", "")
                    if dtype == "text_delta":
                        text = getattr(delta, "text", "")
                        if text:
                            yield text
                    elif dtype == "thinking_delta":
                        thinking = getattr(delta, "thinking", "")
                        if thinking:
                            yield {"reasoning": thinking}
                    elif dtype == "input_json_delta":
                        partial = getattr(delta, "partial_json", "")
                        if partial:
                            yield {"tool_calls": [{
                                "index": getattr(event, "index", 0) or 0,
                                "id": "",
                                "name": "",
                                "arguments": partial,
                            }]}

                elif etype == "message_delta":
                    stop_reason = (getattr(getattr(event, "delta", None), "stop_reason", None)
                                   or stop_reason)
                    usage = getattr(event, "usage", None)
                    if usage is not None:
                        yield {"usage": {
                            "completion_tokens": getattr(usage, "output_tokens", 0),
                        }}

                elif etype == "message_stop":
                    break
        # 终态事件：max_tokens 截断透出为 'length'，让上层区分截断与正常收尾

        # 终态事件：max_tokens 截断透出为 'length'，让上层区分截断与正常收尾
        yield {"finish": "length" if stop_reason == "max_tokens"
               else (stop_reason or "stop")}


def _merge_alternating(messages: list[dict]) -> list[dict]:
    """Merge consecutive same-role messages; the API requires alternation.

    Tool results arrive as their own user entries and injected blocks
    (<subagent_updates> and friends) arrive as user messages too, so a
    tool round ends with two adjacent user messages.  Merging keeps the
    tool_result blocks first inside the combined user message (the API
    requires them at the front) and joins text blocks in order.
    """
    merged: list[dict] = []
    # empty messages are rejected by the api: an assistant turn that produced
    # only tool calls arrives with empty text and must not survive as its own
    # (empty) entry, where it would also block the adjacent merge
    entries = [entry for entry in messages
               if entry.get("content") not in ('', None, [])]
    for entry in entries:
        if (merged and merged[-1].get("role") == entry.get("role")
                and entry.get("role") in ("user", "assistant")):
            previous = merged[-1]["content"]
            current = entry["content"]
            prev_blocks = (previous if isinstance(previous, list) else
                           ([{"type": "text", "text": previous}]
                            if previous else []))
            cur_blocks = (current if isinstance(current, list) else
                          ([{"type": "text", "text": current}]
                           if current else []))
            tool_results = [b for b in cur_blocks
                            if isinstance(b, dict)
                            and b.get("type") == "tool_result"]
            others = [b for b in cur_blocks
                      if not (isinstance(b, dict)
                              and b.get("type") == "tool_result")]
            merged[-1]["content"] = tool_results + prev_blocks + others
            continue
        merged.append(entry)
    return merged
