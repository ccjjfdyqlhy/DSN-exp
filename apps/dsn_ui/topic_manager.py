# apps/dsn_ui/topic_manager.py
# DSN-UI 话题上下文与弹性记忆管理器
# 基于 harness.context_assembly.SegmentedContextAssembler 与 SqliteStore

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

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
from harness.orchestrator import ChatMessage
from harness.store.sqlite import SqliteStore

logger = logging.getLogger("DSNUITopicManager")


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


class DSNUITopicStore:
    """话题持久化层，基于 harness SqliteStore 存储 topics / messages / memos / emotion / state"""

    def __init__(self, store: Optional[SqliteStore] = None, *, db_path: str = ":memory:"):
        self.store = store or SqliteStore(db_path)
        self._init_tables()

    def _init_tables(self) -> None:
        conn = self.store.get_connection()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS ui_topics (
                topic_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                is_pinned INTEGER NOT NULL DEFAULT 0,
                summary TEXT DEFAULT '',
                last_active_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ui_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ui_msgs_topic ON ui_messages(topic_id, id);
            CREATE TABLE IF NOT EXISTS ui_memos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ui_emotion (
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
            "INSERT INTO ui_topics (topic_id, title, status, is_pinned, summary, last_active_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(topic_id) DO UPDATE SET "
            "title=excluded.title, status=excluded.status, is_pinned=excluded.is_pinned, "
            "summary=excluded.summary, last_active_at=excluded.last_active_at",
            (topic.topic_id, topic.title, topic.status, int(topic.is_pinned), topic.summary, topic.last_active_at),
        )

    def append_message(self, topic_id: str, role: str, content: str) -> None:
        self.store.execute(
            "INSERT INTO ui_messages (topic_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (topic_id, role, content, time.time()),
        )

    def load_all_topics(self) -> Dict[str, Topic]:
        rows = self.store.execute("SELECT topic_id, title, status, is_pinned, summary, last_active_at FROM ui_topics")
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
            msg_rows = self.store.execute(
                "SELECT role, content FROM ui_messages WHERE topic_id = ? ORDER BY id", (tid,)
            )
            for m in msg_rows:
                top.messages.append(ChatMessage(role=m["role"], content=m["content"]))
            topics[tid] = top
        return topics

    def save_memo(self, content: str) -> None:
        self.store.execute("INSERT INTO ui_memos (content) VALUES (?)", (content,))

    def load_memos(self) -> List[str]:
        rows = self.store.execute("SELECT content FROM ui_memos ORDER BY id")
        return [r["content"] for r in rows]

    def save_emotion(self, joy: float, sorrow: float, anger: float, fear: float, meta: float) -> None:
        self.store.execute(
            "INSERT INTO ui_emotion (id, joy, sorrow, anger, fear, meta, updated_at) "
            "VALUES (1, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "joy=excluded.joy, sorrow=excluded.sorrow, anger=excluded.anger, "
            "fear=excluded.fear, meta=excluded.meta, updated_at=excluded.updated_at",
            (joy, sorrow, anger, fear, meta, time.time()),
        )

    def load_emotion(self) -> Optional[Dict[str, float]]:
        rows = self.store.execute("SELECT joy, sorrow, anger, fear, meta FROM ui_emotion WHERE id = 1")
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


class DSNUITopicContextManager:
    """DSN-UI 话题上下文与弹性预算剪裁管理器"""

    def __init__(
        self,
        budget: Optional[ContextBudget] = None,
        idle_timeout_seconds: float = 1800.0,
        store: Optional[DSNUITopicStore] = None,
        on_topic_converged: Optional[Callable[[str, str], None]] = None,
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
        self.on_topic_converged = on_topic_converged
        self.last_converged_topic: Optional[str] = None
        # 最近一次弹性上下文装配的统计（供 UI 展示预算/折叠/截断情况）
        self.last_assembly_stats: dict = {}

        if self.store:
            self.topics = self.store.load_all_topics()
            self.memos = self.store.load_memos()
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
                self.close_topic(cur.topic_id, summary=f"与【{cur.title}】相关的过往探讨")
                self.current_topic_id = None

        if not self.current_topic_id or self.current_topic_id not in self.topics:
            tid = f"topic_{uuid.uuid4().hex[:8]}"
            title = user_text.strip().splitlines()[0][:20] if user_text else "新话题"
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
            self.last_converged_topic = t.title
            if self.on_topic_converged:
                try:
                    self.on_topic_converged(t.topic_id, t.title)
                except Exception as e:
                    logger.debug("on_topic_converged callback error: %s", e)
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

        # 只做一次剪裁：plan() 在截断时会就地改写 seg.content，重复调用会
        # 让第二次看到的已是截断后的文本，导致审计统计失真。因此这里由 plan
        # 结果直接构造消息，既保证统计与实际注入一致，也避免二次剪裁。
        raw_segments = list(segments)
        plan = self.assembler.plan(raw_segments)
        assembled: List[ChatMessage] = []
        if system_prefix:
            assembled.append(ChatMessage.system(system_prefix))

        for seg in plan.kept:
            text = seg.label + "\n" + seg.content if seg.label else seg.content
            assembled.append(ChatMessage(role="system", content=text))

        assembled.append(ChatMessage.user(new_user_message))

        self.last_assembly_stats = self._build_assembly_stats(
            plan, raw_segments, system_prefix=system_prefix, assembled=assembled,
        )
        return assembled

    def _build_assembly_stats(self, plan, segments, *, system_prefix, assembled) -> dict:
        """把剪裁计划转成前端可读的弹性上下文统计。

        统计口径（字符数）：
          kept      实际注入的段（含被截断保留的部分）
          dropped   因预算超限被整体丢弃的段
          truncated 被截断保留的段
        """
        budget = self.budget
        kept_chars = sum(len(s.content) for s in plan.kept)
        dropped_chars = sum(len(s.content) for s in plan.dropped)
        truncated_chars = sum(len(s.content) for s in plan.truncated)

        def _by_kind(kind: str):
            kept = [s for s in plan.kept if s.kind == kind]
            dropped = [s for s in plan.dropped if s.kind == kind]
            return {
                "segments_kept": len(kept),
                "segments_dropped": len(dropped),
                "chars_kept": sum(len(s.content) for s in kept),
                "chars_dropped": sum(len(s.content) for s in dropped),
            }

        open_topics = [t for t in self.topics.values() if t.status == "open"]
        closed_topics = [t for t in self.topics.values() if t.status == "closed"]
        system_chars = len(system_prefix or "")

        return {
            "budget": {
                "memo_chars": budget.memo_chars,
                "summary_chars": budget.summary_chars,
                "verbatim_chars": budget.verbatim_chars,
                "tail_rounds": budget.tail_rounds,
            },
            "system_prompt_chars": system_chars,
            "kept_chars": kept_chars,
            "dropped_chars": dropped_chars,
            "truncated_chars": truncated_chars,
            "truncated_segments": len(plan.truncated),
            "dropped_segments": len(plan.dropped),
            "kept_segments": len(plan.kept),
            "total_injected_chars": system_chars + kept_chars,
            "messages_injected": len(assembled),
            "segments": {
                "memo": _by_kind(SEG_MEMO),
                "summary": _by_kind(SEG_SUMMARY),
                "verbatim": _by_kind(SEG_VERBATIM),
            },
            "active_memos": len(self.memos),
            "open_topics": len(open_topics),
            "closed_topics": len(closed_topics),
            "current_topic": (
                self.topics[self.current_topic_id].title
                if self.current_topic_id and self.current_topic_id in self.topics
                else None
            ),
        }

    def get_assembly_stats(self) -> dict:
        """最近一次上下文装配的弹性统计（无记录时返回空结构）。"""
        return getattr(self, "last_assembly_stats", {}) or {}
