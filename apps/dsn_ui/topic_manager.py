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
from apps.dsn_ui.logging_setup import log_exception
from harness.orchestrator import ChatMessage
from harness.store.sqlite import SqliteStore

logger = logging.getLogger("DSNUITopicManager")


class _IterationGuard:
    """上下文管理器：安全遍历共享 dict，并诊断「遍历中被修改」的问题。

    背景：dsn_ui 的话题表 self.topics 是跨协程共享的 dict。
    只要在 `for ... in self.topics.items()` 期间有其它协程增删话题，
    CPython 就会抛 RuntimeError: dictionary changed size during iteration，
    而原始栈只会指向循环那一行，缺少"谁改了它、改了什么"的信息。

    用法：
        with _IterationGuard(self.topics, "assemble.summary") as keys:
            for tid in keys: ...

    捕获到 RuntimeError 时会打印进入/退出时的大小与差异键，精准定位突变源。
    """

    def __init__(self, mapping: dict, site: str):
        self.mapping = mapping
        self.site = site
        self.before: Optional[set] = None

    def __enter__(self):
        self.before = set(self.mapping.keys())
        return list(self.before)

    def __exit__(self, exc_type, exc, tb):
        after = set(self.mapping.keys())
        added = after - (self.before or set())
        removed = (self.before or set()) - after
        if exc is not None and isinstance(exc, RuntimeError) and "changed size" in str(exc):
            logger.error(
                "检测到字典遍历中被修改: site=%s before=%d after=%d added=%s removed=%s",
                self.site, len(self.before or ()), len(after),
                sorted(added)[:10], sorted(removed)[:10],
            )
            log_exception(logger, f"话题字典并发修改: {self.site}", exc)
        elif added or removed:
            # 遍历期间发生了增删但恰好没触发异常（例如只改值）也要留痕
            logger.debug(
                "字典在遍历期间发生变化: site=%s added=%s removed=%s",
                self.site, sorted(added)[:10], sorted(removed)[:10],
            )
        return False  # 不吞异常，交给上层统一处理


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

    def drop_messages(self, topic_id: str, count: int) -> int:
        """删除某话题最早的 count 条消息（用于 drop_oldest 策略）。

        必须与内存中的裁剪同步，否则下次 load_all_topics 会把"已丢弃"的
        内容重新读回来，导致策略表面上生效、实际上下文又被撑满。
        返回实际删除的条数。
        """
        if count <= 0:
            return 0
        rows = self.store.execute(
            "SELECT id FROM ui_messages WHERE topic_id = ? ORDER BY id LIMIT ?",
            (topic_id, count),
        )
        ids = [r["id"] for r in rows]
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        self.store.execute(
            f"DELETE FROM ui_messages WHERE id IN ({placeholders})", tuple(ids)
        )
        logger.debug("已从话题 %s 删除 %d 条最早消息", topic_id, len(ids))
        return len(ids)

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
                logger.debug("空闲话题闭锁: %s", cur.topic_id)
                self.close_topic(cur.topic_id, summary=f"与【{cur.title}】相关的过往探讨")
                self.current_topic_id = None

        if not self.current_topic_id or self.current_topic_id not in self.topics:
            tid = f"topic_{uuid.uuid4().hex[:8]}"
            title = user_text.strip().splitlines()[0][:20] if user_text else "新话题"
            topic = Topic(topic_id=tid, title=title, status="open")
            # 这里是 topics 的写入点之一：若发生在其它协程遍历 topics 期间，
            # 就会触发 "dictionary changed size during iteration"。
            # 记录写入前后规模，便于与装配侧的诊断日志交叉比对。
            logger.debug(
                "新建当前话题: %s (topics %d → %d)",
                tid, len(self.topics), len(self.topics) + 1,
            )
            self.topics[tid] = topic
            self.current_topic_id = tid
            if self.store:
                self.store.save_topic(topic)
            return topic

        return self.topics[self.current_topic_id]

    def record_turn(self, user_msg: str, assistant_msg: str) -> None:
        logger.debug(
            "record_turn: topics=%d user_chars=%d reply_chars=%d",
            len(self.topics), len(user_msg or ""), len(assistant_msg or ""),
        )
        topic = self.get_or_create_current_topic(user_msg)
        topic.add_message(ChatMessage.user(user_msg))
        topic.add_message(ChatMessage.assistant(assistant_msg))
        if self.store:
            try:
                self.store.append_message(topic.topic_id, "user", user_msg)
                self.store.append_message(topic.topic_id, "assistant", assistant_msg)
                self.store.save_topic(topic)
            except Exception as e:  # noqa: BLE001
                log_exception(logger, f"record_turn 持久化失败 topic={topic.topic_id}", e)
                raise
        logger.debug("record_turn 完成: topic=%s messages=%d", topic.topic_id, len(topic.messages))

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

    def compact_topic_if_needed(
        self,
        max_safe_chars: int,
        summarizer_fn: Callable[[str], str],
    ) -> bool:
        """当历史消息总字符数逼近模型上下文上限时，触发静默自动话题摘要以释放空间。
        
        若要摘要的内容超出安全阈值，自动进行裁剪后再调用模型摘要。
        将较早轮次压缩为 summary，保留最近的 2~3 轮原文。
        """
        cur = self.get_or_create_current_topic()
        if not cur or len(cur.messages) <= 4:
            return False

        # 计算当前话题与活跃话题的历史文本总长度
        total_chars = sum(len(m.content) for m in cur.messages)
        if total_chars < max_safe_chars:
            return False

        logger.info(
            "话题 %s 当前字符数 %d 超过安全上限 %d，启动静默自动摘要释放空间",
            cur.topic_id, total_chars, max_safe_chars
        )

        # 保留最近的 4 条消息（2 轮问答），对其余前序历史进行摘要
        messages_to_summarize = cur.messages[:-4]
        recent_messages = cur.messages[-4:]

        hist_lines: list[str] = []
        for m in messages_to_summarize:
            hist_lines.append(f"{m.role}: {m.content}")
        hist_text = "\n\n".join(hist_lines)

        # 若要摘要的内容本身就超过了当前模型的上下文容量，先执行安全截断
        # 优先保留开头和临近部分
        max_summary_input = int(max_safe_chars * 0.8)
        if len(hist_text) > max_summary_input:
            half = max_summary_input // 2
            hist_text = (
                hist_text[:half]
                + "\n\n...[中间部分过长已截断]...\n\n"
                + hist_text[-half:]
            )

        try:
            new_summary = summarizer_fn(hist_text)
            if new_summary and new_summary.strip():
                if cur.summary:
                    cur.summary = f"{cur.summary}\n\n【后续进展摘要】\n{new_summary.strip()}"
                else:
                    cur.summary = f"【前序会话进展摘要】\n{new_summary.strip()}"
                cur.messages = recent_messages
                if self.store:
                    self.store.save_topic(cur)
                logger.info("话题 %s 自动摘要完成，已释放前序历史空间", cur.topic_id)
                return True
        except Exception as e:
            logger.warning("执行静默自动话题摘要失败: %s", e)

        return False

    # ── 上下文充满策略实现 ──

    def _current_message_chars(self) -> tuple[Optional[Topic], int]:
        """当前话题及其历史字符数。"""
        cur = self.get_or_create_current_topic()
        if not cur:
            return None, 0
        return cur, sum(len(m.content or "") for m in cur.messages)

    def drop_oldest_if_needed(self, max_safe_chars: int, keep_recent: int = 6) -> bool:
        """策略 1：直接丢弃本会话最早的上下文。

        不做任何模型调用（零成本、零延迟），单纯把当前话题最早的若干条消息
        删除，只保留最近 keep_recent 条（默认 3 轮问答）。
        被丢弃的内容不会进入摘要，检索时也不再可见 —— 这是它的取舍。
        """
        cur, total_chars = self._current_message_chars()
        if not cur or len(cur.messages) <= keep_recent:
            return False
        if total_chars < max_safe_chars:
            return False

        dropped = len(cur.messages) - keep_recent
        logger.info(
            "策略[drop_oldest] 话题 %s 字符数 %d 超过 %d，直接丢弃最早 %d 条消息",
            cur.topic_id, total_chars, max_safe_chars, dropped,
        )
        # 每丢弃一条就同步删库，避免内存与持久层不一致（重载后旧内容又回来）
        to_drop = cur.messages[:dropped]
        cur.messages = cur.messages[dropped:]
        if self.store:
            try:
                self.store.drop_messages(cur.topic_id, len(to_drop))
                self.store.save_topic(cur)
            except Exception as e:  # noqa: BLE001
                log_exception(logger, f"drop_oldest 持久化失败 topic={cur.topic_id}", e)
                raise
        return True

    def compact_all_if_needed(
        self,
        max_safe_chars: int,
        summarizer_fn: Callable[[str], str],
        keep_recent: int = 2,
    ) -> bool:
        """策略 2：直接 compact 所有内容。

        把**整个会话**（全部话题的原文）压缩成一份摘要，替换掉所有原文，
        只在当前话题保留最近 keep_recent 条作为衔接。
        适合"这次任务已经做完、要开新话题"的场景。
        """
        cur, total_chars = self._current_message_chars()
        all_chars = sum(
            len(m.content or "")
            for t in self.topics.values()
            for m in t.messages
        )
        if all_chars < max_safe_chars:
            return False
        if not self.topics:
            return False

        logger.info(
            "策略[compact_all] 全会话字符数 %d 超过 %d，启动整体压缩",
            all_chars, max_safe_chars,
        )

        # 汇总所有话题的原文（按时间序）
        lines: list[str] = []
        for tid, top in sorted(
            self.topics.items(), key=lambda kv: kv[1].last_active_at
        ):
            if not top.messages:
                continue
            lines.append(f"=== 话题《{top.title}》 ===")
            for m in top.messages:
                lines.append(f"{m.role}: {m.content}")

        hist_text = "\n\n".join(lines)
        # 输入本身过长时先安全截断（保留首尾），避免摘要请求自身溢出
        max_input = int(max_safe_chars * 0.8)
        if len(hist_text) > max_input:
            half = max_input // 2
            hist_text = (
                hist_text[:half]
                + "\n\n...[中间部分过长已截断]...\n\n"
                + hist_text[-half:]
            )

        new_summary = summarizer_fn(hist_text)
        if not new_summary or not new_summary.strip():
            return False

        summary_block = "【全会话压缩摘要】\n" + new_summary.strip()

        # 把摘要写回当前话题，并清空其它话题的原文
        if cur is None:
            cur = self.get_or_create_current_topic()
        recent = cur.messages[-keep_recent:] if keep_recent > 0 else []

        # 其它话题的既有摘要也并入总摘要，避免信息彻底丢失
        for tid, top in self.topics.items():
            if tid == cur.topic_id:
                continue
            if top.summary:
                summary_block += "\n\n【" + top.title + "】\n" + top.summary
            if top.messages:
                top.messages = []
            top.summary = ""

        cur.summary = summary_block
        cur.messages = list(recent)

        if self.store:
            try:
                for top in self.topics.values():
                    self.store.save_topic(top)
            except Exception as e:  # noqa: BLE001
                log_exception(logger, "compact_all 持久化失败", e)
                raise
        logger.info(
            "策略[compact_all] 完成：摘要 %d 字符，保留最近 %d 条",
            len(cur.summary), len(cur.messages),
        )
        return True

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
        # 先对 keys 做快照再遍历：即便其它协程在这一刻新增/删除话题，
        # 也只会看到"本次装配的快照"，不再触发 dictionary changed size。
        with _IterationGuard(self.topics, "assemble.closed_summaries") as _guard_keys:
            items_snapshot = [(tid, self.topics[tid]) for tid in _guard_keys if tid in self.topics]
        for tid, top in items_snapshot:
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

        # 3. 激活/Pin 的历史话题原文（同样基于快照遍历）
        with _IterationGuard(self.topics, "assemble.active_topics") as _guard_keys:
            active_snapshot = [(tid, self.topics[tid]) for tid in _guard_keys if tid in self.topics]
        for tid, top in active_snapshot:
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
