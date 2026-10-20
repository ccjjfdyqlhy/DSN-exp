# infra/vector.py
# 向量原语与索引 —— 与具体业务无关的数值基础能力。
#
# 分层说明（2026-10 修复）：
#   这些原语原本放在 harness/memory/vector.py，但它们只依赖
#   infra.orchestrator.base.IEmbeddingClient（一个基础设施契约），
#   不含任何 Agent 语义。留在 harness 会让 infra/cache.py 反向依赖 harness，
#   形成 infra ↔ harness 循环。故下沉到本模块，harness 侧改为再导出。
#
# 维护提示：harness/memory/vector.py 现在是本模块的兼容层，
# 新代码请 `from infra.vector import ...`。

from __future__ import annotations

import math
import struct
from typing import Any, Optional

from .orchestrator.base import IEmbeddingClient


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
    """维护 键 → 向量 的映射，支持余弦相似度 top-k 检索。

    实现是 O(n) 线性扫描——适合几千条量级；更大规模请换成真正的向量库。
    """

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
