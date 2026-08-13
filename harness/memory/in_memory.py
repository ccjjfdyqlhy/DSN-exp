# harness/memory/in_memory.py
# 进程内记忆存储 — 支持精确关键词 + 可选向量语义检索。

from __future__ import annotations

import time
from typing import Optional

from ..models.base import IEmbeddingClient
from .base import MemoryEntry
from .vector import VectorIndex


class InMemoryStore:
    """简单内存记忆。可选挂载向量索引以支持语义检索。"""

    def __init__(self, embedding_client: Optional[IEmbeddingClient] = None):
        self._entries: list[MemoryEntry] = []
        self._index = VectorIndex(embedding_client) if embedding_client else None

    def add(self, entry: MemoryEntry) -> None:
        if entry.timestamp is None:
            entry.timestamp = time.time()
        self._entries.append(entry)
        if self._index is not None:
            self._index.add(len(self._entries) - 1, entry.text)

    def add_text(self, text: str, role: str = "user", **meta) -> None:
        self.add(MemoryEntry(text=text, role=role, meta=meta))

    def search(self, query: str, k: int = 5) -> list[MemoryEntry]:
        if self._index is not None:
            scored = self._index.search(query, k)
            return [self._entries[i] for i, _ in scored]
        # 关键词降级：子串匹配
        hits = [e for e in self._entries if query.lower() in e.text.lower()]
        return hits[:k]

    def all(self) -> list[MemoryEntry]:
        return list(self._entries)

    def clear(self) -> None:
        self._entries.clear()
        if self._index is not None:
            self._index.clear()

    def count(self) -> int:
        return len(self._entries)

    def __len__(self) -> int:
        return len(self._entries)
