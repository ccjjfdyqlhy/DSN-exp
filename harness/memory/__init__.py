# harness/memory/__init__.py
# 通用记忆抽象 — 会话记忆 + 语义检索，与场景解耦。

from .base import MemoryEntry, IMemoryStore, MemoryStorePort
from .in_memory import InMemoryStore
from .vector import VectorIndex, cosine_similarity, pack_embedding, unpack_embedding

__all__ = [
    "MemoryEntry",
    "IMemoryStore",
    "MemoryStorePort",
    "InMemoryStore",
    "VectorIndex",
    "cosine_similarity",
    "pack_embedding",
    "unpack_embedding",
]
