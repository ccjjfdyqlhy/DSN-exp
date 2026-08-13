# harness/memory/base.py
# 通用记忆抽象。

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
