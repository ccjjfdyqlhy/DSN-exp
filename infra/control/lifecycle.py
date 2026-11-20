# infra/control/lifecycle.py
# AgentArtifact 的生命周期协议（策划案 §4.5.2）。
#
#   DRAFT ──review──▶ REVIEWING ──approve──▶ APPROVED ──release──▶ RELEASED(canary)
#                         ▲                    │                    │
#                         │                    └──rollback──────────┘
#                         │                    ▼
#                         └──reject──── DISPUTED          ROLLED_OUT ──deprecate──▶ DEPRECATED ──▶ ARCHIVED
#
# 两条硬规则：
#   1. **每次状态迁移都是一条不可变事件**（control.lifecycle）——
#      带操作人、时间、理由、关联的 Gate 报告 ID。发布不是改个字段，
#      是 APPROVED → RELEASED 的迁移。
#   2. **release 必须携带通过的 Gate 报告**（策划案 §4.5.2 原文：
#      「必须携带通过的 Gate 报告」）—— 没有报告或报告不是 pass，
#      迁移直接被拒。这是评测闭环（D6）与控制面（D5）的强制交点。
#
# 回滚只回退一步（与 harness/learning/promotion.py 的既定语义一致）：
# RELEASED/ROLLED_OUT --rollback--> ROLLED_BACK，让上一版本继续顶上。

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ArtifactState(str, Enum):
    """artifact 生命周期状态（策划案 §4.5.2 状态图）。"""

    DRAFT = 'draft'
    REVIEWING = 'reviewing'
    APPROVED = 'approved'
    RELEASED = 'released'          # canary 灰度中
    ROLLED_OUT = 'rolled_out'      # 已全量
    ROLLED_BACK = 'rolled_back'    # 已回滚（上一版本顶上）
    DISPUTED = 'disputed'          # 评审被拒
    DEPRECATED = 'deprecated'
    ARCHIVED = 'archived'


class LifecycleError(RuntimeError):
    """一次不合法的生命周期迁移（状态不允许 / 发布缺 Gate 报告）。"""


@dataclass(frozen=True)
class LifecycleEvent:
    """一条不可变的生命周期迁移记录。"""

    id: str
    artifact_id: str
    version: str
    from_state: str
    to_state: str
    action: str
    actor: str
    reason: str = ''
    gate_report_id: str = ''
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'artifact_id': self.artifact_id,
            'version': self.version,
            'from_state': self.from_state,
            'to_state': self.to_state,
            'action': self.action,
            'actor': self.actor,
            'reason': self.reason,
            'gate_report_id': self.gate_report_id,
            'created_at': self.created_at,
        }


@dataclass(frozen=True)
class _Transition:
    """一次合法迁移的定义。"""

    action: str
    from_state: ArtifactState
    to_state: ArtifactState
    #: 迁移是否必须携带通过判定（verdict == pass）的 Gate 报告
    requires_gate: bool = False
    #: reason 是否必填（release / rollback 这类要追责的迁移必填）
    requires_reason: bool = False


#: 全部合法迁移（策划案 §4.5.2 状态图逐条抄）
TRANSITIONS: tuple[_Transition, ...] = (
    _Transition('review', ArtifactState.DRAFT, ArtifactState.REVIEWING),
    _Transition('approve', ArtifactState.REVIEWING, ArtifactState.APPROVED),
    _Transition('reject', ArtifactState.REVIEWING, ArtifactState.DISPUTED,
                requires_reason=True),
    _Transition('release', ArtifactState.APPROVED, ArtifactState.RELEASED,
                requires_gate=True, requires_reason=True),
    _Transition('promote', ArtifactState.RELEASED, ArtifactState.ROLLED_OUT),
    _Transition('rollback', ArtifactState.RELEASED, ArtifactState.ROLLED_BACK,
                requires_reason=True),
    _Transition('rollback', ArtifactState.ROLLED_OUT, ArtifactState.ROLLED_BACK,
                requires_reason=True),
    _Transition('review', ArtifactState.ROLLED_BACK, ArtifactState.REVIEWING),
    _Transition('review', ArtifactState.DISPUTED, ArtifactState.REVIEWING),
    _Transition('deprecate', ArtifactState.RELEASED, ArtifactState.DEPRECATED),
    _Transition('deprecate', ArtifactState.ROLLED_OUT, ArtifactState.DEPRECATED),
    _Transition('deprecate', ArtifactState.ROLLED_BACK, ArtifactState.DEPRECATED),
    _Transition('archive', ArtifactState.DEPRECATED, ArtifactState.ARCHIVED),
)

#: 初始状态：新版本一律从 DRAFT 进场
INITIAL_STATE = ArtifactState.DRAFT

#: 终态（不可再迁移）
TERMINAL_STATES: tuple[ArtifactState, ...] = (ArtifactState.ARCHIVED,)


def allowed_actions(state: ArtifactState | str) -> tuple[str, ...]:
    """某个状态下允许的动作。"""
    current = _as_state(state)
    return tuple(t.action for t in TRANSITIONS if t.from_state == current)


def check_transition(state: ArtifactState | str, action: str, *,
                     gate_report_id: str = '', reason: str = '',
                     gate_lookup: Callable[[str], dict] | None = None,
                     ) -> ArtifactState:
    """校验一次迁移的合法性，返回目标状态；不合法抛 LifecycleError。

    gate_lookup 是**注入的** Gate 报告查询（评测面的 storage 属于 infra/eval，
    控制面不 import 它 —— 依赖靠端口注入）。返回的 dict 需带 ``verdict`` 字段。
    """
    current = _as_state(state)
    if current in TERMINAL_STATES:
        raise LifecycleError(f'{current.value} 是终态，不允许再迁移（action={action}）')
    match = None
    for t in TRANSITIONS:
        if t.from_state == current and t.action == action:
            match = t
            break
    if match is None:
        raise LifecycleError(
            f'状态 {current.value} 不允许动作 {action!r}'
            f'（允许: {allowed_actions(current)}）')
    if match.requires_reason and not (reason or '').strip():
        raise LifecycleError(f'动作 {action} 必须给 reason（迁移要可追责）')
    if match.requires_gate:
        if not (gate_report_id or '').strip():
            raise LifecycleError(
                f'动作 {action} 必须携带 Gate 报告 ID：'
                '发布必须证明这次变更过了四道闸门（策划案 §4.5.2）')
        if gate_lookup is None:
            raise LifecycleError(
                f'动作 {action} 需要 gate_lookup 才能校验报告')
        report = gate_lookup(gate_report_id)
        if not report:
            raise LifecycleError(
                f'Gate 报告 {gate_report_id} 不存在：发布被阻断')
        verdict = str(report.get('verdict') or '')
        if verdict != 'pass':
            raise LifecycleError(
                f'Gate 报告 {gate_report_id} 的判定是 {verdict!r} 而不是 pass：'
                '发布被阻断（策划案 §4.5.2「必须携带通过的 Gate 报告」）')
    return match.to_state


def _as_state(state: ArtifactState | str) -> ArtifactState:
    if isinstance(state, ArtifactState):
        return state
    try:
        return ArtifactState(str(state))
    except ValueError:
        raise LifecycleError(f'未知状态: {state!r}') from None


def new_event_id(action: str, artifact_id: str, version: str) -> str:
    """迁移事件 id：可读、可排序、不靠时钟单调。"""
    return f'lce_{int(time.time() * 1000):x}_{action}_{artifact_id}_{version}'


__all__ = [
    'INITIAL_STATE',
    'TERMINAL_STATES',
    'TRANSITIONS',
    'ArtifactState',
    'LifecycleError',
    'LifecycleEvent',
    'allowed_actions',
    'check_transition',
    'new_event_id',
]
