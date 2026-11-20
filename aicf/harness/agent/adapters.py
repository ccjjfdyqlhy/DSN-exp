# harness/agent/adapters.py
# ToolCallAdapter — 工具调用协议适配 SPI。
#
# 不同模型/接口对"工具调用"的表达方式不同：
#   - 原生 function calling（OpenAI 风格）
#   - 文本内嵌标签（<tool>...</tool>）降级
# Adapter 负责：解析模型回复中的工具调用 + 组装下一轮消息。

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from aicf.infra.models.base import ChatMessage, ChatResponse, ToolCall

#: 工具名在"发给模型"的边界上必须转成 provider 安全的 wire 名
#: （点号 -> 双下划线，见 harness/tools/base.py to_wire_name）。
#: 这里按仓库既有约定延迟导入，避免 harness/agent 与 harness/tools 的导入环。
_TO_WIRE_NAME = None

#: 工具结果里承载图片的字段名（约定）。
#: 工具把图片放在结果的顶层，或放在 output 这个 dict 里，都认。
#:
#: 为什么要有这个约定：摄像头这类工具的产物就是「一张图」，
#: 而 tool 结果的 content 在协议上是**字符串**（Anthropic 还会 str() 拍平），
#: 图片塞不进 tool 消息。能进主模型上下文的只有 role="user" 的
#: content parts 列表 —— 所以工具把图交出来，由本模块转成内容块。
IMAGE_KEYS = ("image_url", "images")


def _extract_image_urls(result: dict) -> list[str]:
    """从一条工具结果里抽出图片 data URL。

    支持两种约定（工具返回 dict，或返回带 dict output 的结果）：
      * ``image_url`` —— 单张图的 data URL；
      * ``images``   —— 多张图的 data URL 列表。
    """
    urls: list[str] = []
    sources = [result]
    out = result.get("output")
    if isinstance(out, dict):
        sources.append(out)
    for src in sources:
        single = src.get("image_url")
        if isinstance(single, str) and single:
            urls.append(single)
        multi = src.get("images")
        if isinstance(multi, (list, tuple)):
            urls.extend([u for u in multi if isinstance(u, str) and u])
    return urls


def _strip_image_keys(value):
    """把 dict 里的图片键去掉（只处理顶层）。

    为什么必须摘掉：这些键里是 base64 原文。若留在 tool 结果的 JSON 里，
    就会变成几 MB 的**文本**回喂给模型 —— 既烧 token 又撑爆上下文，
    而且模型看到的是一串无意义字符，不是图片。
    """
    if isinstance(value, dict):
        return {k: v for k, v in value.items() if k not in IMAGE_KEYS}
    return value


def _image_user_message(urls: list[str]) -> ChatMessage:
    """构造承载图片的 user 消息（content parts 列表）。

    为什么是 role="user" 而不是 role="tool"：
      * OpenAI 的 tool 消息 content 必须是字符串，塞列表会 400；
      * Anthropic 路径会把 tool content 用 str() 拍平（anthropic.py:100），
        图片会变成 Python repr 的字符串。
    只有 user 消息在所有 client 上都能原样透传 content parts。
    """
    parts: list[dict] = [{
        "type": "text",
        "text": "工具返回的画面如下（已直接附上图片，未经过文字转述），"
                "请直接看图回答：",
    }]
    for url in urls:
        parts.append({"type": "image_url", "image_url": {"url": url}})
    return ChatMessage(role="user", content=parts)


def _to_wire(name: str) -> str:
    """把内部工具名转成 wire 名（不可用时原样返回，保证不因导入问题崩溃）。"""
    global _TO_WIRE_NAME
    if _TO_WIRE_NAME is None:
        try:
            from aicf.harness.tools.base import to_wire_name as _impl
        except Exception:  # noqa: BLE001
            _impl = None
        _TO_WIRE_NAME = _impl if _impl is not None else (lambda n: n)
    return _TO_WIRE_NAME(name)


@dataclass
class ParsedOutput:
    """解析模型回复得到的文本与工具调用。"""
    text: str = ""
    tool_calls: list[ToolCall] = None

    def __post_init__(self):
        if self.tool_calls is None:
            self.tool_calls = []


class ToolCallAdapter(ABC):
    """工具调用协议适配器。"""

    name: str = ""

    @abstractmethod
    def parse(self, response: ChatResponse) -> ParsedOutput:
        """从模型回复解析出文本与工具调用。"""

    @abstractmethod
    def build_round(self, response: ChatResponse,
                    results: list[dict]) -> list[ChatMessage]:
        """组装下一轮消息：assistant 消息 + 工具结果消息。

        results: [{call_id, name, output, success, error}]
        """

    def build_tools_schema(self, registry) -> list[dict]:
        """把工具注册表转为模型可用的 tools schema。默认导出全部。"""
        return registry.build_schema()


class NativeToolCallAdapter(ToolCallAdapter):
    """OpenAI 原生 function calling 协议。"""

    name = "native"

    def parse(self, response: ChatResponse) -> ParsedOutput:
        return ParsedOutput(text=response.content, tool_calls=list(response.tool_calls))

    def build_round(self, response: ChatResponse, results: list[dict]) -> list[ChatMessage]:
        image_urls: list[str] = []
        msgs = [ChatMessage.assistant(
            response.content,
            tool_calls=[
                # 关键：assistant 回传的 tool_calls.name 必须是**发给模型时的 wire 名**
                # （math__note），而不是内部名（math.note）。
                # AgentLoop 会把 ToolCall.name 归一成内部名以便派发，若这里原样回填，
                # 下一轮请求里就会出现带点号的函数名 —— 强校验 ^[a-zA-Z0-9_-]+$ 的
                # provider 会直接 400，工具循环在第二轮断掉。
                {"id": tc.id, "type": "function",
                 "function": {"name": _to_wire(tc.name), "arguments": tc.arguments_json}}
                for tc in response.tool_calls
            ],
            # DeepSeek reasoner 要求 reasoning_content 随 assistant 消息回传
            reasoning_content=response.reasoning_content,
        )]
        for r in results:
            # 回喂内容包含 状态(status) + 结果(output/error) + 下一步提示(hint)，
            # 让模型能依据结构化状态决定下一步（重试/换工具/询问用户）。
            payload = {
                "success": r.get("success", True),
                "status": r.get("status", "ok" if r.get("success", True) else "error"),
                "output": r.get("output"),
                "error": r.get("error"),
                "hint": r.get("hint"),
            }
            # 修复说明（2026-10）：AgentLoop 现在会把 ToolResult.data 展开进结果 dict，
            # 但这里只挑了 5 个固定字段，展开出来的附加键仍会被丢掉 ——
            # 工具的结构化附加信息依旧到不了模型。这里把「固定字段以外」的键也带上，
            # 同时不覆盖上面 5 个语义明确的字段。
            for _k, _v in r.items():
                if (_k not in payload and _k not in ("call_id", "name")
                        and _k not in IMAGE_KEYS):
                    payload[_k] = _v
            # output 里若也带了图片，同样摘掉（base64 不能进文本）
            payload["output"] = _strip_image_keys(payload.get("output"))
            content = json.dumps(payload, ensure_ascii=False, default=str)
            msgs.append(ChatMessage.tool_result(
                tool_call_id=r.get("call_id", "unknown"), content=content))
            image_urls.extend(_extract_image_urls(r))
        if image_urls:
            # 图片作为独立的 user 消息跟在 tool 结果之后 ——
            # 下一轮主模型调用就能直接看到这张图。
            msgs.append(_image_user_message(image_urls))
        return msgs


class TaggedToolCallAdapter(ToolCallAdapter):
    """文本内嵌标签降级协议。默认识别 <toolcall>...</toolcall>。"""

    name = "tagged"

    def __init__(self, tag: str = "toolcall"):
        self.tag = tag

    def _pattern(self) -> re.Pattern:
        return re.compile(
            rf"<{re.escape(self.tag)}>(.*?)</{re.escape(self.tag)}>",
            re.DOTALL | re.IGNORECASE,
        )

    def parse(self, response: ChatResponse) -> ParsedOutput:
        text = response.content or ""
        calls: list[ToolCall] = []
        for i, m in enumerate(self._pattern().finditer(text)):
            raw = (m.group(1) or "").strip()
            name = ""
            args: dict = {}
            try:
                data = json.loads(raw)
            except (TypeError, ValueError):
                data = None
            if isinstance(data, dict):
                name = str(data.get("name") or data.get("tool") or "")
                a = data.get("arguments") or data.get("args") or {}
                args = a if isinstance(a, dict) else {}
            else:
                # 形如 "tool.name {json}" 或只有名字
                head, _, rest = raw.partition(" ")
                name = head.strip()
                rest = rest.strip()
                if rest:
                    try:
                        parsed = json.loads(rest)
                        args = parsed if isinstance(parsed, dict) else {}
                    except (TypeError, ValueError):
                        args = {}
            if name:
                calls.append(ToolCall(id=f"tagged-{i}", name=name, arguments=args))
        cleaned = self._pattern().sub("", text).strip()
        return ParsedOutput(text=cleaned, tool_calls=calls)

    def build_round(self, response: ChatResponse, results: list[dict]) -> list[ChatMessage]:
        """标签协议没有原生 tool_calls：用 assistant 文本 + user 结果回喂。"""
        msgs: list[ChatMessage] = []
        image_urls: list[str] = []
        if response.content:
            msgs.append(ChatMessage.assistant(response.content))
        for i, r in enumerate(results):
            payload = {
                "tool": r.get("name", ""),
                "success": r.get("success", True),
                "status": r.get("status", "ok" if r.get("success", True) else "error"),
                "output": _strip_image_keys(r.get("output")),
                "error": r.get("error"),
                "hint": r.get("hint"),
            }
            msgs.append(ChatMessage.user(
                "<toolresult>" + json.dumps(payload, ensure_ascii=False, default=str)
                + "</toolresult>"
            ))
            image_urls.extend(_extract_image_urls(r))
        if image_urls:
            msgs.append(_image_user_message(image_urls))
        return msgs

