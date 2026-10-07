# harness/orchestrator/local_chat.py
# 本地推理引擎的 OpenAI 兼容对话 / 嵌入客户端基类。
#
# llama-server 与 Strata 的 serve/server.py 都对外提供同一套 OpenAI 兼容协议：
#
#     POST /v1/chat/completions   （SSE 流式 + reasoning_content + tool_calls）
#     POST /v1/embeddings         （Strata 暂不支持，见 strata.py 的说明）
#     GET  /health, /props, /v1/models
#
# 因此客户端逻辑只需要实现一次。各引擎的差异只有：
#
#   * base_url / model_name；
#   * 绑定的 launcher（未就绪时自动拉起）；
#   * 是否支持向量端点。
#
# 本模块把原先只服务于 llama.cpp 的实现提升为通用基类，llamacpp.py 与
# strata.py 各自薄薄地继承一层。

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import AsyncGenerator
from typing import Any

import requests

from .base import (
    ChatClientAdapter,
    ChatMessage,
    ChatResponse,
    IEmbeddingClient,
    ToolCall,
)

logger = logging.getLogger("LocalOpenAIChat")


class OpenAICompatChat(ChatClientAdapter):
    """任何「本地 OpenAI 兼容推理服务」的对话客户端。

    完全符合 IChatClient 契约，支持：
      - /v1/chat/completions 协议
      - DeepSeek reasoning 思考链提取（<think> 标签与 reasoning_content 字段）
      - SSE 流式推送增量与 Tool Call 解析
      - ModelScheduler 显存管理联动
      - 可选关联 launcher，未就绪时自动拉起
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        model_name: str | None = None,
        timeout: float = 300.0,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        api_key: str | None = None,
        scheduler: Any | None = None,
        launcher: Any | None = None,
        label: str = "本地推理服务",
    ):
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name or "local-model"
        self.model: str = self.model_name
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.api_key = api_key
        self.label = label
        self._scheduler = scheduler
        self._launcher = launcher
        self.last_usage = None
        # 最近一次流式/非流式返回的 timings（llama-server / Strata 都提供 timings）
        self.last_timings = None
        self.last_model = self.model
        self._http_session = requests.Session()

    # ── HTTP 基础 ──

    def _headers(self) -> dict[str, str]:
        h = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "text/event-stream, application/json",
        }
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _raise_for_status(self, resp) -> None:
        """带响应体上下文的 raise_for_status。

        上游的失败原因（模型不兼容、显存不足、模板错误、参数非法等）
        **只在响应体里**，而 requests 的默认 raise_for_status 会把它丢掉，
        上层只剩下 "500 Server Error" 这种无信息量的报错。
        这里把响应体解析出来拼进异常消息，让日志能直接看出根因。
        """
        if resp.status_code < 400:
            return
        detail = ""
        try:
            raw = resp.text or ""
        except Exception:  # noqa: BLE001 - 读取 body 失败不应掩盖原始错误
            raw = ""
        if raw:
            # 尝试解析为结构化错误（{"error":{"message":...}}）
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    err = data.get("error")
                    if isinstance(err, dict):
                        detail = str(err.get("message") or err)
                    elif err:
                        detail = str(err)
                    else:
                        detail = str(data.get("message") or raw)
                else:
                    detail = raw
            except (TypeError, ValueError):
                detail = raw
        detail = (detail or "").strip()
        if len(detail) > 2000:
            detail = detail[:2000] + "…[已截断]"

        msg = (
            f"{self.label} 返回 HTTP {resp.status_code}"
            f" ({resp.request.url if resp.request is not None else ''})"
        )
        if detail:
            msg += f"：{detail}"
        logger.error("%s 上游错误: %s", self.label, msg)
        raise RuntimeError(msg)

    def _ensure_launcher_running(self) -> None:
        """如果绑定了 launcher 且未就绪，自动拉起。"""
        if self._launcher is not None and not self._launcher.is_ready():
            logger.info("检测到 %s 引擎未就绪，通过 launcher 启动...", self.label)
            self._launcher.start(wait_ready=True, timeout=self.timeout)

    # ── 消息归一化 ──

    def _normalize_system_messages(self, msgs: list[Any]) -> list[Any]:
        """把多条 system 消息合并为开头的一条。

        严格的 Jinja chat template（Bonsai、部分 Qwen/Llama 官方模板、Strata 的
        Qwen3.8 模板）会直接报错 "System message must be at the beginning."，
        导致上游 500。而应用层出于模块化，可能按段追加多条 system
        （DSN 的记忆注入即如此）。

        这里做最后一道归一化，语义等价（系统内容都是前缀上下文）：
          * 开头的连续 system 合并为一条；
          * 夹在中间的 system 并入开头那条（避免被模板拒绝或静默丢弃）。
        """
        if not isinstance(msgs, list) or not msgs:
            return msgs

        def _content_of(m: Any) -> str:
            c = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
            if isinstance(c, str):
                return c
            if isinstance(c, list):
                return "\n".join(
                    p.get("text", "") for p in c
                    if isinstance(p, dict) and p.get("type") == "text"
                )
            return str(c or "")

        system_texts: list[str] = []
        rest: list[Any] = []
        for m in msgs:
            role = m.get("role") if isinstance(m, dict) else getattr(m, "role", "")
            if role == "system":
                t = _content_of(m)
                if t.strip():
                    system_texts.append(t)
            else:
                rest.append(m)

        if not system_texts:
            # 没有非空 system 内容：若原本没有 system 消息则原样返回，
            # 否则把空 system 全部剔除（严格模板同样不接受空 system）。
            if len(rest) == len(msgs):
                return msgs
            logger.debug("已剔除 %d 条空白 system 消息", len(msgs) - len(rest))
            return rest

        # 只有一条且本来就在开头 → 无需改动
        if len(system_texts) == 1 and len(rest) == len(msgs) - 1:
            first = msgs[0]
            role = first.get("role") if isinstance(first, dict) else getattr(first, "role", "")
            if role == "system":
                return msgs

        merged = "\n\n".join(system_texts)
        if isinstance(msgs[0], dict):
            head: Any = {"role": "system", "content": merged}
        else:
            head = ChatMessage.system(merged)
        logger.debug("已将 %d 条 system 消息合并为 1 条", len(system_texts))
        return [head] + rest

    # ── 非流式 ──

    def _build_payload(
        self,
        messages: list[Any],
        tools: list[dict] | None,
        *,
        temperature: float | None,
        max_tokens: int | None,
        stream: bool,
    ) -> dict:
        msgs = self._normalize_system_messages(self._to_message_dicts(messages))
        payload: dict[str, Any] = {
            "messages": msgs,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
            "stream": stream,
        }
        if self.model_name:
            payload["model"] = self.model_name
        if tools:
            payload["tools"] = [{"type": "function", "function": t} for t in tools]
        return payload

    def _do_http_request(self, payload: dict) -> dict:
        url = f"{self.base_url}/v1/chat/completions"
        self._ensure_launcher_running()
        resp = self._http_session.post(
            url,
            headers=self._headers(),
            json=payload,
            timeout=self.timeout,
        )
        self._raise_for_status(resp)
        data = resp.json()
        self.last_usage = data.get("usage")
        self.last_timings = data.get("timings") or self.last_timings
        self.last_model = data.get("model", self.model_name)
        return data

    def invoke(
        self,
        messages: list[Any],
        tools: list[dict] | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> ChatResponse:
        payload = self._build_payload(
            messages, tools,
            temperature=temperature, max_tokens=max_tokens, stream=False,
        )

        old_to = self.timeout
        if timeout is not None:
            self.timeout = timeout

        try:
            if self._scheduler is not None and self.model_name:
                with self._scheduler.use(self.model_name, timeout=self.timeout):
                    result = self._do_http_request(payload)
            else:
                result = self._do_http_request(payload)
        finally:
            self.timeout = old_to

        choice = (result.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content") or ""
        reasoning_content = message.get("reasoning_content")

        # Strata（以及 llama.cpp 的 --reasoning-format none）在只生成思考时
        # 会把 content 置为 null，思考全在 reasoning_content —— 上面已处理。
        # 这里再兜底 <think> 标签内联的形式。
        if not reasoning_content and "<think>" in content and "</think>" in content:
            start = content.find("<think>") + len("<think>")
            end = content.find("</think>")
            if end > start:
                reasoning_content = content[start:end].strip()
                content = (content[:content.find("<think>")] + content[end + len("</think>"):].strip()).strip()

        tool_calls: list[ToolCall] = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except (TypeError, ValueError):
                args = {}
            tool_calls.append(ToolCall(
                id=tc.get("id", ""),
                name=fn.get("name", ""),
                arguments=args,
            ))

        return ChatResponse(
            content=content,
            tool_calls=tool_calls,
            usage=self.last_usage or {},
            model=self.last_model or self.model,
            finish_reason=choice.get("finish_reason"),
            reasoning_content=reasoning_content,
        )

    # ── 流式 ──

    async def stream(
        self,
        messages: list[Any],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        """SSE 流式交互生成器。"""
        payload = self._build_payload(
            messages, tools,
            temperature=kwargs.get("temperature"),
            max_tokens=kwargs.get("max_tokens"),
            stream=True,
        )

        self._ensure_launcher_running()

        def _request():
            url = f"{self.base_url}/v1/chat/completions"
            return self._http_session.post(
                url,
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
                stream=True,
            )

        loop = asyncio.get_running_loop()
        resp = await loop.run_in_executor(None, _request)
        # 用带响应体上下文的版本替换 raise_for_status：
        # 否则上游 500 的真实原因（显存不足/模板不兼容等）会被丢弃。
        self._raise_for_status(resp)

        q: asyncio.Queue = asyncio.Queue()
        resp.encoding = "utf-8"

        def _reader():
            try:
                for line in resp.iter_lines(decode_unicode=False):
                    if line:
                        text_line = line.decode("utf-8", errors="replace") if isinstance(line, bytes) else line
                        loop.call_soon_threadsafe(q.put_nowait, text_line)
            except Exception as ex:  # noqa: BLE001 - 交给消费侧抛出
                loop.call_soon_threadsafe(q.put_nowait, ex)
            finally:
                loop.call_soon_threadsafe(q.put_nowait, None)

        threading.Thread(target=_reader, daemon=True).start()

        try:
            while True:
                item = await q.get()
                if item is None:
                    break
                if isinstance(item, Exception):
                    raise item

                raw = item
                if not raw or not raw.startswith("data:"):
                    # SSE 注释帧（如 Strata 的 ": keep-alive"）直接跳过
                    continue
                data = raw[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except (TypeError, ValueError):
                    continue

                # timings/usage 可能出现在 choices 为空数组的收尾 chunk 中
                # （或末尾仅带 timings）。必须在过滤 choices 之前提取，
                # 否则用量数据会被静默丢弃，前端上下文指示环永远拿不到 token 数。
                timings = chunk.get("timings")
                if timings:
                    self.last_timings = timings
                    yield {"timings": timings}
                if chunk.get("usage"):
                    self.last_usage = chunk["usage"]
                    yield {"usage": chunk["usage"]}

                if not chunk.get("choices"):
                    continue

                delta = chunk["choices"][0].get("delta") or {}

                # 处理思维链增量输出
                if delta.get("reasoning_content"):
                    yield {"reasoning_content": delta["reasoning_content"]}

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
                            "arguments": fn.get("arguments", "") or "",
                        })
                    if emitted:
                        yield {"tool_calls": emitted}
        finally:
            resp.close()


class OpenAICompatEmbeddingClient(IEmbeddingClient):
    """llama-server / 任何暴露 /v1/embeddings 的本地服务向量客户端。"""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        model_name: str | None = None,
        timeout: float = 60.0,
        api_key: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name or "local-embedding"
        self.timeout = timeout
        self.api_key = api_key
        self._session = requests.Session()

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        url = f"{self.base_url}/v1/embeddings"
        payload = {"input": texts, "model": self.model_name}
        resp = self._session.post(url, headers=self._headers(), json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return [item["embedding"] for item in data.get("data", [])]

    def embed_one(self, text: str) -> list[float]:
        res = self.embed([text])
        return res[0] if res else []
