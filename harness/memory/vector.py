# harness/memory/vector.py
# 向量索引 — 基于嵌入的语义检索。

from __future__ import annotations

import math
from typing import Any, Optional

from ..models.base import IEmbeddingClient


class VectorIndex:
    """维护 文本 → 向量 的映射，支持余弦相似度 top-k 检索。"""

    def __init__(self, embedding_client: IEmbeddingClient):
        self._client = embedding_client
        self._entries: list[tuple[Any, list[float]]] = []

    def add(self, key: Any, text: str) -> None:
        self._entries.append((key, self._client.embed_one(text)))

    def add_batch(self, pairs: list[tuple[Any, str]]) -> None:
        texts = [t for _, t in pairs]
        vectors = self._client.embed(texts)
        for (key, _), vec in zip(pairs, vectors):
            self._entries.append((key, vec))

    def search(self, query: str, k: int = 5,
               threshold: Optional[float] = None) -> list[tuple[Any, float]]:
        if not self._entries:
            return []
        q = self._client.embed_one(query)
        scored = [(key, self._cosine(q, vec)) for key, vec in self._entries]
        scored.sort(key=lambda x: x[1], reverse=True)
        if threshold is not None:
            scored = [s for s in scored if s[1] >= threshold]
        return scored[:k]

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)
