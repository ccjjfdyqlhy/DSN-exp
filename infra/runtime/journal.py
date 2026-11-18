# infra/runtime/journal.py
# 只追加的事件日志（策划案 §4.2.2）—— 托管运行时的**真相来源**。
#
# 策划案原文：
#     Event Journal (WAL, 只追加)   ← 事实的唯一真相来源
#             │  周期性
#             ▼
#     Checkpoint (快照, 可丢弃)     ← 加速恢复，不是真相来源
#
# 三条不变量（破了就等于托管运行时失效）：
#   1. 同一会话内 seq **严格单调递增**，不复用、不回填；
#   2. **只追加** —— 这里没有 update / delete 路径，连方法都不提供；
#      「修正事实」的正确姿势是再追加一条更正事件，不是改旧行；
#   3. 消费方按 seq 去重 —— 事件可能被重复投递（§8.2 用例 6），
#      去重之后不能重复计费。
#
# 为什么不用「更新最后一条事件」这种优化：一旦允许改写，
# 崩溃时刻的状态就依赖「写到哪一步」，而不是「记录了什么」——
# 那正是我们要消灭的不确定性。

from __future__ import annotations

import logging
import time
from typing import Any, Iterable, Iterator, Optional, Sequence

from .state import EventKind, EventRecord
from .store import StorePort

logger = logging.getLogger('infra.runtime.journal')


class Journal:
    """会话级只追加事件日志。

    用法:
        journal = Journal(store)
        event = journal.append('tool_intent', payload, session_id=sid)
        for ev in journal.replay(sid, after_seq=checkpoint_seq):
            ...
    """

    def __init__(self, store: StorePort):
        self._store = store

    # ── 写 ───────────────────────────────────────────────
    def append(self, kind: str, payload: Optional[dict[str, Any]] = None, *,
               session_id: str, turn_id: str = '',
               idempotency_key: str = '', ts: Optional[float] = None) -> EventRecord:
        """追加一条事件，返回带真实 seq 的记录。

        ts 允许调用方指定：恢复重放时我们要保留**原始发生时间**，
        而不是把重放时刻写进去（否则时间线会被重放搅乱）。
        """
        event = EventRecord(
            session_id=session_id,
            seq=0,                      # 由 store 分配
            kind=kind,
            turn_id=turn_id,
            payload=dict(payload or {}),
            ts=time.time() if ts is None else ts,
            idempotency_key=idempotency_key,
        )
        return self._store.append_event(event)

    # ── 读 ───────────────────────────────────────────────
    def events(self, session_id: str, *, after_seq: int = 0,
               kinds: Optional[Sequence[str]] = None,
               limit: Optional[int] = None) -> list[EventRecord]:
        """按 seq 升序取事件。after_seq 之后的不含 after_seq 本身。"""
        return self._store.list_events(session_id, after_seq=after_seq,
                                       kinds=kinds, limit=limit)

    def iter_events(self, session_id: str, *, after_seq: int = 0,
                    kinds: Optional[Sequence[str]] = None) -> Iterator[EventRecord]:
        """流式取事件（事件量大时不要一次性全 load 进内存）。"""
        for event in self.events(session_id, after_seq=after_seq, kinds=kinds):
            yield event

    def replay(self, session_id: str, *, after_seq: int = 0) -> list[EventRecord]:
        """恢复用：从 after_seq 之后重放。

        注意是**排他**的 after_seq —— 检查点已经把 <= after_seq 的事实
        吃进去了，重放它们等于把同一件事做两遍。
        """
        return self.events(session_id, after_seq=after_seq)

    def last_seq(self, session_id: str) -> int:
        """当前水位线（已写入的最大 seq）。"""
        return self._store.last_event_seq(session_id)

    def kind_counts(self, session_id: str) -> dict[str, int]:
        """按 kind 统计事件数 —— 恢复报告 / 审计用。"""
        counts: dict[str, int] = {}
        for event in self.events(session_id):
            counts[event.kind] = counts.get(event.kind, 0) + 1
        return counts

    # ── 去重（策划案 §8.2 用例 6）────────────────────────
    @staticmethod
    def dedupe(events: Iterable[EventRecord]) -> list[EventRecord]:
        """按 (session_id, seq) 去重，保留**第一次**出现的记录。

        事件可能被重复投递（重试、跨进程重放、消费者重入）。
        消费方先过这一道，就不会被同一件事计费两次。
        """
        seen: set[tuple[str, int]] = set()
        out: list[EventRecord] = []
        for event in events:
            key = (event.session_id, event.seq)
            if key in seen:
                continue
            seen.add(key)
            out.append(event)
        return out

    @staticmethod
    def tool_kinds() -> tuple[str, ...]:
        """与工具副作用相关的 kind（恢复时按这些 kind 配对 intent/result）。"""
        return (EventKind.TOOL_INTENT, EventKind.TOOL_RESULT, EventKind.TOOL_ERROR)


__all__ = ['Journal']
