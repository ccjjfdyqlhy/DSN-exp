# tests/test_memory.py
# 测试新 MemorySystem — 上下文压缩、主动召回、备忘录

import os
import sys
import json
import unittest
import tempfile
from typing import Optional
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from apps.dsn.config import Config
from apps.dsn.memory import MemorySystem


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

class FakeCipher:
    """明文透传（无加密）"""
    def encrypt(self, user_id: int, text: str) -> str:
        return text
    def decrypt(self, user_id: int, text: str) -> str:
        return text


class FakeDB:
    """轻量 in-memory SQLite，模拟 ChatDBManager 的最小接口"""

    def __init__(self):
        import sqlite3
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._cipher = FakeCipher()
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                round INTEGER,
                round_index INTEGER,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT DEFAULT (datetime('now'))
            )
        """)
        self.conn.commit()

    def _get_connection(self):
        return self.conn

    def get_next_round_index(self, chat_id: int) -> int:
        row = self.conn.execute(
            "SELECT MAX(round) FROM memory_v2 WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        return (row[0] or 0) + 1

    def get_messages_by_rounds(self, user_id, chat_id, rounds):
        placeholder = ",".join("?" for _ in rounds)
        rows = self.conn.execute(
            f"SELECT round, role, content, timestamp FROM messages "
            f"WHERE chat_id = ? AND round_index IN ({placeholder}) "
            f"ORDER BY round ASC, message_id ASC",
            [chat_id] + list(rounds),
        ).fetchall()
        result = {}
        for r in rows:
            result.setdefault(r["round"], []).append({
                "role": r["role"],
                "content": r["content"],
                "timestamp": r["timestamp"],
            })
        return result


class FakeLMSummaryModel:
    def summarize_dialog(self, messages, max_length=100):
        user = messages[0]["content"] if messages else ""
        return f"讨论了: {user[:80]}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMemorySystem(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db = FakeDB()
        cls.summary_model = FakeLMSummaryModel()
        cls.ms = MemorySystem(db=cls.db, summary_model=cls.summary_model)

    def setUp(self):
        self.db.conn.execute("DELETE FROM memory_v2")

    # ---- helpers ----

    def _seed_exp(self, uid=1, cid=1, round_=1, content="test memory"):
        enc = self.db._cipher.encrypt(uid, content)
        self.db.conn.execute(
            "INSERT INTO memory_v2 (user_id, chat_id, type, round, content) "
            "VALUES (?, ?, 'exp', ?, ?)", (uid, cid, round_, enc)
        )
        self.db.conn.commit()

    def _seed_memo(self, uid=1, cid=1, text="test memo"):
        enc = self.db._cipher.encrypt(uid, text)
        self.db.conn.execute(
            "INSERT INTO memory_v2 (user_id, chat_id, type, content) "
            "VALUES (?, ?, 'memo', ?)", (uid, cid, enc)
        )
        self.db.conn.commit()

    # ---- 1. 备忘录 CRUD ----

    def test_add_memo(self):
        mid = self.ms.add_memo(1, 1, "用户喜欢咖啡")
        self.assertIsInstance(mid, int)
        self.assertGreater(mid, 0)

    def test_get_memos_via_context(self):
        self.ms.add_memo(1, 1, "用户生日是6月15日")
        self.ms.add_memo(1, 1, "用户不喜欢香菜")
        history = [{"role": "user", "content": "hello"}]

        result = self.ms.assemble_context(1, history)
        self.assertEqual(len(result), 3)
        self.assertIn("[备忘]", result[0]["content"])
        self.assertIn("用户生日是6月15日", result[0]["content"])
        self.assertIn("[备忘]", result[1]["content"])
        self.assertIn("用户不喜欢香菜", result[1]["content"])
        self.assertEqual(result[2], history[0])

    def test_delete_memo(self):
        mid = self.ms.add_memo(1, 1, "临时备忘")
        self.assertTrue(self.ms.delete_memo(mid))
        self.assertFalse(self.ms.delete_memo(mid))  # already deleted

    # ---- 2. 上下文压缩 (被动回忆) ----

    def test_assemble_context_no_compression(self):
        """少量消息不触发压缩"""
        self._seed_exp(1, 1, 1, "讨论了Python异步")
        history = [
            {"role": "user", "content": f"msg{i}"}
            for i in range(10)
        ]
        result = self.ms.assemble_context(1, history)
        # 10 <= threshold (56) → no compression, just pass through
        self.assertEqual(len(result), 10)
        self.assertEqual(history, result)

    def test_assemble_context_triggers_compression(self):
        """大量消息触发压缩，远端历史被记忆摘要替换"""
        self._seed_exp(1, 1, 1, "第一轮摘要")
        self._seed_exp(1, 1, 2, "第二轮摘要")

        history = [{"role": "user", "content": f"msg{i}"} for i in range(100)]

        result = self.ms.assemble_context(1, history)
        # 100 > 56 → compress
        # result = [记忆1, 记忆2] + [recent 56 msgs]
        self.assertGreater(len(result), 0)
        self.assertIn("[记忆 · 轮次1]", result[0]["content"])
        self.assertIn("[记忆 · 轮次2]", result[1]["content"])
        self.assertNotIn("[记忆", [m["content"] for m in result[2:]])
        self.assertEqual(result[0]["role"], "system")
        self.assertEqual(len(result), 2 + 56)  # 2 mems + 56 recent

    def test_assemble_context_with_memos(self):
        """备忘录始终排在摘要和消息前面"""
        self.ms.add_memo(1, 1, "重要备忘")
        self._seed_exp(1, 1, 1, "讨论摘要")

        history = [{"role": "user", "content": f"msg{i}"} for i in range(100)]

        result = self.ms.assemble_context(1, history)
        self.assertIn("[备忘]", result[0]["content"])
        self.assertIn("[记忆", result[1]["content"])

    # ---- 3. 主动召回 (搜索) ----

    def test_search_returns_empty(self):
        hits = self.ms.search(1, ["nothing"])
        self.assertEqual(hits, [])

    def test_search_finds_exact_match(self):
        self._seed_exp(1, 1, 1, "用户喜欢Python编程")
        self._seed_exp(1, 1, 2, "讨论过Rust语言特性")

        hits = self.ms.search(1, ["Python"])
        self.assertEqual(len(hits), 1)
        self.assertIn("Python编程", hits[0]["content"])

    def test_search_matches_chinese(self):
        self._seed_exp(1, 1, 1, "用户在北京工作")
        self._seed_exp(1, 1, 2, "用户在上海出差")

        hits = self.ms.search(1, ["北京"])
        self.assertEqual(len(hits), 1)
        self.assertIn("北京", hits[0]["content"])

    def test_search_multiple_keywords(self):
        self._seed_exp(1, 1, 1, "用户使用Python和FastAPI")
        self._seed_exp(1, 1, 2, "用户使用Go和Docker")

        hits = self.ms.search(1, ["Python", "FastAPI"])
        self.assertEqual(len(hits), 1)

    def test_search_respects_limit(self):
        for i in range(10):
            self._seed_exp(1, 1, i + 1, f"Python相关的讨论第{i+1}次")

        hits = self.ms.search(1, ["Python"], limit=3)
        self.assertEqual(len(hits), 3)

    def test_search_includes_memos(self):
        self.ms.add_memo(1, 1, "用户的Python项目需要重构")
        self._seed_exp(1, 1, 1, "讨论了Rust")

        hits = self.ms.search(1, ["Python"])
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["type"], "memo")
        self.assertIn("重构", hits[0]["content"])

    # ---- 3b. 向量嵌入 ----

    def test_cosine_similarity_identical(self):
        v = [0.1, 0.2, 0.3]
        sim = MemorySystem._cosine_similarity(v, v)
        self.assertAlmostEqual(sim, 1.0)

    def test_cosine_similarity_orthogonal(self):
        sim = MemorySystem._cosine_similarity([1.0, 0.0], [0.0, 1.0])
        self.assertAlmostEqual(sim, 0.0)

    def test_cosine_similarity_opposite(self):
        sim = MemorySystem._cosine_similarity([1.0, 0.0], [-1.0, 0.0])
        self.assertAlmostEqual(sim, -1.0)

    def test_cosine_similarity_empty(self):
        sim = MemorySystem._cosine_similarity([], [1.0])
        self.assertEqual(sim, 0.0)

    def test_pack_unpack_roundtrip(self):
        vec = [0.5, -0.25, 0.0, 1.0, 3.14159]
        blob = MemorySystem._pack_embedding(vec)
        self.assertEqual(len(blob), 4 * len(vec))  # 4 bytes per float
        unpacked = MemorySystem._unpack_embedding(blob)
        for a, b in zip(vec, unpacked):
            self.assertAlmostEqual(a, b, places=5)

    def _seed_embed(self, uid=1, cid=1, round_=1, vec=None):
        """向 memory_embeds 表写入原始消息 embedding"""
        if vec is None:
            vec = [0.0] * 4
        blob = MemorySystem._pack_embedding(vec)
        conn = self.db._get_connection()
        conn.execute(
            "INSERT OR REPLACE INTO memory_embeds (user_id, chat_id, round, embedding) "
            "VALUES (?, ?, ?, ?)", (uid, cid, round_, blob),
        )
        conn.commit()

    def test_search_vector_only(self):
        """embedding_query 为 list[float] 时走纯向量搜索"""
        from apps.dsn.config import Config
        old_enabled = Config.MEMORY_EMBEDDING_ENABLED
        Config.MEMORY_EMBEDDING_ENABLED = True

        try:
            ec = _FakeEmbeddingClient()
            ms = MemorySystem(db=self.db, summary_model=self.summary_model, embedding_client=ec)
            self._seed_exp(1, 1, 1, "用户喜欢Python编程")
            self._seed_exp(1, 1, 2, "讨论过Rust语言特性")
            self._seed_embed(1, 1, 1, [0.9, 0.1, 0.0, 0.0])
            self._seed_embed(1, 1, 2, [0.1, 0.0, 0.9, 0.0])

            query_vec = [0.95, 0.05, 0.0, 0.0]
            hits = ms.search(1, [], embedding_query=query_vec, threshold=0.5)
            self.assertEqual(len(hits), 1)
            self.assertIn("Python", hits[0]["content"])
            self.assertGreater(hits[0]["score"], 0.8)
        finally:
            Config.MEMORY_EMBEDDING_ENABLED = old_enabled

    def test_search_hybrid_keyword_and_vector(self):
        """关键词 + 向量混合搜索"""
        from apps.dsn.config import Config
        old_enabled = Config.MEMORY_EMBEDDING_ENABLED
        Config.MEMORY_EMBEDDING_ENABLED = True
        try:
            ec = _FakeEmbeddingClient()
            ms = MemorySystem(db=self.db, summary_model=self.summary_model, embedding_client=ec)
            self._seed_exp(1, 1, 1, "Python和FastAPI后端开发")
            self._seed_exp(1, 1, 2, "Rust并发与系统编程")
            self._seed_embed(1, 1, 1, [1.0, 0.0, 0.0])
            self._seed_embed(1, 1, 2, [0.0, 1.0, 0.0])

            # query 向量与 round2 强匹配(cos≈1), 与 round1 正交(cos=0)
            hits = ms.search(1, ["Rust", "并发"], embedding_query=[0.0, 1.0, 0.0], threshold=0.3)
            self.assertEqual(len(hits), 1)
            self.assertIn("Rust", hits[0]["content"])
        finally:
            Config.MEMORY_EMBEDDING_ENABLED = old_enabled

    def test_search_fallback_when_no_embedding(self):
        """有 embedding_query 但 memory 无 blob 时应跳过 vector 部分"""
        from apps.dsn.config import Config
        old_enabled = Config.MEMORY_EMBEDDING_ENABLED
        Config.MEMORY_EMBEDDING_ENABLED = True
        try:
            ec = _FakeEmbeddingClient()
            ms = MemorySystem(db=self.db, summary_model=self.summary_model, embedding_client=ec)
            self._seed_exp(1, 1, 1, "用户喜欢Python编程")
            # 不设 embedding BLOB → vec_score = 0，但 keyword 仍匹配
            hits = ms.search(1, ["Python"], embedding_query=[0.9, 0.1], threshold=0.3)
            self.assertEqual(len(hits), 1)
            self.assertIn("Python", hits[0]["content"])
        finally:
            Config.MEMORY_EMBEDDING_ENABLED = old_enabled

    def test_embed_raw_round(self):
        """验证 summarize_turn 将原始对话 embedding 写入 memory_embeds"""
        from apps.dsn.config import Config
        old_enabled = Config.MEMORY_EMBEDDING_ENABLED
        Config.MEMORY_EMBEDDING_ENABLED = True
        try:
            ec = _FakeEmbeddingClient()
            ms = MemorySystem(db=self.db, summary_model=self.summary_model, embedding_client=ec)
            mid = ms.summarize_turn(1, 1, 99, "测试文本", "回复内容", async_mode=False)
            self.assertIsNotNone(mid)

            conn = self.db._get_connection()
            row = conn.execute(
                "SELECT embedding FROM memory_embeds "
                "WHERE user_id = 1 AND chat_id = 1 AND round = 99",
            ).fetchone()
            self.assertIsNotNone(row)
            unpacked = MemorySystem._unpack_embedding(row["embedding"])
            self.assertEqual(len(unpacked), 5)
            self.assertAlmostEqual(unpacked[0], 0.5)
        finally:
            Config.MEMORY_EMBEDDING_ENABLED = old_enabled


class _FakeEmbeddingClient:
    """mock EmbeddingClient，返回固定的 5 维向量"""
    def embed(self, text: str) -> list[float]:
        return [0.5, 0.3, 0.1, 0.05, 0.02]
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


    # ---- 4. 标签处理 ----

    def test_handle_tags_recall(self):
        self._seed_exp(1, 1, 1, "用户喜欢Python")
        text = '你说得对！<recall>{"keywords": ["Python"], "count": 3}</recall>'

        result = self.ms.handle_tags(1, 1, text)
        self.assertNotIn("你说得对！<recall>", result)  # original tag stripped
        self.assertNotIn('"keywords"', result)           # JSON stripped
        self.assertIn("[记忆检索结果]", result)

    def test_handle_tags_memo(self):
        text = "好的，我记住了。<memo>用户下周五截止</memo>还有什么？"

        result = self.ms.handle_tags(1, 1, text)
        self.assertNotIn("<memo>", result)
        self.assertIn("好的，我记住了。", result)
        self.assertIn("还有什么？", result)

        # memo should be persisted
        history = [{"role": "user", "content": "hi"}]
        result = self.ms.assemble_context(1, history)
        self.assertIn("[备忘]", result[0]["content"])
        self.assertIn("用户下周五截止", result[0]["content"])

    def test_handle_tags_multiple_recalls(self):
        self._seed_exp(1, 1, 1, "Python异步")
        self._seed_exp(1, 1, 2, "Rust并发")
        text = (
            '先查Python: <recall>{"keywords": ["Python"], "count": 1}</recall>\n'
            '再查Rust: <recall>{"keywords": ["Rust"], "count": 1}</recall>'
        )
        result = self.ms.handle_tags(1, 1, text)
        self.assertNotIn('"keywords"', result)  # original JSON stripped
        self.assertIn("[记忆检索结果]", result)  # results present

    def test_handle_tags_detail(self):
        self._seed_exp(1, 1, 1, "讨论")
        text = '<recall>{"detail": [1]}</recall>'
        result = self.ms.handle_tags(1, 1, text)
        self.assertIn("[记忆细节还原]", result)

    # ---- 5. summarize_turn ----

    def test_summarize_turn_sync(self):
        mid = self.ms.summarize_turn(1, 1, 1, "你好", "你好！有什么可以帮你的？", async_mode=False)
        self.assertIsInstance(mid, int)
        self.assertGreater(mid, 0)

    def test_summarize_turn_persisted(self):
        self.ms.summarize_turn(1, 1, 1, "Python真棒", "是的！", async_mode=False)

        history = [{"role": "user", "content": "msg"} for _ in range(100)]
        result = self.ms.assemble_context(1, history)
        self.assertIn("[记忆 · 轮次1]", result[0]["content"])


if __name__ == "__main__":
    unittest.main()
