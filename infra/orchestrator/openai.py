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
        max_retries: Optional[int] = None,
        extra_headers: Optional[dict] = None,
        protocol: str = "chat",
        tool_choice: Any = "auto",
        send_tool_choice: bool = True,
        send_usage_in_stream: bool = True,
        http_client: Any = None,
        async_http_client: Any = None,
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
        #: SDK 默认 max_retries=2 —— 超时会被重试，单次 8s 超时变成 24s。
        #: 对话链路要"快失败"，默认降到 1。
        self._max_retries = max_retries if max_retries is not None else 1

        from openai import AsyncOpenAI, OpenAI  # 延迟导入，避免未安装时影响其他模块
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=self._max_retries,
            default_headers=self._extra_headers or None,
            # SOCKS 代理等场景由调用方构造好 httpx 客户端整体注入（infra.net）。
            # SDK 两端要求的类型不同：同步端 httpx.Client，异步端 httpx.AsyncClient。
            http_client=http_client,
        )
        self._async_client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=self._max_retries,
            default_headers=self._extra_headers or None,
            http_client=async_http_client,
        )

    def set_timeout(self, timeout: Optional[float]) -> None:
        """动态调整请求超时（秒）。

        对讲机场景需要"快失败"：语音轮用更短的超时，provider 卡住时
        及时报错，而不是让用户干等一分钟。
        """
        self._timeout = timeout
        for cli in (getattr(self, "_client", None),
                    getattr(self, "_async_client", None)):
            if cli is not None:
                try:
                    cli.timeout = timeout
                except Exception:   # noqa: BLE001
                    pass

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
        extra_body: Optional[dict] = None,
        max_retries: Optional[int] = None,
    ) -> ChatResponse:
        """调一次模型。

        `extra_body` 是**厂商私有字段的正规通道**（OpenAI SDK 的同名参数）：
        例如 llama.cpp 的 `chat_template_kwargs={"enable_thinking": false}`
        —— 不关掉的话，Qwen3 会把 max_tokens 全花在 thinking 上，
        返回的 content 是**空的**（实测踩过）。
        不传就完全不进请求体，其他网关不受影响。
        """
        if self.protocol == "responses":
            return self._invoke_responses(messages, tools, temperature=temperature,
                                          max_tokens=max_tokens, timeout=timeout)
        msgs = self._to_message_dicts(messages)
        # 【诊断】这次调用有多大 —— provider 账单里出现 18k~26k token 的
        # 请求且答案只有十几个字，说明某个后台调用把整段历史塞进了 prompt。
        try:
            _chars = sum(len(str(m.get("content") or "")) for m in msgs)
            if _chars > 4000:
                logger.info("[LLM大请求] model=%s msgs=%d 总字符=%d",
                            self.model, len(msgs), _chars)
        except Exception:   # noqa: BLE001
            pass
        kwargs: dict[str, Any] = {"model": self.model, "messages": msgs}
        self._apply_tools(kwargs, tools)
        self._apply_sampling(kwargs, temperature=temperature, max_tokens=max_tokens)

        if extra_body:
            kwargs["extra_body"] = dict(extra_body)
        if max_retries is not None:
            kwargs["max_retries"] = max_retries
        resp = self._client.chat.completions.create(**kwargs)
        if not hasattr(resp, "choices"):
            # 有些网关**无视 stream=false，强制返回 SSE**（实测：newapi.gay）。
            # openai SDK 这时给回来的是原始字符串而不是 Completion 对象，
            # 直接 _to_response 会炸：'str' object has no attribute 'choices'。
            #
            # 这条路径影响面不小：教师链路（harness/learning/teacher.py 走 invoke）、
            # 任何非流式的远端调用都会挂。网关是别人的，我们改不了——
            # 只能在自己这边兜住：退回流式调用，把增量拼成一次普通响应。
            logger.debug("网关返回的不是 JSON 响应，退回流式聚合")
            return self._invoke_by_stream(kwargs)
        return self._to_response(resp)

    def _invoke_by_stream(self, params: dict[str, Any]) -> ChatResponse:
        """用流式请求拼出一次普通的非流式响应。

        给「强制 SSE 的网关」用：对调用方来说仍然是一次普通的 invoke。
        """
        stream_params = {**params, "stream": True}
        if self._send_usage_in_stream:
            stream_params.setdefault("stream_options", {"include_usage": True})

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_acc: dict[int, dict[str, Any]] = {}
        usage: dict[str, Any] = {}
        finish: Optional[str] = None

        with self._client.chat.completions.create(**stream_params) as stream:
            for chunk in stream:
                if getattr(chunk, "usage", None) is not None:
                    usage = _plain(chunk.usage)
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                choice = choices[0]
                finish = getattr(choice, "finish_reason", None) or finish
                delta = getattr(choice, "delta", None)
                if delta is None:
                    continue
                if getattr(delta, "content", None):
                    content_parts.append(delta.content)
                if getattr(delta, "reasoning_content", None):
                    reasoning_parts.append(delta.reasoning_content)
                for tc in (getattr(delta, "tool_calls", None) or []):
                    idx = getattr(tc, "index", 0) or 0
                    slot = tool_acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if getattr(tc, "id", None):
                        slot["id"] = tc.id
                    fn = getattr(tc, "function", None)
                    if fn is not None:
                        if getattr(fn, "name", None):
                            slot["name"] = fn.name
                        if getattr(fn, "arguments", None):
                            slot["arguments"] += fn.arguments

        tool_calls: list[ToolCall] = []
        for idx, slot in sorted(tool_acc.items()):
            raw_args = slot["arguments"] or ""
            try:
                arguments = json.loads(raw_args) if raw_args else {}
            except json.JSONDecodeError:
                # 网关把参数切碎了或截断了：宁可给空参，也不要把半个 JSON 传下去
                arguments = {}
            tool_calls.append(
                ToolCall(id=slot["id"] or f"call_{idx}", name=slot["name"], arguments=arguments)
            )

        return ChatResponse(
            content="".join(content_parts),
            tool_calls=tool_calls,
            usage=usage,
            model=params.get("model"),
            finish_reason=finish,
            reasoning_content="".join(reasoning_parts) or None,
        )

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
    def _responses_content_parts(content: Any, role: str) -> list[dict]:
        """把 OpenAI **对话协议**的 content parts 转成 Responses 协议的内容块。

        两种协议的图片块形状不一样，不能原样透传：
          对话协议：{"type": "image_url", "image_url": {"url": <url>}}
          Responses：{"type": "input_image", "image_url": <url>}   ← image_url 是**字符串**
        原样透传 → 网关 400（"Invalid type for 'input_image'"）。
        文本块同理：对话协议的 {"type": "text"} → input_text（助手消息用 output_text）。

        图片引用也可以携带 **file_id**（Files API 预上传）而不是 url：
          对话协议约定：{"type": "image_url", "image_url": {"file_id": <id>}}
          Responses：{"type": "input_image", "file_id": <id>, "detail": "auto"}
        """
        text_type = "output_text" if role == "assistant" else "input_text"
        parts: list[dict] = []
        for part in content:
            if isinstance(part, str):
                parts.append({"type": text_type, "text": part})
                continue
            if not isinstance(part, dict):
                continue
            ptype = part.get("type", "")
            if ptype in ("text", "input_text", "output_text"):
                text = part.get("text", "")
                # 已经是 Responses 形状的（input_text/output_text）保持原样
                parts.append({"type": ptype if ptype != "text" else text_type,
                              "text": text})
            elif ptype in ("image_url", "input_image"):
                image = part.get("image_url", "")
                if isinstance(image, dict):
                    file_id = image.get("file_id", "")
                    if file_id:
                        # Files API 预上传的图：按 id 引用，请求体里不带 base64
                        parts.append({"type": "input_image", "file_id": file_id,
                                      "detail": "auto"})
                        continue
                    url = image.get("url", "")
                else:
                    url = image
                if not url:
                    continue
                parts.append({"type": "input_image", "image_url": url,
                              "detail": "auto"})
            else:
                # 未知块：能当文本就当文本，总比把非法形状塞给网关强
                text = part.get("text")
                if text is None:
                    continue
                parts.append({"type": text_type, "text": text})
        return parts

    @staticmethod
    def _messages_to_responses_input(messages: list[Any]) -> list[dict]:
        """把 ChatMessage 列表转成 Responses API 的 input items。"""
        items: list[dict] = []
        for m in messages:
            if isinstance(m, dict):
                # dict 消息与 ChatMessage 走同一套翻译：tool 轮在这里是
                # function_call / function_call_output items，不是 chat 形状。
                # 原样透传一条 {"role": "tool"}，模型就找不到能与自己调用
                # 配对的结果，从此不再从工具结果里学习。
                items.extend(OpenAICompatClient._dict_to_responses_items(m))
                continue
            role = getattr(m, "role", "")
            content = getattr(m, "content", "") or ""
            parts = None
            if isinstance(content, (list, tuple)):
                # 多模态消息：content 是**内容块列表**。
                # 过去整个列表被塞进 {"type":"input_text","text": <list>} ——
                # text 必须是字符串，形状非法，网关直接 400；而且图片块被
                # 丢掉，模型根本看不见图。现在按 Responses 协议逐块转换。
                if role == "tool":
                    # 工具输出在 Responses 协议里是**字符串**，不是内容块列表
                    items.append({
                        "type": "function_call_output",
                        "call_id": getattr(m, "tool_call_id", "") or "",
                        "output": "\n".join(
                            str(p.get("text", "")) for p in content
                            if isinstance(p, dict)),
                    })
                    continue
                if role not in ("system", "user", "assistant"):
                    continue
                parts = OpenAICompatClient._responses_content_parts(content, role)
            if role == "system":
                items.append({"role": "system",
                              "content": parts if parts is not None
                              else [{"type": "input_text", "text": content}]})
            elif role == "user":
                items.append({"role": "user",
                              "content": parts if parts is not None
                              else [{"type": "input_text", "text": content}]})
            elif role == "assistant":
                text = content
                if not text and getattr(m, "reasoning_content", ""):
                    # 这条 wire 没有 reasoning 字段：只带推理的轮次把推理
                    # 当作正文携带，否则整条消息等于什么都没说。
                    text = str(getattr(m, "reasoning_content", ""))
                if parts is not None or text:
                    # 只有 tool_calls 的轮次不附带空的 output_text 块
                    items.append({"role": "assistant",
                                  "content": parts if parts is not None
                                  else [{"type": "output_text", "text": text}]})
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
    def _dict_to_responses_items(m: dict) -> list[dict]:
        """Translate one chat-shaped dict into Responses input items.

        Plain dicts take exactly the ChatMessage route: a tool result becomes
        a ``function_call_output`` item and an assistant turn's tool calls
        become ``function_call`` items.  ``reasoning_content`` is dropped on
        purpose (a chat-completions field this endpoint rejects); an
        assistant turn that carries only reasoning carries it as its text,
        because a turn that says nothing is a turn the model cannot read.
        """
        role = str(m.get("role") or "user")
        if role not in ("system", "user", "assistant", "tool"):
            return []
        content = m.get("content")
        reasoning = m.get("reasoning_content")
        if role == "tool":
            if isinstance(content, str):
                output = content
            elif isinstance(content, (list, tuple)):
                output = "\n".join(str(p.get("text", "")) for p in content
                                   if isinstance(p, dict))
            else:
                output = str(content or "")
            return [{"type": "function_call_output",
                     "call_id": str(m.get("tool_call_id") or ""),
                     "output": output}]
        text = content if isinstance(content, str) else ""
        if role == "assistant" and not text and reasoning:
            text = str(reasoning)
        items: list[dict] = []
        if isinstance(content, (list, tuple)):
            items.append({"role": role,
                          "content": OpenAICompatClient._responses_content_parts(
                              list(content), role)})
        elif text:
            text_type = "output_text" if role == "assistant" else "input_text"
            items.append({"role": role,
                          "content": [{"type": text_type, "text": text}]})
        if role == "assistant":
            for tc in (m.get("tool_calls") or []):
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function") or {}
                arguments = fn.get("arguments", "{}")
                if not isinstance(arguments, str):
                    arguments = json.dumps(arguments, ensure_ascii=False)
                items.append({
                    "type": "function_call",
                    "call_id": str(tc.get("id") or ""),
                    "name": str(fn.get("name") or ""),
                    "arguments": arguments,
                })
        return items

    def list_models(self) -> list[str]:
        """The model ids this endpoint exposes (``GET /models``)."""
        page = self._client.models.list()
        data = getattr(page, "data", page) or []
        ids: list[str] = []
        for item in data:
            model_id = getattr(item, "id", None) or (
                item.get("id") if isinstance(item, dict) else None)
            if model_id:
                ids.append(str(model_id))
        return sorted(dict.fromkeys(ids))

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
            # 推理档位：仅当调用方显式传入才会出现在请求体里（老网关不受影响）
            "reasoning_effort",
            # SDK 级参数：把厂商私有字段合并进请求体（如 toggle 式思考开关），
            # 不会作为独立字段出现在 wire 上
            "extra_body",
        }
        for key, value in kwargs.items():
            if value is not None and key in _STANDARD_STREAM_PARAMS:
                params[key] = value

        # 显式要求远端回传用量：多数 OpenAI 兼容网关在 stream=True 时默认
        # 不下发 usage，不请求的话终态用量恒为 0，前端用量环/计费显示全空。
        if self._send_usage_in_stream:
            params.setdefault("stream_options", {"include_usage": True})

        try:
            stream = await self._async_client.chat.completions.create(**params)
        except Exception as error:    # noqa: BLE001 - narrow the retry below
            # Several OpenAI-compatible servers reject stream_options with a
            # 400; retry once without it before giving up.
            status = int(getattr(error, "status_code", 0)
                         or getattr(error, "status", 0) or 0)
            if status != 400 or "stream_options" not in params:
                raise
            params.pop("stream_options", None)
            stream = await self._async_client.chat.completions.create(**params)
        finish: Optional[str] = None
        async for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                yield {"usage": _plain(usage)}
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            finish = getattr(choice, "finish_reason", None) or finish
            delta = choice.delta
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
        # 终态事件：流正常结束但没有 finish_reason（断连/代理截断）时按
        # 'incomplete' 透出，让上层把可能被截断的回复当未完成处理。
        yield {"finish": finish or "incomplete"}

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
        # 推理档位与提示缓存键：Responses 协议的原生字段，仅调用方显式
        # 传入时才出现。reasoning 形如 {"effort": "high", "summary": "auto"}；
        # prompt_cache_key 由上层用稳定前缀指纹填充（命中则省前缀重复计费）。
        if kwargs.get("reasoning") is not None:
            params["reasoning"] = kwargs["reasoning"]
        if kwargs.get("prompt_cache_key"):
            params["prompt_cache_key"] = kwargs["prompt_cache_key"]

        # output_index -> {id, name}（function_call 元信息来自 output_item.added）
        call_meta: dict[int, dict] = {}
        finish: Optional[str] = None
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
                    response = getattr(event, "response", None)
                    usage = getattr(response, "usage", None)
                    if usage:
                        yield {"usage": _plain(usage)}
                    status = str(getattr(response, "status", "") or "")
                    if status == "completed":
                        finish = "stop"
                    else:
                        details = getattr(response, "incomplete_details", None)
                        reason = str(getattr(details, "reason", "") or "")
                        finish = "length" if reason == "max_output_tokens" else "incomplete"
        if finish is not None:
            yield {"finish": finish}

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
