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
import time
from collections.abc import AsyncGenerator
from typing import Any, Callable

import requests

from .base import (
    ChatClientAdapter,
    ChatMessage,
    ChatResponse,
    IEmbeddingClient,
    ToolCall,
    content_shape,
    count_image_parts,
    local_http_session,
)

logger = logging.getLogger("LocalOpenAIChat")

#: 连接级瞬时故障的重试次数（仅用于「尚未产出任何字节」的请求）。
#:
#: 背景：llama-server / Strata 在空闲或长请求之间会主动关闭 keep-alive 连接，
#: 而 requests 的默认连接池会继续复用那条已被对端关闭的 socket，于是下一次
#: POST 在 conn.getresponse() 处直接抛 RemoteDisconnected，被包成
#: requests.ConnectionError: "Connection aborted / Remote end closed
#: connection without response"。它既不是模型错误也不是参数错误，重发即可。
#:
#: 之所以必须限制在「尚未产出任何字节」，是因为 chat/completions 不幂等：
#: 一旦已经收到并转发了部分 SSE 增量，重发会让前端看到重复内容。而连接在
#: 握手阶段就被拒绝时，上游不可能已经开始生成，重发是安全的。
DEFAULT_STREAM_RETRIES = 2

#: 重试前的退避基数（秒），按尝试次数线性放大。
_RETRY_BACKOFF_BASE = 0.25

#: 判定为「可安全重发」的异常类型。
_RETRYABLE_EXCEPTIONS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.ChunkedEncodingError,
    requests.exceptions.ContentDecodingError,
)

#: 连接级错误的文案特征（urllib3 的 ProtocolError 会被包进 ConnectionError）。
_RETRYABLE_HINTS = (
    "remote end closed connection",
    "connection aborted",
    "connection reset",
    "connection refused",
    "remotedisconnected",
    "protocolerror",
    "broken pipe",
)


def _is_retryable_connection_error(exc: BaseException) -> bool:
    """判断异常是否为「连接级瞬时故障」，可以安全重发。

    只认连接/传输层异常，且必须命中已知的断开特征 —— 刻意不把
    requests.Timeout 算进来：本地推理超时通常意味着模型真的在长时间生成，
    重发只会更慢，而且可能叠加成两次生成。
    """
    if isinstance(exc, _RETRYABLE_EXCEPTIONS):
        return True
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(hint in text for hint in _RETRYABLE_HINTS)


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
        on_status: "Callable[[str, dict], None] | None" = None,
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
        #: 引擎状态回调（loading/loaded/failed/unloaded）。
        #:
        #: 请求时发现引擎未就绪会**自行拉起**，这条路不经过
        #: ModelOrchestrator.load_model()，因此必须靠这个回调把状态同步给
        #: 调度器与 SSE 订阅者 —— 否则模型列表/显存页会一直显示"未加载"。
        self._on_status = on_status
        #: 保证并发请求只拉起一次引擎
        self._launch_lock = threading.Lock()
        self.last_usage = None
        # 最近一次流式/非流式返回的 timings（llama-server / Strata 都提供 timings）
        self.last_timings = None
        self.last_model = self.model
        # 走忽略代理的会话：本地引擎在 127.0.0.1，绝不能被 ALL_PROXY 接管
        self._http_session = local_http_session()

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

    def _notify_engine_status(self, status: str, **extra: Any) -> None:
        """向编排器上报引擎状态（无回调时静默）。"""
        if self._on_status is None:
            return
        try:
            self._on_status(status, **extra)
        except Exception:  # noqa: BLE001 - 状态上报失败不能影响推理
            logger.debug("引擎状态回调失败: %s %s", self.label, status, exc_info=True)

    def _ensure_launcher_running(self) -> None:
        """如果绑定了 launcher 且未就绪，自动拉起。

        **阻塞函数**：模型加载可能耗时数十秒到数分钟。异步调用方必须用
        asyncio.to_thread 包起来，否则会把整个事件循环冻住
        （连带所有 SSE 推送与其它请求一起卡死）。

        拉起过程中会上报 loading → loaded/failed，让模型列表与显存调度页
        同步反映真实状态 —— 这是"重试历史消息时后端自动加载了模型，前端
        却仍显示没有可用模型"的根因。
        """
        if self._launcher is None or self._launcher.is_ready():
            return

        # 并发请求可能同时发现引擎未就绪：加锁 + 二次确认，保证只拉起一次
        with self._launch_lock:
            if self._launcher.is_ready():
                return

            logger.info("检测到 %s 引擎未就绪，通过 launcher 启动...", self.label)
            self._notify_engine_status("loading")
            try:
                self._launcher.start(wait_ready=True, timeout=self.timeout)
            except Exception as e:
                logger.error("%s 自动拉起失败: %s", self.label, e)
                self._notify_engine_status("failed", error=str(e))
                raise
            logger.info("%s 已就绪（请求时自动拉起）", self.label)
            self._notify_engine_status("loaded")

    def _discard_pooled_connections(self) -> None:
        """丢弃连接池里的空闲连接，强制下一次请求重建 TCP 连接。

        用于连接级故障后的重试：出问题的那条 socket 已经被对端关闭，
        如果不清掉，重试会从池里捞出同一条死连接，再失败一次。

        只影响**空闲**连接：正在被其它请求持有的连接已从池中取出，
        clear() 不会碰到它们，因此并发中的流不会被这个操作打断。
        """
        try:
            self._http_session.close()
        except Exception:  # noqa: BLE001 - 清理失败不应掩盖原始错误
            logger.debug("清理 %s 连接池失败（忽略）", self.label, exc_info=True)

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

        # ── 多模态终检：这是发往引擎的最后一站 ──
        # 在这里打日志可以直接回答「图片到底有没有上线」。
        # 只有确实涉及多模态（有 image_url 或存在非文本 content）时才记录，
        # 避免给纯文本请求刷屏。
        _imgs = count_image_parts(msgs)
        if _imgs or tools or any(not isinstance(m.get("content"), str) for m in msgs):
            logger.info(
                "%s 上行 payload: messages=%d images=%d tools=%s 形状=%s",
                self.label, len(msgs), _imgs,
                [t.get("name") for t in (tools or [])][:10] if tools else "无",
                [f"{m.get('role')}:{content_shape(m.get('content'))}" for m in msgs],
            )
        else:
            logger.debug("%s 上行 payload(纯文本): messages=%d", self.label, len(msgs))
        return payload

    def _do_http_request(self, payload: dict) -> dict:
        """单次非流式请求，带连接级故障重发。

        非流式请求只有在完整拿到响应体后才算成功，因此连接阶段失败时
        重发不会产生重复结果（没有半个响应可言）。
        """
        url = f"{self.base_url}/v1/chat/completions"
        attempts = max(1, DEFAULT_STREAM_RETRIES + 1)
        last_exc: BaseException | None = None

        for attempt in range(attempts):
            self._ensure_launcher_running()
            try:
                resp = self._http_session.post(
                    url,
                    headers=self._headers(),
                    json=payload,
                    timeout=self.timeout,
                )
            except Exception as exc:  # noqa: BLE001 - 判定后决定是否重发
                if attempt + 1 >= attempts or not _is_retryable_connection_error(exc):
                    raise
                last_exc = exc
                self._discard_pooled_connections()
                backoff = _RETRY_BACKOFF_BASE * (attempt + 1)
                logger.warning(
                    "%s 非流式请求连接中断（%s: %s），%.2fs 后重发 %d/%d",
                    self.label, type(exc).__name__, exc, backoff,
                    attempt + 1, DEFAULT_STREAM_RETRIES,
                )
                time.sleep(backoff)
                continue
            break
        else:  # pragma: no cover - 循环内必然 break 或 raise
            if last_exc is not None:
                raise last_exc
            raise RuntimeError(f"{self.label} 请求失败")

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
        """SSE 流式交互生成器。

        在「本次请求尚未产出任何增量」的前提下，对连接级瞬时故障自动重发
        （见 DEFAULT_STREAM_RETRIES 的说明）。一旦已经 yield 过内容就不再
        重试 —— 重发会让前端看到重复的思考/回答。
        """
        payload = self._build_payload(
            messages, tools,
            temperature=kwargs.get("temperature"),
            max_tokens=kwargs.get("max_tokens"),
            stream=True,
        )

        retries = int(kwargs.get("retries", DEFAULT_STREAM_RETRIES) or 0)
        attempts = max(1, retries + 1)
        last_exc: BaseException | None = None

        for attempt in range(attempts):
            produced = False
            try:
                async for item in self._stream_once(payload):
                    produced = True
                    yield item
                return
            except Exception as exc:  # noqa: BLE001 - 判定后决定是否重发
                if (
                    produced
                    or attempt + 1 >= attempts
                    or not _is_retryable_connection_error(exc)
                ):
                    raise
                last_exc = exc
                self._discard_pooled_connections()
                backoff = _RETRY_BACKOFF_BASE * (attempt + 1)
                logger.warning(
                    "%s 连接在握手阶段中断（%s: %s），%.2fs 后重发 %d/%d",
                    self.label, type(exc).__name__, exc, backoff,
                    attempt + 1, retries,
                )
                await asyncio.sleep(backoff)
                # 上游可能刚好在这段时间里退出，重发前再确认一次引擎在线。
                # 放线程里：拉起模型是阻塞操作，不能冻住事件循环。
                await asyncio.to_thread(self._ensure_launcher_running)

        if last_exc is not None:  # pragma: no cover - 循环内必然 return 或 raise
            raise last_exc

    async def _stream_once(self, payload: dict) -> AsyncGenerator[Any, None]:
        """单次 SSE 请求：建连、读流、解析增量。不做重试。"""
        # 自动拉起引擎是阻塞操作（可能数十秒），必须离开事件循环，
        # 否则整台服务器（含所有 SSE 推送）都会被冻住。
        await asyncio.to_thread(self._ensure_launcher_running)

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
        self._session = local_http_session()

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
