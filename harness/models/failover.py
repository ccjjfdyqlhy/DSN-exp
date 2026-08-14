# harness/models/failover.py
# FailoverChat — 多端点故障转移客户端（场景无关，从 DSN 广义化移植）。
#
# 问题域：同一服务有多个可互换端点（API 账号 / 镜像 / 本地+云端），
# 调用时按给定顺序逐个尝试，端点抛错自动回退下一个；全部失败才抛出。
#
# 设计：
#   - 实现 IChatClient 契约（invoke/stream），可被 AgentLoop/Provider 直接使用
#   - 端点 = (name, IChatClient) 对；顺序由调用方决定（可接 DynamicRouter 排序）
#   - on_observation 回调把每次真实请求的成功/失败/延迟交给外部学习器
#   - 流式故障转移：流开始前失败可换端点；已产出内容后失败则上抛（无法回滚）

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Callable, Optional

from .base import ChatClientAdapter, ChatResponse, IChatClient

logger = logging.getLogger("FailoverChat")


def _invoke_client(client, messages, tools, *, temperature=None, max_tokens=None,
                   timeout=None) -> ChatResponse:
    """调用端点客户端：优先 IChatClient.invoke；否则回退 dsn 风格有状态客户端。

    有状态客户端（OpenAIChat/LMStudioChat 风格）具备 continue_conversation 与
    messages 属性：先把同一消息集同步到客户端再调用，实现"同状态重试"。
    """
    if hasattr(client, "invoke"):
        return client.invoke(
            messages, tools,
            temperature=temperature, max_tokens=max_tokens, timeout=timeout)
    if hasattr(client, "continue_conversation"):
        if hasattr(client, "messages"):
            client.messages = list(messages)
        reply = client.continue_conversation(tools=tools)
        tool_calls = []
        for tc in (getattr(client, "last_tool_calls", None) or []):
            fn = tc.get("function", {}) if isinstance(tc, dict) else {}
            if isinstance(fn, dict):
                import json
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except (TypeError, ValueError):
                    args = {}
                tool_calls.append({
                    "id": tc.get("id", ""),
                    "name": fn.get("name", ""),
                    "arguments": args,
                })
        from .base import ToolCall
        return ChatResponse(
            content=reply or "",
            tool_calls=[ToolCall(**tc) for tc in tool_calls if tc.get("name")],
            usage=getattr(client, "last_usage", None) or {},
            model=getattr(client, "last_model", None) or getattr(client, "model", ""),
        )
    raise TypeError(
        f"端点客户端 {type(client).__name__} 需实现 invoke 或 continue_conversation")


@dataclass
class FailoverEndpoint:
    """一个可故障转移的端点。"""

    name: str
    client: Any            # IChatClient（duck-typed：需有 invoke/stream）


class FailoverChat(ChatClientAdapter):
    """按顺序尝试多个端点，自动回退。

    invoke()  同步路径：逐端点尝试，返回首个成功响应
    stream()  流式路径：逐端点尝试流；仅在未产出内容前失败才换端点
    """

    model: str = ""

    def __init__(
        self,
        endpoints: list[FailoverEndpoint],
        *,
        on_observation: Optional[Callable[[str, bool, float], None]] = None,
        timeout: Optional[float] = None,
    ):
        self._endpoints = list(endpoints)
        self._on_observation = on_observation
        self._timeout = timeout
        self.last_endpoint: Optional[str] = None
        self.fallback_log: list[str] = []

    # ── 端点访问 ──

    def endpoints(self) -> list[FailoverEndpoint]:
        return list(self._endpoints)

    def __len__(self) -> int:
        return len(self._endpoints)

    def __repr__(self) -> str:
        return (f"<FailoverChat endpoints="
                f"{[e.name for e in self._endpoints]}>")

    # ── 观察记录 ──

    def _observe(self, endpoint: str, ok: bool, latency_ms: float) -> None:
        if self._on_observation is not None:
            try:
                self._on_observation(endpoint, ok, latency_ms)
            except Exception:
                logger.debug("observation callback failed", exc_info=True)

    # ── 同步调用 ──

    def invoke(
        self,
        messages: list[Any],
        tools: Optional[list[dict]] = None,
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> ChatResponse:
        errors: list[tuple[str, str]] = []
        for ep in self._endpoints:
            _t0 = time.time()
            try:
                resp = _invoke_client(
                    ep.client, messages, tools,
                    temperature=temperature, max_tokens=max_tokens,
                    timeout=timeout or self._timeout,
                )
                self._observe(ep.name, True, (time.time() - _t0) * 1000)
                self.last_endpoint = ep.name
                if errors:
                    note = (f"{time.strftime('%H:%M:%S')} 回退到 {ep.name}"
                            f"（此前失败: {errors[0][0]}）")
                    self.fallback_log.append(note)
                    logger.info("FailoverChat: %s 失败后回退到 %s 成功",
                                errors[0][0], ep.name)
                return resp
            except Exception as e:
                msg = f"{type(e).__name__}: {e}"
                errors.append((ep.name, msg))
                self._observe(ep.name, False, (time.time() - _t0) * 1000)
                logger.warning("FailoverChat: 端点 %s 调用失败: %s", ep.name, msg)
                continue
        err = errors[-1][1] if errors else "无可用端点"
        raise RuntimeError(f"所有端点均失败: {err}")

    # ── 流式调用 ──

    async def stream(
        self,
        messages: list[Any],
        tools: Optional[list[dict]] = None,
        **kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        errors: list[tuple[str, str]] = []
        for ep in self._endpoints:
            _t0 = time.time()
            produced = False
            try:
                if not hasattr(ep.client, "stream"):
                    # 无流式能力的客户端：同步 invoke 后单帧产出
                    import asyncio
                    resp = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: _invoke_client(
                            ep.client, messages, tools, **kwargs))
                    yield resp.content
                    produced = True
                    self._observe(ep.name, True, (time.time() - _t0) * 1000)
                    self.last_endpoint = ep.name
                    return
                agen = ep.client.stream(messages, tools, **kwargs)
                async for chunk in agen:
                    produced = True
                    yield chunk
                self._observe(ep.name, True, (time.time() - _t0) * 1000)
                self.last_endpoint = ep.name
                if errors:
                    note = (f"{time.strftime('%H:%M:%S')} 流式回退到 {ep.name}"
                            f"（此前失败: {errors[0][0]}）")
                    self.fallback_log.append(note)
                return
            except Exception as e:
                msg = f"{type(e).__name__}: {e}"
                errors.append((ep.name, msg))
                self._observe(ep.name, False, (time.time() - _t0) * 1000)
                if produced:
                    # 已产出内容后失败：无法回滚，直接上抛
                    raise RuntimeError(
                        f"端点 {ep.name} 流式中途失败: {msg}") from e
                logger.warning("FailoverChat: 端点 %s 流式启动失败: %s", ep.name, msg)
                continue
        err = errors[-1][1] if errors else "无可用端点"
        raise RuntimeError(f"所有端点均失败: {err}")
