# infra/runtime/recovery.py
# 恢复流程（策划案 §4.2.2 / §8.2 用例 1、7）：
#
#     load latest checkpoint → replay journal after checkpoint → 继续 turn
#
# 【三条铁律】
#   1. checkpoint 是加速器，不是真相来源。
#      checkpoint 损坏（§8.2 用例 7）时必须退化成「纯 journal 重放」，
#      而不是让恢复失败 —— 快照本来就是可以丢的东西。
#   2. journal 是真相来源。
#      「这次工具调用到底做完没有」只能由 journal 回答：
#      有 intent + 有 result = 做完；只有 intent = 没做完（结果未知）。
#   3. **effectful 绝不擅自重放**（§4.2.3）。
#      只有 intent 没有 result 的 effectful 调用 → 标记 unknown_outcome，
#      交给人确认。宁可让任务挂起，也不能重复扣款 / 重复发消息。
#      pure / idempotent 的同类调用 → 标记为「可重放」，恢复时自动重跑。
#
# 副作用配对为什么要扫**全量**事件而不是「检查点之后」的事件：
#   intent 可能在检查点之前写下、result 在之后（甚至根本没写）。
#   只看检查点之后的会漏掉「跨检查点的在途调用」—— 那正是最危险的一类。

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from .checkpoint import CheckpointCorruptError, CheckpointStore
from .journal import Journal
from .state import (
    EFFECT_EFFECTFUL,
    CheckpointRecord,
    EventKind,
    EventRecord,
    TurnRecord,
    normalize_effect,
)
from .store import StorePort

logger = logging.getLogger('infra.runtime.recovery')


@dataclass
class UnknownOutcome:
    """一次**结果未知**的副作用调用（只有 intent、没有 result）。

    这是托管运行时里最需要小心的对象：外部系统可能已经执行过了
    （发出去的消息收不回来、扣的款退不回去），也可能根本没执行。
    运行时不能替人做这个判断 —— 只能如实标记、如实上报。
    """

    session_id: str
    turn_seq: int
    tool: str
    tool_version: str
    idempotency_key: str
    effect: str = EFFECT_EFFECTFUL
    args_digest: str = ''
    args: Optional[dict[str, Any]] = None
    detected_at: float = field(default_factory=time.time)
    reason: str = 'intent_without_result'

    def to_dict(self) -> dict[str, Any]:
        return {
            'session_id': self.session_id,
            'turn_seq': self.turn_seq,
            'tool': self.tool,
            'tool_version': self.tool_version,
            'idempotency_key': self.idempotency_key,
            'effect': self.effect,
            'args_digest': self.args_digest,
            'detected_at': self.detected_at,
            'reason': self.reason,
        }


@dataclass
class ReplayableCall:
    """一次**可以安全重放**的调用（pure / idempotent，缺 result）。"""

    session_id: str
    turn_seq: int
    tool: str
    tool_version: str
    idempotency_key: str
    effect: str = 'pure'
    args: Optional[dict[str, Any]] = None
    args_digest: str = ''

    def to_dict(self) -> dict[str, Any]:
        return {
            'session_id': self.session_id,
            'turn_seq': self.turn_seq,
            'tool': self.tool,
            'tool_version': self.tool_version,
            'idempotency_key': self.idempotency_key,
            'effect': self.effect,
            'args_digest': self.args_digest,
        }


@dataclass
class RecoveryPlan:
    """一次恢复的完整结论：恢复到哪、有什么要重放、什么要人确认。"""

    session_id: str
    resume_turn_seq: int = 0
    checkpoint: Optional[CheckpointRecord] = None
    checkpoint_corrupt: bool = False
    pending_turn: Optional[TurnRecord] = None
    events: list[EventRecord] = field(default_factory=list)
    tool_results: dict[str, Any] = field(default_factory=dict)
    unknown_outcomes: list[UnknownOutcome] = field(default_factory=list)
    replayable: list[ReplayableCall] = field(default_factory=list)
    last_event_seq: int = 0

    @property
    def has_unknown_outcomes(self) -> bool:
        return bool(self.unknown_outcomes)

    @property
    def requires_human_review(self) -> bool:
        """是否必须人工确认才能继续（有结果未知的副作用）。"""
        return bool(self.unknown_outcomes)

    @property
    def state(self) -> dict[str, Any]:
        """恢复出来的状态快照（给上层重建内存态用）。"""
        return {
            'session_id': self.session_id,
            'turn_seq': self.resume_turn_seq,
            'checkpoint_state': dict(self.checkpoint.blob) if self.checkpoint else {},
            'tool_results': dict(self.tool_results),
            'events_replayed': len(self.events),
            'last_event_seq': self.last_event_seq,
        }

    def unknown_keys(self) -> set[str]:
        """结果未知的幂等键集合 —— 执行器据此拒绝自动重放。"""
        return {item.idempotency_key for item in self.unknown_outcomes}

    def summary(self) -> dict[str, Any]:
        """人类可读的恢复摘要（CLI / 审计用）。"""
        return {
            'session_id': self.session_id,
            'resume_turn_seq': self.resume_turn_seq,
            'checkpoint': self.checkpoint.ref if self.checkpoint else None,
            'checkpoint_corrupt': self.checkpoint_corrupt,
            'events_replayed': len(self.events),
            'unknown_outcomes': [item.to_dict() for item in self.unknown_outcomes],
            'replayable': [item.to_dict() for item in self.replayable],
        }


def recover(port: StorePort, session_id: str) -> RecoveryPlan:
    """算出一份恢复方案。

    **纯读**：不写任何东西。写事件（session_resumed / tool_effect_unknown）
    由调用方（ManagedRuntime.resume）决定要不要落 —— 恢复本身不该有副作用，
    否则「只是看一眼恢复状态」也会污染 journal。
    """
    journal = Journal(port)
    checkpoints = CheckpointStore(port)

    # ── 1. 取最新检查点（损坏就退化）────────────────────
    checkpoint: Optional[CheckpointRecord] = None
    checkpoint_corrupt = False
    try:
        checkpoint = checkpoints.latest(session_id)
    except CheckpointCorruptError:
        checkpoint_corrupt = True
        logger.warning('检查点损坏，退化为纯 journal 重放: session=%s', session_id)

    # ── 2. 重放检查点之后的事件 ─────────────────────────
    after_seq = checkpoint.journal_seq if checkpoint else 0
    events = journal.replay(session_id, after_seq=after_seq)
    last_seq = journal.last_seq(session_id)

    # ── 3. 配对 intent / result（全量扫描）───────────────
    tool_events = journal.events(session_id, kinds=Journal.tool_kinds())
    intents: dict[str, EventRecord] = {}
    finished: set[str] = set()
    for event in tool_events:
        key = event.idempotency_key or str(event.payload.get('idempotency_key', ''))
        if not key:
            continue
        if event.kind == EventKind.TOOL_INTENT:
            intents.setdefault(key, event)
        elif event.kind == EventKind.TOOL_RESULT:
            finished.add(key)

    # ── 4. 重建结果表 + 找出未完成的调用 ────────────────
    tool_results: dict[str, Any] = {}
    for event in tool_events:
        if event.kind != EventKind.TOOL_RESULT:
            continue
        key = event.idempotency_key or str(event.payload.get('idempotency_key', ''))
        if key:
            tool_results[key] = event.payload.get('result')

    unknown: list[UnknownOutcome] = []
    replayable: list[ReplayableCall] = []
    for key, intent in intents.items():
        if key in finished:
            continue
        # 结果也可能只落在缓存表里（事件写成功、缓存写失败或反过来）
        cached = port.get_tool_result(key)
        if cached is not None:
            tool_results.setdefault(key, cached.result)
            continue
        payload = intent.payload or {}
        effect = normalize_effect(payload.get('effect'))
        args = payload.get('args')
        if not isinstance(args, dict):
            args = None
        turn_seq = int(payload.get('turn_seq', 0) or 0)
        if effect == EFFECT_EFFECTFUL:
            unknown.append(UnknownOutcome(
                session_id=session_id,
                turn_seq=turn_seq,
                tool=str(payload.get('tool', '')),
                tool_version=str(payload.get('tool_version', '')),
                idempotency_key=key,
                effect=effect,
                args_digest=str(payload.get('args_digest', '')),
                args=args,
            ))
        else:
            replayable.append(ReplayableCall(
                session_id=session_id,
                turn_seq=turn_seq,
                tool=str(payload.get('tool', '')),
                tool_version=str(payload.get('tool_version', '')),
                idempotency_key=key,
                effect=effect,
                args=args,
                args_digest=str(payload.get('args_digest', '')),
            ))

    # ── 5. 决定续跑哪个 turn ────────────────────────────
    pending_turn = port.last_open_turn(session_id)
    if pending_turn is not None:
        resume_turn_seq = pending_turn.seq
    else:
        turns = port.list_turns(session_id)
        resume_turn_seq = (turns[-1].seq + 1) if turns else 0

    plan = RecoveryPlan(
        session_id=session_id,
        resume_turn_seq=resume_turn_seq,
        checkpoint=checkpoint,
        checkpoint_corrupt=checkpoint_corrupt,
        pending_turn=pending_turn,
        events=events,
        tool_results=tool_results,
        unknown_outcomes=unknown,
        replayable=replayable,
        last_event_seq=last_seq,
    )
    logger.info(
        '恢复方案 session=%s turn=%s checkpoint=%s 未知结果=%d 可重放=%d',
        session_id, resume_turn_seq,
        checkpoint.ref if checkpoint else ('损坏' if checkpoint_corrupt else '无'),
        len(unknown), len(replayable))
    return plan


__all__ = ['recover', 'RecoveryPlan', 'UnknownOutcome', 'ReplayableCall']
