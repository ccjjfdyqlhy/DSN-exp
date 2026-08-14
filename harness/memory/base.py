# harness/memory/base.py
# 通用记忆抽象。
#
# DSN 超集：MemoryStorePort 是"对话路径记忆服务"的 canonical 契约
# （dsn MemorySystem 实现并经 harness Runtime 注册，见 apps/dsn/memory/core.py）。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable


@dataclass
class MemoryEntry:
    """一条记忆记录。"""
    text: str
    role: str = "user"               # user | assistant | system | memo
    meta: dict = field(default_factory=dict)
    timestamp: Optional[float] = None


@runtime_checkable
class IMemoryStore(Protocol):
    """记忆存储接口 — 追加、检索、清空。"""

    def add(self, entry: MemoryEntry) -> None: ...

    def search(self, query: str, k: int = 5) -> list[MemoryEntry]: ...

    def clear(self) -> None: ...

    def count(self) -> int: ...


@runtime_checkable
class MemoryStorePort(Protocol):
    """对话路径使用的记忆服务契约（由 harness 全局引擎定义）。

    DSN 的 MemorySystem 即实现此契约并经 harness Runtime 注册，
    对话路径（MemoryPlugin / RecallPlugin / topics）经 harness 解析该服务。
    """

    def assemble_context(
        self,
        user_id: int,
        history: list,
        cross_user_id: Any = ...,
        chat_id: Any = None,
    ) -> list: ...

    def summarize_turn(
        self,
        user_id: int,
        chat_id: int,
        round_idx: int,
        user_msg: str,
        assistant_reply: str,
        **kwargs: Any,
    ) -> Any: ...

    def search(
        self,
        user_id: int,
        keywords: list,
        limit: int = ...,
        **kwargs: Any,
    ) -> list: ...

    def add_memo(self, user_id: int, chat_id: int, text: str) -> int: ...

    def delete_memo(self, memo_id: int) -> bool: ...
