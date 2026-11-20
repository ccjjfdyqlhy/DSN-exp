# harness/memory/persistent.py
# SQLite-backed vector memory (W3.3): the first real consumer of the
# pack_embedding / unpack_embedding primitives that used to have zero callers.
#
# What this buys over InMemoryStore: vectors survive process restarts.
# The index is still cosine top-k over the stored rows -- fine at the
# few-thousand scale, same contract as infra VectorIndex.

from __future__ import annotations

from typing import Any, Optional

from .base import MemoryEntry
from aicf.infra.vector import cosine_similarity, pack_embedding, unpack_embedding


class SqliteVectorMemory:
    """IMemoryStore implementation persisting embeddings in SessionStore."""

    def __init__(self, store: Any, embedding_client: Any):
        self.store = store            # infra SessionStore (owns the vectors table)
        self.embedding_client = embedding_client

    # ── IMemoryStore contract ───────────────────────────
    def add(self, entry: MemoryEntry) -> None:
        vector = self.embedding_client.embed_one(entry.text)
        self.store.save_vector(entry.text, vector, role=entry.role,
                               meta=dict(entry.meta or {}))

    def add_text(self, text: str, role: str = 'user', **meta) -> None:
        self.add(MemoryEntry(text=text, role=role, meta=dict(meta)))

    def search(self, query: str, k: int = 5) -> list[MemoryEntry]:
        query_vector = self.embedding_client.embed_one(query)
        return [MemoryEntry(text=row['text'], role=row.get('role', 'user'),
                            meta=dict(row.get('meta') or {}))
                for row in self.store.similar_vectors(query_vector, k=k)]

    def clear(self) -> None:
        self.store.clear_vectors()

    def count(self) -> int:
        return self.store.count_vectors()

    def __len__(self) -> int:
        return self.count()


__all__ = ['SqliteVectorMemory']
