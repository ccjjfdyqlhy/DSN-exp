# tests/test_memory_recall.py
# 动态记忆召回系统集成测试

import os
import sys
import unittest
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from chatdbmgr import ChatDBManager
from memory_recall import MemoryRecallEngine


class TestMemoryRecallEngine(unittest.TestCase):
    """测试 MemoryRecallEngine 的核心功能"""

    @classmethod
    def setUpClass(cls):
        cls.db_path = tempfile.mktemp(suffix=".db")
        cls.db = ChatDBManager(cls.db_path)
        cls.engine = MemoryRecallEngine(cls.db)

    @classmethod
    def tearDownClass(cls):
        cls.db.close_connection()
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)

    def setUp(self):
        self.user_id = 1
        self.db.add_or_update_user(self.user_id, "test_user")
        self.chat_id = self.db.create_chat(self.user_id, "test_chat")

    def tearDown(self):
        self.db.delete_chat(self.user_id, self.chat_id)

    def _add_messages(self, messages: list[tuple[str, str]], round_index: int = None):
        """添加消息到数据库"""
        formatted = [{"role": r, "content": c} for r, c in messages]
        self.db.append_messages(self.user_id, self.chat_id, formatted, round_index=round_index)

    def _add_memory(self, round_index: int, summary: str, keywords: str = "",
                    msg_start: int = None, msg_end: int = None):
        """添加记忆条目"""
        return self.db.save_memory(
            self.user_id, self.chat_id, round_index, summary,
            keywords=keywords, message_start_id=msg_start, message_end_id=msg_end
        )

    # ── 关键词提取 ──

    def test_extract_keywords_from_summary(self):
        summary = "讨论了Python类型系统的基本概念\n[关键词: Python, 类型系统, 泛型]"
        kws = MemoryRecallEngine.extract_keywords_from_summary(summary)
        self.assertIn("python", kws)
        self.assertIn("类型系统", kws)
        self.assertIn("泛型", kws)

    def test_extract_keywords_empty(self):
        summary = "一段没有关键词的摘要"
        kws = MemoryRecallEngine.extract_keywords_from_summary(summary)
        self.assertEqual(kws, "")

    def test_strip_keywords_from_summary(self):
        summary = "讨论了Python类型系统\n[关键词: Python, 泛型]"
        clean = MemoryRecallEngine.strip_keywords_from_summary(summary)
        self.assertEqual(clean, "讨论了Python类型系统")
        self.assertNotIn("[关键词", clean)

    def test_extract_keywords_english(self):
        summary = "Discussed Python type system basics\n[keywords: python, types, generics]"
        kws = MemoryRecallEngine.extract_keywords_from_summary(summary)
        self.assertIn("python", kws)
        self.assertIn("types", kws)
        self.assertIn("generics", kws)

    # ── 检索 ──

    def test_search_by_keyword(self):
        self._add_memory(1, "一轮关于 Python 类型注解的讨论", keywords="python,类型,注解")
        self._add_memory(2, "讨论文件系统设计", keywords="文件系统,设计")
        self._add_memory(3, "Python 高级特性 — 装饰器与元类", keywords="python,装饰器,元类")

        hits = self.db.search_memories(self.user_id, self.chat_id, ["python"], count=5)
        self.assertEqual(len(hits), 2, f"应该找到2条Python相关记忆，实际找到{len(hits)}条")
        self.assertIn(1, [h["round_index"] for h in hits])
        self.assertIn(3, [h["round_index"] for h in hits])

    def test_search_no_match(self):
        self._add_memory(1, "Python 讨论", keywords="python")
        hits = self.db.search_memories(self.user_id, self.chat_id, ["rust"], count=5)
        self.assertEqual(len(hits), 0)

    def test_search_multiple_keywords(self):
        self._add_memory(1, "Python 类型系统", keywords="python,类型")
        self._add_memory(2, "Rust 类型系统", keywords="rust,类型")
        self._add_memory(3, "Python 异步编程", keywords="python,async")

        hits = self.db.search_memories(self.user_id, self.chat_id, ["python", "类型"], count=5)
        self.assertGreaterEqual(len(hits), 1)
        # Python+类型 should match round 1 the most (both keywords hit)
        top = hits[0]
        self.assertEqual(top["round_index"], 1)

    def test_search_respects_count(self):
        for i in range(1, 10):
            self._add_memory(i, f"讨论 Python 话题 {i}", keywords="python")
        hits = self.db.search_memories(self.user_id, self.chat_id, ["python"], count=3)
        self.assertEqual(len(hits), 3)

    # ── 细节还原 ──

    def test_get_detail(self):
        self._add_messages([("user", "Python 的类型注解怎么用？"), ("assistant", "Python 使用 : 语法声明类型...")], round_index=5)
        self._add_messages([("user", "那泛型呢？"), ("assistant", "泛型通过 TypeVar 实现...")], round_index=6)

        detail = self.engine.get_detail(self.user_id, self.chat_id, [5])
        self.assertIn(5, detail)
        self.assertEqual(len(detail[5]), 2)
        self.assertEqual(detail[5][0]["role"], "user")
        self.assertIn("类型注解", detail[5][0]["content"])

    def test_get_multiple_rounds(self):
        self._add_messages([("user", "Q1"), ("assistant", "A1")], round_index=1)
        self._add_messages([("user", "Q3"), ("assistant", "A3")], round_index=3)
        self._add_messages([("user", "Q5"), ("assistant", "A5")], round_index=5)

        detail = self.engine.get_detail(self.user_id, self.chat_id, [1, 3, 5])
        self.assertEqual(len(detail), 3)
        self.assertIn(1, detail)
        self.assertIn(3, detail)
        self.assertIn(5, detail)

    # ── 格式化 ──

    def test_format_search_results_found(self):
        hits = [{
            "round_index": 5, "summary": "讨论了Python类型系统",
            "keywords": "python,类型", "score": 1.85,
            "created_at": "2026-05-10", "message_start_id": 10, "message_end_id": 15,
        }]
        result = MemoryRecallEngine.format_search_results(hits, ["python"])
        self.assertIn("找到 1 条", result)
        self.assertIn("#5", result)
        self.assertIn("Python类型系统", result)

    def test_format_search_results_empty(self):
        result = MemoryRecallEngine.format_search_results([], ["rust"])
        self.assertIn("未找到", result)
        self.assertIn("rust", result)

    def test_format_detail_results(self):
        detail = {
            5: [{"role": "user", "content": "测试问题", "timestamp": "2026-05-10"}]
        }
        result = MemoryRecallEngine.format_detail_results(detail)
        self.assertIn("第5轮", result)
        self.assertIn("测试问题", result)

    # ── handle_recall 端到端 ──

    def test_handle_recall_search(self):
        self._add_memory(1, "Python 学习讨论", keywords="python,学习")
        self._add_messages([("user", "怎么学Python？"), ("assistant", "从基础开始...")], round_index=1)

        result = self.engine.handle_recall(
            self.user_id, self.chat_id,
            {"keywords": ["python"], "count": 3}
        )
        self.assertIsNotNone(result)
        self.assertIn("Python 学习讨论", result)

    def test_handle_recall_detail(self):
        self._add_messages([("user", "问题1"), ("assistant", "回答1")], round_index=7)

        result = self.engine.handle_recall(
            self.user_id, self.chat_id,
            {"detail": [7]}
        )
        self.assertIsNotNone(result)
        self.assertIn("第7轮", result)
        self.assertIn("回答1", result)

    def test_handle_recall_mixed(self):
        self._add_memory(1, "文件管理讨论", keywords="文件,管理")
        self._add_messages([("user", "怎么读文件？"), ("assistant", "用 open()...")], round_index=1)

        result = self.engine.handle_recall(
            self.user_id, self.chat_id,
            {"keywords": ["文件"], "detail": True}
        )
        self.assertIsNotNone(result)
        self.assertIn("文件管理讨论", result)   # search result
        self.assertIn("怎么读文件？", result)    # detail result

    def test_handle_recall_no_match(self):
        result = self.engine.handle_recall(
            self.user_id, self.chat_id,
            {"keywords": ["nonexistent_topic"], "count": 3}
        )
        self.assertIsNotNone(result)
        self.assertIn("未找到", result)

    # ── 数据库扩展 ──

    def test_memories_table_has_new_columns(self):
        memory_id = self._add_memory(1, "测试记忆", keywords="test,memory",
                                     msg_start=10, msg_end=15)
        memories = self.db.get_memories(self.user_id, self.chat_id)
        self.assertGreater(len(memories), 0)
        mem = memories[0]
        self.assertEqual(mem["keywords"], "test,memory")
        self.assertEqual(mem["message_start_id"], 10)
        self.assertEqual(mem["message_end_id"], 15)

    def test_messages_table_has_round_index(self):
        self._add_messages([("user", "hello")], round_index=42)
        detail = self.engine.get_detail(self.user_id, self.chat_id, [42])
        self.assertIn(42, detail)
        self.assertEqual(detail[42][0]["role"], "user")
        self.assertEqual(detail[42][0]["content"], "hello")

    def test_get_last_message_ids(self):
        self._add_messages([("user", "msg1"), ("assistant", "msg2")], round_index=1)
        min_id, max_id = self.db.get_last_message_ids(self.chat_id, count=2)
        self.assertIsNotNone(min_id)
        self.assertIsNotNone(max_id)
        self.assertGreaterEqual(max_id, min_id)

    # ── 旧接口兼容 ──

    def test_old_get_memories_still_works(self):
        self._add_memory(1, "旧格式摘要")
        memories = self.db.get_memories(self.user_id, self.chat_id)
        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0]["round_index"], 1)
        self.assertEqual(memories[0]["summary"], "旧格式摘要")
        # 新字段应有默认值
        self.assertEqual(memories[0]["keywords"], "")
        self.assertIsNone(memories[0]["message_start_id"])


if __name__ == "__main__":
    unittest.main()
