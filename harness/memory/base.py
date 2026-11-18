# harness/memory/base.py
# generic memory abstraction.
#
# MemoryStorePort is the canonical contract for a conversation memory service.
# an application implements it and registers the instance through Runtime.

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
    """Contract for the memory service used by the conversation path.

    An application implements this contract, registers it through Runtime, and
    the memory and recall plugins resolve it from there.
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
