# infra/cache.py
# 通用语义缓存 — L1 精确命中 + L2 向量相似命中。
#
# 用于拦截重复请求节省 token / 复用合成产物。场景无关。

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Hashable, Optional

# 修复说明（2026-10 分层）：
# 原先这里是 `from harness.memory.vector import VectorIndex`，会使 infra 反向依赖
# harness，并与 harness/memory/vector.py 中对 infra.models.base 的引用构成循环。
# 向量原语已下沉到 infra/vector.py，此处不再依赖 harness。
from .vector import VectorIndex
from .orchestrator.base import IEmbeddingClient


class SemanticCache:
    """两级缓存。"""

    def __init__(
        self,
        embedding_client: Optional[IEmbeddingClient] = None,
        *,
        similarity_threshold: float = 0.9,
        max_l1_entries: int = 4096,
        max_l2_entries: int = 10000,
    ):
        # 修复：L1 此前是无上限 dict，长跑进程随请求数无限增长（内存泄漏）；
        # 且全类无锁，多线程下 put 的"检查 L2 长度→clear→add"非原子。
        # 现 L1 用 OrderedDict 做 LRU（有界），读写统一持锁。
        self._l1: OrderedDict[Hashable, Any] = OrderedDict()
        self._max_l1 = max(1, int(max_l1_entries))
        self._lock = threading.Lock()
        self._threshold = similarity_threshold
        self._l2 = VectorIndex(embedding_client) if embedding_client else None
        self._max_l2 = max_l2_entries

    def get(self, query: str, *, exact_key: Optional[Hashable] = None) -> tuple[bool, Any]:
        """返回 (hit, value)。"""
        key = exact_key if exact_key is not None else query
        with self._lock:
            if key in self._l1:
                self._l1.move_to_end(key)
                return True, self._l1[key]
        if self._l2 is not None:
            scored = self._l2.search(query, k=1, threshold=self._threshold)
            if scored:
                return True, scored[0][0]
        return False, None

    def put(self, query: str, value: Any, *, exact_key: Optional[Hashable] = None) -> None:
        key = exact_key if exact_key is not None else query
        with self._lock:
            self._l1[key] = value
            self._l1.move_to_end(key)
            while len(self._l1) > self._max_l1:
                self._l1.popitem(last=False)
            if self._l2 is not None:
                if len(self._l2) >= self._max_l2:
                    self._l2.clear()  # 简化：超限清空重建
                self._l2.add(value, query)

    def clear(self) -> None:
        with self._lock:
            self._l1.clear()
            if self._l2 is not None:
                self._l2.clear()

    @property
    def l1_size(self) -> int:
        with self._lock:
            return len(self._l1)

    @property
    def l2_size(self) -> int:
        with self._lock:
            return len(self._l2) if self._l2 else 0
