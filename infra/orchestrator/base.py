# infra/models/base.py
# 通用模型抽象 — 消息、调用结果、客户端接口。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Optional, Protocol, runtime_checkable

import requests

#: 面向本地引擎（127.0.0.1）复用的 HTTP 会话，见 local_http_session()。
_LOCAL_HTTP_SESSION: requests.Session | None = None


def local_http_session() -> requests.Session:
    """返回一个**忽略代理环境变量**的 requests.Session（进程内复用）。

    本地推理引擎（llama-server / Strata / LMStudio）只监听 127.0.0.1，但
    requests 默认 trust_env=True 会读取 ALL_PROXY / HTTP_PROXY，把发往
    localhost 的请求也交给代理。实测在 ALL_PROXY=socks5h://127.0.0.1:10808
    且该代理未运行时，**所有**本地请求直接 ConnectionError：

        requests.get("http://127.0.0.1:8080/health")
        -> ConnectionError: SOCKSHTTPConnectionPool ... Connection refused

    后果是就绪探针永远失败 —— 模型其实已经加载完成，界面却一直卡在加载中，
    直到 180s 超时。注意 proxies={"http": None} **不足以**覆盖环境变量，
    必须显式关掉 trust_env。

    会话可跨线程复用：底层 urllib3 连接池是线程安全的，这里也只用它发
    不带 cookie/状态的本地请求。
    """
    global _LOCAL_HTTP_SESSION
    if _LOCAL_HTTP_SESSION is None:
        session = requests.Session()
        session.trust_env = False
        _LOCAL_HTTP_SESSION = session
    return _LOCAL_HTTP_SESSION


#: 面向本地引擎的「探测」专用会话，见 local_probe_session()。
_PROBE_HTTP_SESSION: requests.Session | None = None


def local_probe_session() -> requests.Session:
    """专用于健康检查/属性探测的本地会话（与 local_http_session 分开）。

    为什么要分开：流式响应（SSE）通常在读到 [DONE] 就提前 close()，
    底层连接还剩一点字节没读完。urllib3 仍可能把这条连接放回连接池，
    于是**下一个复用到它的请求会失败**。

    实测后果：一次流式对话之后，同一会话上的 /health 探测返回失败 →
    is_ready() 判为未就绪 → 触发一次毫无必要的重新拉起，并广播一次
    假的 loading/loaded 状态。

    探测都是完整读取的简单 GET，单独一条会话即可保证连接始终干净。
    """
    global _PROBE_HTTP_SESSION
    if _PROBE_HTTP_SESSION is None:
        session = requests.Session()
        session.trust_env = False
        _PROBE_HTTP_SESSION = session
    return _PROBE_HTTP_SESSION


def content_shape(content: Any) -> str:
    """把一条消息的 content 概括成可读形状，用于多模态链路排查。

    形如 text(12c) / parts[image_url=1,text=1](9400000c) —— 一眼看出
    图像内容块在哪一层掉了。
    """
    if isinstance(content, str):
        return f"text({len(content)}c)"
    if isinstance(content, (list, tuple)):
        counts: dict[str, int] = {}
        total = 0
        for part in content:
            if isinstance(part, dict):
                ptype = str(part.get("type") or ("text" if "text" in part else "?"))
                counts[ptype] = counts.get(ptype, 0) + 1
                url = part.get("image_url")
                if isinstance(url, dict):
                    total += len(str(url.get("url") or ""))
                else:
                    total += len(str(part.get("text") or ""))
            else:
                counts["?"] = counts.get("?", 0) + 1
        detail = ",".join(f"{k}={v}" for k, v in sorted(counts.items()))
        return f"parts[{detail}]({total}c)"
    return f"{type(content).__name__}"


def count_image_parts(messages: Any) -> int:
    """统计消息列表里 image_url 内容块的数量（多模态链路的关键指标）。"""
    total = 0
    for m in messages or []:
        content = m.get("content") if isinstance(m, dict) else getattr(m, "content", None)
        if isinstance(content, (list, tuple)):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    total += 1
    return total


@dataclass
class ChatMessage:
    """统一的对话消息表示，与厂商无关。"""
    role: str                       # system | user | assistant | tool
    #: 纯文本时为 str；多模态时是 OpenAI 风格的 content parts 列表
    #: （[{"type":"text",...}, {"type":"image_url",...}]）。刻意不强制转成
    #: 字符串 —— 拍平会把图像内容块丢掉。
    content: Any = ""
    name: Optional[str] = None
    tool_calls: list[dict] = field(default_factory=list)
    tool_call_id: Optional[str] = None
    # DeepSeek reasoner 等模型要求把上轮的 reasoning_content 回传给 API，
    # 否则多轮工具调用会报 400 "reasoning_content must be passed back"。
    reasoning_content: Optional[str] = None

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name:
            d["name"] = self.name
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.reasoning_content:
            d["reasoning_content"] = self.reasoning_content
        return d

    @classmethod
    def system(cls, content: str) -> "ChatMessage":
        return cls(role="system", content=content)

    @classmethod
    def user(cls, content: str) -> "ChatMessage":
        return cls(role="user", content=content)

    @classmethod
    def assistant(cls, content: str, tool_calls: Optional[list[dict]] = None,
                  reasoning_content: Optional[str] = None) -> "ChatMessage":
        return cls(role="assistant", content=content, tool_calls=tool_calls or [],
                   reasoning_content=reasoning_content)

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
    reasoning_content: Optional[str] = None


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
            if hasattr(m, "to_dict") and callable(m.to_dict):
                out.append(m.to_dict())
            elif isinstance(m, dict):
                out.append(m)
            else:
                raise TypeError(f"无法归一化消息类型: {type(m).__name__}")
        return out
