# harness/agent/context.py
# ThreeZoneContext — 三段式上下文（prefix / history / draft）+ 工具顺序清理。
#
# 设计目标：稳定前缀（prefix）最大化模型前缀缓存命中；draft 存放本回合
# 工具结果（可整体提交或回滚）；history 为已提交的对话。
#
# SpeculativePrefetch 从工具错误输出解析未定义符号并注入源码，减少往返。
# [FETCH:...] 占位符协议由 PrefetchPlaceholders 解析。

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..models.base import ChatMessage


class ThreeZoneContext:
    """prefix / history / draft 三段上下文。"""

    def __init__(self, system_prompt: str = ""):
        self.system_prompt = system_prompt
        self.prefix: list[ChatMessage] = []
        self.history: list[ChatMessage] = []
        self.draft: list[ChatMessage] = []

    def build_request(self) -> list[ChatMessage]:
        msgs: list[ChatMessage] = []
        if self.system_prompt:
            msgs.append(ChatMessage.system(self.system_prompt))
        msgs += self.prefix + self.history + self.draft
        return self._sanitize_tool_order(msgs)

    def stable_prefix(self) -> list[ChatMessage]:
        msgs: list[ChatMessage] = []
        if self.system_prompt:
            msgs.append(ChatMessage.system(self.system_prompt))
        return msgs + self.prefix

    def attach_prefix(self, content: str, *, dedupe: bool = True) -> None:
        if dedupe and any(m.content == content for m in self.prefix):
            return
        self.prefix.append(ChatMessage.system(content))

    def clear_prefix(self) -> None:
        self.prefix.clear()

    def add_user(self, content: str) -> None:
        self.history.append(ChatMessage.user(content))

    def add_assistant(self, msg: ChatMessage) -> None:
        self.history.append(msg)

    def add_tool_result(self, tool_call_id: str, name: str, content: str) -> None:
        self.draft.append(ChatMessage.tool_result(tool_call_id, content))

    def commit_draft(self) -> None:
        self.history.extend(self.draft)
        self.draft.clear()

    def rollback_draft(self) -> None:
        self.draft.clear()

    def total_messages(self) -> int:
        return len(self.build_request())

    @staticmethod
    def _sanitize_tool_order(msgs: list[ChatMessage]) -> list[ChatMessage]:
        """移除孤立 tool 消息，确保每条 tool 前有对应的 assistant(tool_calls)。"""
        result: list[ChatMessage] = []
        pending_ids: set[str] = set()
        for m in msgs:
            if m.role == "tool":
                if m.tool_call_id not in pending_ids:
                    continue
                result.append(m)
            else:
                pending_ids = {tc.get("id") for tc in m.tool_calls} if m.tool_calls else set()
                result.append(m)
        return result


# ── 推测性预取 ──

_UNDEFINED_SYMBOL_RE = re.compile(
    r"NameError: name '(\w+)' is not defined|'(\w+)' object has no attribute"
    r"|undefined symbol: (\w+)|Unresolved reference: (\w+)"
)


class SpeculativePrefetch:
    """从错误输出解析未定义符号，经符号索引查找并注入源码。"""

    def __init__(self, symbol_lookup: Callable[[str], Optional[dict]],
                 symbol_guess: Optional[Callable[[str], list[str]]] = None,
                 source_loader: Optional[Callable[[str, int], str]] = None):
        self._lookup = symbol_lookup
        self._guess = symbol_guess or (lambda n: [])
        self._source_loader = source_loader

    def analyze(self, text: str) -> list[str]:
        names = set()
        for m in _UNDEFINED_SYMBOL_RE.finditer(text):
            for g in m.groups():
                if g:
                    names.add(g)
        found = []
        for name in names:
            sym = self._lookup(name)
            if sym is None and self._guess:
                for sname in self._guess(name):
                    if self._lookup(sname) is not None:
                        found.append(sname)
                        break
            elif sym is not None:
                found.append(name)
        return found

    def prefetch(self, symbol_names: list[str],
                 max_source_lines: int = 15) -> str:
        blocks = []
        seen = set()
        for name in symbol_names:
            if name in seen:
                continue
            seen.add(name)
            sym = self._lookup(name)
            if not sym:
                continue
            fpath = sym.get("file_path", "")
            line = int(sym.get("line", 1))
            if self._source_loader is None:
                continue
            try:
                source = self._source_loader(fpath, line)
            except (FileNotFoundError, IOError, OSError):
                continue
            if not source:
                continue
            header = sym.get("signature", name)
            blocks.append(f"# {header}  ({fpath}:{line})\n{source[:max_source_lines * 200]}")
        return "\n\n".join(blocks)


# ── [FETCH:...] 占位符协议 ──

_FETCH_RE = re.compile(r"\[FETCH:([^\]]+)\]")


class PrefetchPlaceholders:
    """把模型回复中的 [FETCH:Symbol] 占位符替换为符号源码。"""

    def __init__(self, fetch_resolver: Callable[[str], Optional[str]]):
        self._resolver = fetch_resolver

    def resolve(self, text: str) -> str:
        def _sub(m: re.Match) -> str:
            name = m.group(1).strip()
            src = self._resolver(name)
            return f"\n```\n{src}\n```\n" if src else m.group(0)
        return _FETCH_RE.sub(_sub, text)

    def pending(self, text: str) -> list[str]:
        return [m.group(1).strip() for m in _FETCH_RE.finditer(text)]
