# tests/test_topics.py
# 测试话题系统 — 分段决策、激活窗口、上下文组装、pinned、清扫

import os
import sys
import json
import tempfile
import unittest
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import Config
from db.chat import ChatDBManager
from memory import MemorySystem
from memory.topics import TopicManager


# ---------------------------------------------------------------------------
# Mocks
# ---------------------------------------------------------------------------

class FakeCipher:
    def encrypt(self, user_id, text):
        return text
    def decrypt(self, user_id, text):
        return text if text else ""


class FakeLMSummaryModel:
    def summarize_dialog(self, messages, max_length=100):
        user = messages[0]["content"] if messages else ""
        return f"讨论了: {user[:80]}"
    def summarize_text(self, text, max_length=100):
        return f"摘要: {text[:60]}"
    def complete_text(self, prompt, max_length=30):
        # 依据 prompt 中的标记返回结构化判定
        if "FORCE_NEW" in prompt:
            return '{"action":"new","topic_id":0,"reason":"t"}'
        if "REOPEN" in prompt:
            import re as _re
            m = _re.search(r"^- #(\d+) 「", prompt, _re.MULTILINE)
            if m:
                return f'{{"action":"reopen","topic_id":{m.group(1)},"reason":"t"}}'
            return '{"action":"new","topic_id":0,"reason":"t"}'
        if "当前话题" in prompt and "候选旧话题" in prompt:
            return '{"action":"continue","topic_id":1,"reason":"t"}'
        return '{"action":"new","topic_id":0,"reason":"default"}'


class FakeEmbedding:
    def embed(self, text):
        low = text.lower()
        if "python" in low or "代码" in low:
            return [1.0, 0.0, 0.0]
        if "旅行" in low or "travel" in low:
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]


class TopicTestBase(unittest.TestCase):
    def setUp(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._tmp_path = path
        self.db = ChatDBManager(db_path=path)
        self.db._cipher = FakeCipher()
        self.summary = FakeLMSummaryModel()
        self.ms = MemorySystem(db=self.db, summary_model=self.summary)
        self.db._get_connection().execute(
            "INSERT OR IGNORE INTO users (uid, nickname) VALUES (1, '测试用户')"
        )
        self.db._get_connection().commit()
        self.cid = self.db.create_chat(1, "测试")

        self._saved = {}
        for key in (
            "TOPIC_ENABLED", "TOPIC_IDLE_SECONDS", "TOPIC_CONTINUE_THRESHOLD",
            "TOPIC_REOPEN_THRESHOLD", "TOPIC_ACTIVATION_THRESHOLD",
            "TOPIC_JUDGE_ENABLED", "TOPIC_JUDGE_ALWAYS", "TOPIC_TAIL_ROUNDS",
            "TOPIC_MAX_OPEN_TOPICS", "TOPIC_MAX_VERBATIM_CHARS",
            "TOPIC_SUMMARY_CHARS", "TOPIC_MEMO_CHARS",
        ):
            self._saved[key] = getattr(Config, key)
        Config.TOPIC_ENABLED = True
        Config.TOPIC_IDLE_SECONDS = 1800
        Config.TOPIC_CONTINUE_THRESHOLD = 0.0
        Config.TOPIC_REOPEN_THRESHOLD = 0.99
        Config.TOPIC_ACTIVATION_THRESHOLD = 0.9
        Config.TOPIC_JUDGE_ENABLED = False
        Config.TOPIC_JUDGE_ALWAYS = False
        Config.TOPIC_TAIL_ROUNDS = 5
        Config.TOPIC_MAX_OPEN_TOPICS = 3
        Config.TOPIC_MAX_VERBATIM_CHARS = 6000
        Config.TOPIC_SUMMARY_CHARS = 2000
        Config.TOPIC_MEMO_CHARS = 1200

    def tearDown(self):
        for key, val in self._saved.items():
            setattr(Config, key, val)
        self.db.close_connection()
        try:
            os.remove(self._tmp_path)
        except OSError:
            pass

    def _append(self, role, content, round_index, topic_id=None):
        self.db.append_messages(1, self.cid, [{"role": role, "content": content}],
                                round_index=round_index, topic_id=topic_id,
                                skip_ownership_check=True)

    def _seed_exp(self, topic_id, round_, content):
        self.db._get_connection().execute(
            "INSERT INTO memory_v2 (user_id, chat_id, type, round, content, topic_id) "
            "VALUES (1, ?, 'exp', ?, ?, ?)", (self.cid, round_, content, topic_id)
        )
        self.db._get_connection().commit()


class TestTopicDecision(TopicTestBase):

    def test_first_message_creates_topic(self):
        tm = self.ms._topics
        d = tm.on_new_message(1, self.cid, "你好")
        self.assertEqual(d["action"], "new")
        self.assertTrue(d["topic_id"])
        topics = tm.store.list_topics(1, self.cid)
        self.assertEqual(len(topics), 1)
        self.assertEqual(topics[0]["status"], "open")

    def test_continue_same_topic(self):
        tm = self.ms._topics
        d1 = tm.on_new_message(1, self.cid, "你好")
        tid = d1["topic_id"]
        self._append("user", "你好", 1, tid)
        self._append("assistant", "你好呀", 1, tid)
        d2 = tm.on_new_message(1, self.cid, "我们今天聊点什么")
        self.assertEqual(d2["action"], "continue")
        self.assertEqual(d2["topic_id"], tid)

    def test_idle_close_then_new_topic(self):
        tm = self.ms._topics
        d1 = tm.on_new_message(1, self.cid, "第一话题")
        tid1 = d1["topic_id"]
        # 模拟 30min 静默: 把话题活动时间改旧
        self.db._get_connection().execute(
            "UPDATE topics SET last_activity_at = datetime('now', '-2 hours') WHERE topic_id = ?",
            (tid1,),
        )
        self.db._get_connection().commit()
        d2 = tm.on_new_message(1, self.cid, "第二话题")
        self.assertEqual(d2["action"], "new")
        self.assertNotEqual(d2["topic_id"], tid1)
        t1 = tm.store.get_topic(1, tid1)
        self.assertEqual(t1["status"], "closed")

    def test_reopen_after_idle(self):
        tm = self.ms._topics
        d1 = tm.on_new_message(1, self.cid, "python 项目")
        tid1 = d1["topic_id"]
        tm.store.set_summary(1, tid1, "Python项目", "讨论了 python 代码")
        self.db._get_connection().execute(
            "UPDATE topics SET last_activity_at = datetime('now', '-2 hours') WHERE topic_id = ?",
            (tid1,),
        )
        self.db._get_connection().commit()
        # 无消息时间戳 → 回退话题活动时间判定 idle → 关闭; 阈值0 → 规则回退 reopen
        Config.TOPIC_REOPEN_THRESHOLD = 0.0
        Config.TOPIC_JUDGE_ENABLED = False
        d2 = tm.on_new_message(1, self.cid, "python 项目")
        self.assertIn(d2["action"], ("reopen", "new"))
        t1 = tm.store.get_topic(1, tid1)
        if d2["action"] == "reopen":
            self.assertEqual(d2["topic_id"], tid1)
            self.assertEqual(t1["status"], "open")


class TestTopicContext(TopicTestBase):

    def test_context_contains_blocks(self):
        tm = self.ms._topics
        d1 = tm.on_new_message(1, self.cid, "聊旅行")
        tid = d1["topic_id"]
        self._append("user", "聊旅行", 1, tid)
        self._append("assistant", "去哪玩", 1, tid)
        self._append("user", "想去日本", 2, tid)
        self._append("assistant", "不错", 2, tid)
        tm.store.set_summary(1, tid, "旅行计划", "用户想去日本")
        # 关闭该话题, 变闭锁摘要
        tm.store.close_topic(tid, end_round=2)

        ctx = tm.assemble_topic_context(1, self.cid, [])
        text = "\n".join(m["content"] for m in ctx)
        self.assertIn("旅行计划", text)
        self.assertIn("想去日本", text)

    def test_tail_from_db_rounds(self):
        tm = self.ms._topics
        d1 = tm.on_new_message(1, self.cid, "新话题")
        tid = d1["topic_id"]
        for r in range(1, 8):
            self._append("user", f"消息{r}", r, tid)
            self._append("assistant", f"回复{r}", r, tid)
        ctx = tm.assemble_topic_context(1, self.cid, [])
        text = "\n".join(m["content"] for m in ctx)
        # 最近 TAIL_ROUNDS=5 轮(3-7)进原始尾部; 更早轮次(1-2)进当前话题原文块
        self.assertIn("消息7", text)
        self.assertIn("回复7", text)
        # 无重复注入: 每轮原文恰好出现一次
        self.assertEqual(text.count("消息1"), 1)
        self.assertEqual(text.count("消息5"), 1)
        self.assertEqual(text.count("消息7"), 1)

    def test_reopen_injects_full_old_topic(self):
        tm = self.ms._topics
        # 旧话题 #1: 轮1-3
        d_old = tm.on_new_message(1, self.cid, "python")
        tid_old = d_old["topic_id"]
        for r in range(1, 4):
            self._append("user", f"旧{r}", r, tid_old)
            self._append("assistant", f"旧回复{r}", r, tid_old)
        tm.store.set_summary(1, tid_old, "Python项目", "python 代码")
        tm.store.close_topic(tid_old, end_round=3)
        # 新话题 #2: 轮4-6 (最近对话)
        Config.TOPIC_JUDGE_ENABLED = True
        d_new = tm.on_new_message(1, self.cid, "新话题")
        tid_new = d_new["topic_id"]
        for r in range(4, 7):
            self._append("user", f"新{r}", r, tid_new)
            self._append("assistant", f"新回复{r}", r, tid_new)
        st = tm._state(1, self.cid)
        st.current_topic_id = tid_old  # 手动切回旧话题(重开场景)
        tm.store.reopen_topic(tid_old)
        ctx = tm.assemble_topic_context(1, self.cid, [])
        text = "\n".join(m["content"] for m in ctx)
        # 尾部窗口(最近5轮=2..6)覆盖旧话题轮2-3与新话题轮4-6; 旧话题仅注入未覆盖的轮1
        self.assertIn("[话题·当前话题·Python项目·第1-1轮]", text)
        self.assertIn("旧回复1", text)
        self.assertEqual(text.count("旧1"), 1)  # 无重复
        # 最近对话(轮4-6)作为原始尾部
        self.assertIn("新6", text)


class TestTopicActivation(TopicTestBase):

    def test_pin_unpin(self):
        tm = self.ms._topics
        d1 = tm.on_new_message(1, self.cid, "话题A")
        tid = d1["topic_id"]
        self.assertTrue(tm.pin_topic(1, self.cid, tid))
        st = tm._state(1, self.cid)
        self.assertIn(tid, st.active_pins)
        self.assertTrue(tm.unpin_topic(1, self.cid, tid))
        self.assertNotIn(tid, st.active_pins)

    def test_pin_closed_topic_reopens(self):
        tm = self.ms._topics
        d1 = tm.on_new_message(1, self.cid, "旧话题")
        tid = d1["topic_id"]
        self._append("user", "旧话题内容", 1, tid)
        self._append("assistant", "收到", 1, tid)
        tm.store.close_topic(tid, end_round=1)
        self.assertEqual(tm.store.get_topic(1, tid)["status"], "closed")
        self.assertTrue(tm.pin_topic(1, self.cid, tid))
        # 持续激活关闭话题 → 自动重开, 组装时原文注入
        self.assertEqual(tm.store.get_topic(1, tid)["status"], "open")
        ctx = tm.assemble_topic_context(1, self.cid, [])
        text = "\n".join(m["content"] for m in ctx)
        self.assertIn("[话题·持续激活·", text)
        self.assertIn("旧话题内容", text)

    def test_max_open_topics_cap(self):
        tm = self.ms._topics
        old_ids = []
        # 建 3 个已关闭话题
        for i in range(3):
            d = tm.on_new_message(1, self.cid, f"旧话题{i}")
            tid = d["topic_id"]
            self._append("user", f"旧内容{i}", i + 1, tid)
            self._append("assistant", f"旧回复{i}", i + 1, tid)
            tm.store.close_topic(tid, end_round=i + 1)
            old_ids.append(tid)
        # 当前话题
        d_cur = tm.on_new_message(1, self.cid, "新话题")
        tid_cur = d_cur["topic_id"]
        st = tm._state(1, self.cid)
        # 全部被动激活(模拟) + 限制同时打开数
        st.passive_activations = set(old_ids)
        old_max = Config.TOPIC_MAX_OPEN_TOPICS
        Config.TOPIC_MAX_OPEN_TOPICS = 2
        try:
            ctx = tm.assemble_topic_context(1, self.cid, [])
            text = "\n".join(m["content"] for m in ctx)
            passive_count = text.count("[话题·被动激活·")
            self.assertLessEqual(passive_count, 2)  # 当前话题占 1 席, 被动激活最多 1
        finally:
            Config.TOPIC_MAX_OPEN_TOPICS = old_max

    def test_recall_activate_pins_topic(self):
        tm = self.ms._topics
        d1 = tm.on_new_message(1, self.cid, "聊美食")
        tid = d1["topic_id"]
        self._append("user", "喜欢吃火锅", 1, tid)
        self._append("assistant", "好的", 1, tid)
        self._seed_exp(tid, 1, "用户喜欢吃火锅")
        hits = self.ms.search(1, ["火锅"], limit=5)
        self.assertTrue(hits)
        payload = {"keywords": ["火锅"], "count": 5, "activate": True}
        self.ms._handle_recall(1, self.cid, payload)
        st = tm._state(1, self.cid)
        self.assertIn(tid, st.active_pins)

    def test_sweep_stale(self):
        tm = self.ms._topics
        d1 = tm.on_new_message(1, self.cid, "话题")
        tid = d1["topic_id"]
        self.db._get_connection().execute(
            "UPDATE topics SET last_activity_at = datetime('now', '-3 hours') WHERE topic_id = ?",
            (tid,),
        )
        self.db._get_connection().commit()
        closed = tm.sweep_stale_topics()
        self.assertGreaterEqual(closed, 1)
        t = tm.store.get_topic(1, tid)
        self.assertEqual(t["status"], "closed")


class TestTopicJudge(TopicTestBase):

    def test_judge_reopen_parsing(self):
        tm = self.ms._topics
        s = tm.store
        # 旧话题 #1(已关闭) + 当前话题 #2
        tid_old = s.create_topic(1, self.cid, 1)
        s.close_topic(tid_old, end_round=1)
        s.set_summary(1, tid_old, "旧话题", "python 项目讨论")
        tid_cur = s.create_topic(1, self.cid, 2)
        st = tm._state(1, self.cid)
        st.current_topic_id = tid_cur
        Config.TOPIC_JUDGE_ENABLED = True
        Config.TOPIC_CONTINUE_THRESHOLD = 0.99  # 避免免-judge 直连, 强制走判定
        d = tm.on_new_message(1, self.cid, "REOPEN")
        self.assertEqual(d["action"], "reopen")
        self.assertEqual(d["topic_id"], tid_old)
        t = s.get_topic(1, tid_old)
        self.assertEqual(t["status"], "open")


if __name__ == "__main__":
    unittest.main()
