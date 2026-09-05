# apps/emotion_exp/topic_manager.py
# 基于 harness.context_assembly 的轻量话题管理器
# 维护本地/跨轮次话题切分、状态机（open/closed/pinned）与预算剪裁组装

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from harness.context_assembly import (
    ContextBudget,
    ContextSegment,
    PRIORITY_ACTIVE,
    PRIORITY_CURRENT,
    PRIORITY_MEMO,
    PRIORITY_SUMMARY,
    SEG_MEMO,
    SEG_SUMMARY,
    SEG_VERBATIM,
    SegmentedContextAssembler,
)
from harness.models.base import ChatMessage
from harness.store.sqlite import SqliteStore



@dataclass
class Topic:
    topic_id: str
    title: str
    status: str = "open"  # open | closed
    is_pinned: bool = False
    messages: List[ChatMessage] = field(default_factory=list)
    summary: str = ""
    last_active_at: float = field(default_factory=time.time)
    def add_message(self, msg: ChatMessage) -> None:
        self.messages.append(msg)
        self.last_active_at = time.time()



class TopicStore:
    """话题持久化层，基于 harness SqliteStore 存储 topics / memos / emotion"""

    def __init__(self, store: Optional[SqliteStore] = None, *, db_path: str = ":memory:"):
        self.store = store or SqliteStore(db_path)
        self._init_tables()

    def _init_tables(self) -> None:
        conn = self.store.get_connection()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS exp_topics (
                topic_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                is_pinned INTEGER NOT NULL DEFAULT 0,
                summary TEXT DEFAULT '',
                last_active_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS exp_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_exp_msgs_topic ON exp_messages(topic_id, id);
            CREATE TABLE IF NOT EXISTS exp_memos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS exp_emotion (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                joy REAL NOT NULL,
                sorrow REAL NOT NULL,
                anger REAL NOT NULL,
                fear REAL NOT NULL,
                meta REAL NOT NULL,
                updated_at REAL NOT NULL
            );
        """)
        conn.commit()

    def save_topic(self, topic: Topic) -> None:
        self.store.execute(
            "INSERT INTO exp_topics (topic_id, title, status, is_pinned, summary, last_active_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(topic_id) DO UPDATE SET "
            "title=excluded.title, status=excluded.status, is_pinned=excluded.is_pinned, "
            "summary=excluded.summary, last_active_at=excluded.last_active_at",
            (topic.topic_id, topic.title, topic.status, int(topic.is_pinned), topic.summary, topic.last_active_at),
        )

    def append_message(self, topic_id: str, role: str, content: str) -> None:
        self.store.execute(
            "INSERT INTO exp_messages (topic_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (topic_id, role, content, time.time()),
        )

    def load_all_topics(self) -> Dict[str, Topic]:
        rows = self.store.execute("SELECT topic_id, title, status, is_pinned, summary, last_active_at FROM exp_topics")
        topics: Dict[str, Topic] = {}
        for r in rows:
            tid = r["topic_id"]
            top = Topic(
                topic_id=tid,
                title=r["title"],
                status=r["status"],
                is_pinned=bool(r["is_pinned"]),
                summary=r["summary"] or "",
                last_active_at=r["last_active_at"],
            )
            # 加载该话题的消息
            msg_rows = self.store.execute(
                "SELECT role, content FROM exp_messages WHERE topic_id = ? ORDER BY id", (tid,)
            )
            for m in msg_rows:
                top.messages.append(ChatMessage(role=m["role"], content=m["content"]))
            topics[tid] = top
        return topics

    def save_memo(self, content: str) -> None:
        self.store.execute("INSERT INTO exp_memos (content) VALUES (?)", (content,))

    def load_memos(self) -> List[str]:
        rows = self.store.execute("SELECT content FROM exp_memos ORDER BY id")
        return [r["content"] for r in rows]

    def save_emotion(self, joy: float, sorrow: float, anger: float, fear: float, meta: float) -> None:
        self.store.execute(
            "INSERT INTO exp_emotion (id, joy, sorrow, anger, fear, meta, updated_at) "
            "VALUES (1, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "joy=excluded.joy, sorrow=excluded.sorrow, anger=excluded.anger, "
            "fear=excluded.fear, meta=excluded.meta, updated_at=excluded.updated_at",
            (joy, sorrow, anger, fear, meta, time.time()),
        )

    def load_emotion(self) -> Optional[Dict[str, float]]:
        rows = self.store.execute("SELECT joy, sorrow, anger, fear, meta FROM exp_emotion WHERE id = 1")
        if rows:
            r = rows[0]
            return {
                "joy": r["joy"],
                "sorrow": r["sorrow"],
                "anger": r["anger"],
                "fear": r["fear"],
                "meta": r["meta"],
            }
        return None

class HarnessTopicContextManager:
    """结合 harness 话题上下文装配器的管理组件"""

    def __init__(
        self,
        budget: Optional[ContextBudget] = None,
        idle_timeout_seconds: float = 1800.0,
        store: Optional[TopicStore] = None,
    ):
        self.budget = budget or ContextBudget(
            memo_chars=2000,
            summary_chars=4000,
            verbatim_chars=16000,
            tail_rounds=3,
        )
        self.assembler = SegmentedContextAssembler(self.budget)
        self.idle_timeout_seconds = idle_timeout_seconds
        self.store = store

        if self.store:
            self.topics = self.store.load_all_topics()
            self.memos = self.store.load_memos()
            # 尝试寻找最近活跃的 open 话题作为 current_topic_id
            open_topics = [t for t in self.topics.values() if t.status == "open"]
            if open_topics:
                open_topics.sort(key=lambda t: t.last_active_at, reverse=True)
                self.current_topic_id = open_topics[0].topic_id
            else:
                self.current_topic_id = None
        else:
            self.topics = {}
            self.current_topic_id = None
            self.memos = []

    def add_memo(self, text: str) -> None:
        if text not in self.memos:
            self.memos.append(text)
            if self.store:
                self.store.save_memo(text)

    def get_or_create_current_topic(self, user_text: str = "") -> Topic:
        now = time.time()
        if self.current_topic_id and self.current_topic_id in self.topics:
            cur = self.topics[self.current_topic_id]
            if now - cur.last_active_at > self.idle_timeout_seconds and cur.status == "open":
                self.close_topic(cur.topic_id, summary=f"与 {cur.title} 相关的过往讨论")
                self.current_topic_id = None

        if not self.current_topic_id or self.current_topic_id not in self.topics:
            tid = f"topic_{uuid.uuid4().hex[:8]}"
            title = user_text[:18] if user_text else "新话题"
            topic = Topic(topic_id=tid, title=title, status="open")
            self.topics[tid] = topic
            self.current_topic_id = tid
            if self.store:
                self.store.save_topic(topic)
            return topic

        return self.topics[self.current_topic_id]

    def record_turn(self, user_msg: str, assistant_msg: str) -> None:
        topic = self.get_or_create_current_topic(user_msg)
        topic.add_message(ChatMessage.user(user_msg))
        topic.add_message(ChatMessage.assistant(assistant_msg))
        if self.store:
            self.store.append_message(topic.topic_id, "user", user_msg)
            self.store.append_message(topic.topic_id, "assistant", assistant_msg)
            self.store.save_topic(topic)

    def close_topic(self, topic_id: str, summary: str = "") -> bool:
        if topic_id in self.topics:
            t = self.topics[topic_id]
            t.status = "closed"
            if summary:
                t.summary = summary
            elif not t.summary and t.messages:
                t.summary = f"讨论了关于【{t.title}】的内容，共计 {len(t.messages)} 条记录。"
            if self.store:
                self.store.save_topic(t)
            return True
        return False

    def pin_topic(self, topic_id: str, pin: bool = True) -> bool:
        if topic_id in self.topics:
            self.topics[topic_id].is_pinned = pin
            if self.store:
                self.store.save_topic(self.topics[topic_id])
            return True
        return False

    def assemble_context_messages(
        self,
        new_user_message: str,
        system_prefix: str = "",
    ) -> List[ChatMessage]:
        segments: List[ContextSegment] = []

        # 1. 常驻备忘段
        for idx, memo in enumerate(self.memos, 1):
            segments.append(
                ContextSegment(
                    kind=SEG_MEMO,
                    content=memo,
                    priority=PRIORITY_MEMO,
                    label=f"[常驻备忘 #{idx}]",
                )
            )

        # 2. 闭锁话题摘要
        for tid, top in self.topics.items():
            if top.status == "closed" and top.summary:
                segments.append(
                    ContextSegment(
                        kind=SEG_SUMMARY,
                        content=top.summary,
                        priority=PRIORITY_SUMMARY,
                        label=f"[历史话题摘要·{top.title}]",
                        meta={"topic_id": tid},
                    )
                )

        # 3. 激活/Pin 的历史话题原文
        for tid, top in self.topics.items():
            if tid != self.current_topic_id and (top.is_pinned or top.status == "open"):
                text = "\n".join(f"{m.role}: {m.content}" for m in top.messages)
                if text:
                    segments.append(
                        ContextSegment(
                            kind=SEG_VERBATIM,
                            content=text,
                            priority=PRIORITY_ACTIVE,
                            label=f"[激活关联话题·{top.title}]",
                            truncatable=False,
                            meta={"topic_id": tid},
                        )
                    )

        # 4. 当前话题原文
        cur_topic = self.get_or_create_current_topic(new_user_message)
        if cur_topic.messages:
            cur_text = "\n".join(f"{m.role}: {m.content}" for m in cur_topic.messages)
            segments.append(
                ContextSegment(
                    kind=SEG_VERBATIM,
                    content=cur_text,
                    priority=PRIORITY_CURRENT,
                    label=f"[当前话题·{cur_topic.title}]",
                    truncatable=True,
                    meta={"topic_id": cur_topic.topic_id},
                )
            )

        raw_msgs = self.assembler.assemble(segments)
        assembled: List[ChatMessage] = []
        if system_prefix:
            assembled.append(ChatMessage.system(system_prefix))

        for item in raw_msgs:
            assembled.append(ChatMessage(role=item["role"], content=item["content"]))

        assembled.append(ChatMessage.user(new_user_message))
        return assembled

    def add_message(self, msg: ChatMessage) -> None:
        self.messages.append(msg)
        self.last_active_at = time.time()
