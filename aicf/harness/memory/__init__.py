# harness/memory/__init__.py
# 通用记忆抽象 — 会话记忆 + 语义检索，与场景解耦。
# 可审计的两级模型（Source→Artifact）见 provenance —— SDK 默认路径
# enable_memory=True + security_audit=True（默认）时自动启用。

from .base import MemoryEntry, IMemoryStore, MemoryStorePort
from .in_memory import InMemoryStore
from .persistent import SqliteVectorMemory
from .provenance import (
    DisclosureMatrix,
    DisclosureRule,
    EvidenceGate,
    MemoryArtifact,
    MemorySource,
    ProvenanceMemoryStore,
)
from .session_port import SessionMemoryStore
from .topic import (
    DriftTopicDetector,
    TopicDecision,
    TopicDetectorPort,
    TopicManager,
    TopicRecord,
)
from .vector import VectorIndex, cosine_similarity, pack_embedding, unpack_embedding

__all__ = [
    "MemoryEntry",
    "IMemoryStore",
    "MemoryStorePort",
    "InMemoryStore",
    "SqliteVectorMemory",
    "SessionMemoryStore",
    "DriftTopicDetector",
    "TopicDecision",
    "TopicDetectorPort",
    "TopicManager",
    "TopicRecord",
    "DisclosureMatrix",
    "DisclosureRule",
    "EvidenceGate",
    "MemoryArtifact",
    "MemorySource",
    "ProvenanceMemoryStore",
    "VectorIndex",
    "cosine_similarity",
    "pack_embedding",
    "unpack_embedding",
]
