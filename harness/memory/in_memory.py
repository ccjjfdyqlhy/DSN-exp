# harness/memory/in_memory.py
# 进程内记忆存储 — 支持精确关键词 + 可选向量语义检索。

from __future__ import annotations

import re
import time
from typing import Optional

from infra.models.base import IEmbeddingClient
from .base import MemoryEntry
from .vector import VectorIndex

#: Latin words and CJK runs. A CJK run has no spaces, so it is split into
#: character bigrams afterwards.
_WORD_RE = re.compile(r'[a-z0-9_]+|[\u4e00-\u9fff]+')


def keywords(text: str) -> list[str]:
    """Split a query into matchable keywords.

    Why not match the whole query: the user asks a new question about an
    old fact, so a substring test on the full sentence almost never hits.
    Latin words stay whole, a CJK run becomes character bigrams.
    """
    lowered = (text or '').lower()
    words: list[str] = []
    for token in _WORD_RE.findall(lowered):
        if not token.isascii():
            if len(token) == 1:
                words.append(token)
            else:
                words.extend(token[i:i + 2] for i in range(len(token) - 1))
        else:
            words.append(token)
    return [word for word in words if len(word) > 1]


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
        return self._keyword_search(query, k)

    def _keyword_search(self, query: str, k: int) -> list[MemoryEntry]:
        """Rank the entries by how many query keywords they contain."""
        terms = keywords(query)
        if not terms:
            return []
        scored: list[tuple[int, MemoryEntry]] = []
        for entry in self._entries:
            haystack = entry.text.lower()
            hits = sum(1 for term in terms if term in haystack)
            if hits:
                scored.append((hits, entry))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [entry for _hits, entry in scored[:k]]

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
