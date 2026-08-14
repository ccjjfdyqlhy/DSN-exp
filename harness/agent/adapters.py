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

from ..models.base import ChatMessage, ChatResponse, ToolCall


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
        msgs = [ChatMessage.assistant(
            response.content,
            tool_calls=[
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.name, "arguments": tc.arguments_json}}
                for tc in response.tool_calls
            ],
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
            content = json.dumps(payload, ensure_ascii=False, default=str)
            msgs.append(ChatMessage.tool_result(
                tool_call_id=r.get("call_id", "unknown"), content=content))
        return msgs


class TaggedToolCallAdapter(ToolCallAdapter):
    """文本内嵌标签降级协议。默认识别 <toolcall>...</toolcall>。"""

    name = "tagged"

    def __init__(self, tag: str = "toolcall"):
        self.tag = tag

    def parse(self, response: ChatResponse) -> ParsedOutput:
        text = response.content or ""
        tool_calls: list[ToolCall] = []
        pattern = re.compile(
            rf"<{self.tag}>\s*(.*?)\s*</{self.tag}>", re.DOTALL)
        cleaned = pattern.sub("", text).strip()
        for m in pattern.finditer(text):
            inner = m.group(1).strip()
            try:
                obj = json.loads(inner)
            except (TypeError, ValueError):
                # 尝试 name: json 形式
                obj = self._parse_loose(inner)
            if not obj:
                continue
            name = obj.get("name") or obj.get("tool") or obj.get("function")
            args = obj.get("arguments") or obj.get("args") or obj.get("params") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (TypeError, ValueError):
                    args = {}
            if name:
                tool_calls.append(ToolCall(
                    id=f"tagged-{len(tool_calls)}", name=name, arguments=args))
        return ParsedOutput(text=cleaned, tool_calls=tool_calls)

    @staticmethod
    def _parse_loose(inner: str) -> Optional[dict]:
        """容忍 'name\n<json>' 之类的松散格式。"""
        head, _, tail = inner.partition("\n")
        head = head.strip()
        try:
            if head and tail.strip():
                obj = json.loads(tail.strip())
                obj.setdefault("name", head)
                return obj
        except (TypeError, ValueError):
            return None
        return None

    def build_round(self, response: ChatResponse, results: list[dict]) -> list[ChatMessage]:
        lines = []
        for r in results:
            data = r.get("output") if r.get("success") else r.get("error")
            hint = r.get("hint")
            line = f"- {r.get('name', 'tool')} [{r.get('status', 'ok' if r.get('success', True) else 'error')}]: {json.dumps(data, ensure_ascii=False, default=str)}"
            if hint:
                line += f" (提示: {hint})"
            lines.append(line)
        summary = "\n".join(lines)
        return [
            ChatMessage.assistant(response.content),
            ChatMessage.user(f"[工具执行结果]\n{summary}"),
        ]
