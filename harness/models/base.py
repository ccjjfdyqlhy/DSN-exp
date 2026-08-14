# harness/models/base.py
# 通用模型抽象 — 消息、调用结果、客户端接口。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Optional, Protocol, runtime_checkable


@dataclass
class ChatMessage:
    """统一的对话消息表示，与厂商无关。"""
    role: str                       # system | user | assistant | tool
    content: str
    name: Optional[str] = None
    tool_calls: list[dict] = field(default_factory=list)
    tool_call_id: Optional[str] = None

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name:
            d["name"] = self.name
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        return d

    @classmethod
    def system(cls, content: str) -> "ChatMessage":
        return cls(role="system", content=content)

    @classmethod
    def user(cls, content: str) -> "ChatMessage":
        return cls(role="user", content=content)

    @classmethod
    def assistant(cls, content: str, tool_calls: Optional[list[dict]] = None) -> "ChatMessage":
        return cls(role="assistant", content=content, tool_calls=tool_calls or [])

    @classmethod
    def tool_result(cls, tool_call_id: str, content: str) -> "ChatMessage":
        return cls(role="tool", content=content, tool_call_id=tool_call_id)


@dataclass
class ToolCall:
    """模型请求的一次工具调用。"""
    id: str
    name: str
    arguments: dict = field(default_factory=dict)

    @property
    def arguments_json(self) -> str:
        import json
        return json.dumps(self.arguments, ensure_ascii=False)


@dataclass
class ChatResponse:
    """统一的模型调用结果。"""
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    model: Optional[str] = None
    finish_reason: Optional[str] = None


@runtime_checkable
class IChatClient(Protocol):
    """对话模型客户端接口。"""

    model: str

    def invoke(
        self,
        messages: list[Any],
        tools: Optional[list[dict]] = None,
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> ChatResponse: ...

    def stream(
        self,
        messages: list[Any],
        tools: Optional[list[dict]] = None,
        **kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        """流式输出生成器。

        yield 项两种形态（流式工具调用协议）：
          - str：文本增量（纯文本流，兼容旧调用方）
          - dict：结构化增量事件，可含：
              {"content": str}                       文本增量
              {"tool_calls": [{"index", "id", "name", "arguments"}]}
                                                     工具调用增量（按 index 累积）
              {"usage": {...}}                       用量信息
        实现应保证：无工具增量时只 yield str（保持向后兼容）。
        """


@runtime_checkable
class IEmbeddingClient(Protocol):
    """向量嵌入客户端接口。"""

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def embed_one(self, text: str) -> list[float]: ...


@runtime_checkable
class IModelProvider(Protocol):
    """模型提供商接口 — 按需解析对话/嵌入客户端。"""

    def get_chat_client(
        self, model_name: Optional[str] = None, model_type: Optional[str] = None,
    ) -> IChatClient: ...

    def get_embedding_client(self) -> Optional[IEmbeddingClient]: ...


class ChatClientAdapter:
    """IChatClient 的便捷基类，提供消息归一化辅助。"""

    model: str = ""

    @staticmethod
    def _to_message_dicts(messages: list[Any]) -> list[dict]:
        out = []
        for m in messages:
            if isinstance(m, ChatMessage):
                out.append(m.to_dict())
            elif isinstance(m, dict):
                out.append(m)
            else:
                raise TypeError(f"无法归一化消息类型: {type(m).__name__}")
        return out
