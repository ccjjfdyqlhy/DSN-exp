# harness/models/stub.py
# 无网络依赖的桩实现 — 用于测试与离线开发。
#
# - StubChatClient: 脚本化/可编程回复的对话客户端
# - StubEmbeddingClient: 确定性哈希嵌入（供语义检索测试）

from __future__ import annotations

import hashlib
import math
from typing import Any, AsyncGenerator, Callable, Optional

from .base import ChatResponse, ChatClientAdapter


class StubChatClient(ChatClientAdapter):
    """可编程回复的桩对话客户端。支持按序脚本或动态回调。"""

    def __init__(
        self,
        *,
        model: str = "stub",
        responses: Optional[list[ChatResponse]] = None,
        respond: Optional[Callable[[list[dict], Optional[list[dict]]], ChatResponse]] = None,
    ):
        self.model = model
        self._responses = list(responses or [])
        self._respond = respond
        self.calls: list[dict] = []

    def invoke(
        self,
        messages: list[Any],
        tools: Optional[list[dict]] = None,
        **kwargs: Any,
    ) -> ChatResponse:
        msgs = self._to_message_dicts(messages)
        self.calls.append({"messages": msgs, "tools": tools, "kwargs": kwargs})
        if self._respond is not None:
            return self._respond(msgs, tools)
        if self._responses:
            return self._responses.pop(0)
        return ChatResponse(content="", model=self.model)

    async def stream(self, messages: list[Any], tools: Optional[list[dict]] = None,
                     **kwargs: Any) -> AsyncGenerator[str, None]:
        resp = self.invoke(messages, tools, **kwargs)
        for token in resp.content:
            yield token


class StubEmbeddingClient:
    """确定性字符 n-gram 哈希嵌入。无外部依赖，结果可复现。"""

    def __init__(self, dim: int = 128):
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_one(t) for t in texts]

    def embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = [text[i:i + 3] for i in range(max(1, len(text) - 2))]
        if not tokens:
            tokens = [text]
        for tok in tokens:
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            vec[h % self.dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]
