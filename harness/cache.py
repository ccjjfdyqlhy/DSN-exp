# harness/cache.py
# 通用语义缓存 — L1 精确命中 + L2 向量相似命中。
#
# 用于拦截重复请求节省 token / 复用合成产物。场景无关。

from __future__ import annotations

from typing import Any, Hashable, Optional

from .memory.vector import VectorIndex
from .models.base import IEmbeddingClient


class SemanticCache:
    """两级缓存。"""

    def __init__(
        self,
        embedding_client: Optional[IEmbeddingClient] = None,
        *,
        similarity_threshold: float = 0.9,
        max_l2_entries: int = 10000,
    ):
        self._l1: dict[Hashable, Any] = {}
        self._threshold = similarity_threshold
        self._l2 = VectorIndex(embedding_client) if embedding_client else None
        self._max_l2 = max_l2_entries

    def get(self, query: str, *, exact_key: Optional[Hashable] = None) -> tuple[bool, Any]:
        """返回 (hit, value)。"""
        key = exact_key if exact_key is not None else query
        if key in self._l1:
            return True, self._l1[key]
        if self._l2 is not None:
            scored = self._l2.search(query, k=1, threshold=self._threshold)
            if scored:
                return True, scored[0][0]
        return False, None

    def put(self, query: str, value: Any, *, exact_key: Optional[Hashable] = None) -> None:
        key = exact_key if exact_key is not None else query
        self._l1[key] = value
        if self._l2 is not None:
            if len(self._l2) >= self._max_l2:
                self._l2.clear()  # 简化：超限清空重建
            self._l2.add(value, query)

    def clear(self) -> None:
        self._l1.clear()
        if self._l2 is not None:
            self._l2.clear()

    @property
    def l1_size(self) -> int:
        return len(self._l1)

    @property
    def l2_size(self) -> int:
        return len(self._l2) if self._l2 else 0
