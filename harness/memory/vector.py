# harness/memory/vector.py
# 向量索引 — 基于嵌入的语义检索。
#
# DSN 超集：pack_embedding / unpack_embedding / cosine_similarity 为通用向量原语，
# DSN MemorySystem 的嵌入存储与检索即使用这些原语（见 apps/dsn/memory/core.py）。

from __future__ import annotations

import math
import struct
from typing import Any, Optional

from ..models.base import IEmbeddingClient


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """余弦相似度。空向量或维度不一致返回 0.0。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def pack_embedding(vec: list[float]) -> bytes:
    """把 float 向量打包为二进制（float32 原生序），供数据库 BLOB 存储。"""
    return struct.pack(f"{len(vec)}f", *vec)


def unpack_embedding(blob: bytes) -> list[float]:
    """从二进制解包 float 向量（与 pack_embedding 对应）。"""
    return list(struct.unpack(f"{len(blob) // 4}f", blob))


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
        scored = [(key, cosine_similarity(q, vec)) for key, vec in self._entries]
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
        """兼容入口 — 统一走模块级 cosine_similarity。"""
        return cosine_similarity(a, b)
