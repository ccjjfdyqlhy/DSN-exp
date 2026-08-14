# tests/test_harness_memory.py
# harness 记忆系统超集测试：向量原语 / 服务契约 + dsn 实现对齐。

from __future__ import annotations

import sqlite3

from harness.memory import (
    MemoryEntry, IMemoryStore, MemoryStorePort, InMemoryStore, VectorIndex,
    cosine_similarity, pack_embedding, unpack_embedding,
)
from harness.models.stub import StubEmbeddingClient


def test_vector_primitives_roundtrip():
    vec = [0.1, -0.2, 0.3, 0.4]
    blob = pack_embedding(vec)
    # float32 存储有精度损失，逐元素近似断言
    assert len(unpack_embedding(blob)) == len(vec)
    for got, want in zip(unpack_embedding(blob), vec):
        assert abs(got - want) < 1e-6


def test_cosine_similarity_values():
    a = [1.0, 0.0]
    b = [1.0, 0.0]
    assert abs(cosine_similarity(a, b) - 1.0) < 1e-9
    assert abs(cosine_similarity(a, [0.0, 1.0])) < 1e-9
    # 空向量 / 维度不一致 → 0
    assert cosine_similarity([], [1.0]) == 0.0
    assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0


def test_vector_index_uses_harness_cosine():
    idx = VectorIndex(StubEmbeddingClient())
    idx.add("k1", "咖啡")
    idx.add("k2", "天气")
    hits = idx.search("咖啡", k=1)
    assert hits and hits[0][0] == "k1"
    # _cosine 兼容入口指向模块级实现
    assert VectorIndex._cosine([1.0, 0.0], [1.0, 0.0]) == cosine_similarity([1.0, 0.0], [1.0, 0.0])


def test_memory_store_port_protocol():
    assert hasattr(MemoryStorePort, "assemble_context")
    assert hasattr(MemoryStorePort, "summarize_turn")
    assert hasattr(MemoryStorePort, "search")
    assert hasattr(MemoryStorePort, "add_memo")
    assert hasattr(MemoryStorePort, "delete_memo")


def test_dsn_memory_system_conforms_memory_store_port():
    """dsn MemorySystem 结构上符合 harness MemoryStorePort 契约。"""
    from apps.dsn.memory.core import MemorySystem

    class FakeCipher:
        def encrypt(self, user_id, text):
            return text
        def decrypt(self, user_id, text):
            return text

    class FakeDB:
        def __init__(self):
            self.conn = sqlite3.connect(":memory:")
            self.conn.row_factory = sqlite3.Row
            self._cipher = FakeCipher()
        def _get_connection(self):
            return self.conn

    ms = MemorySystem(db=FakeDB(), summary_model=object(), embedding_client=None)
    assert isinstance(ms, MemoryStorePort), "MemorySystem 未实现 MemoryStorePort"
    assert ms.embedding_client is None


def test_dsn_memory_primitives_delegate_to_harness():
    """dsn 记忆检索原语来自 harness（pack/unpack/cosine 委托）。"""
    import apps.dsn.memory.core as core
    vec = [0.5, -1.5, 2.0]
    assert core.MemorySystem._pack_embedding(vec) == pack_embedding(vec)
    blob = pack_embedding(vec)
    assert core.MemorySystem._unpack_embedding(blob) == vec
    assert core.MemorySystem._cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
    # 单一生效源：dsn 模块内的名字即 harness 函数
    assert core.pack_embedding is pack_embedding
    assert core.cosine_similarity is cosine_similarity
