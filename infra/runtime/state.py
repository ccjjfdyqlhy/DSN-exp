# infra/runtime/state.py
# 托管运行时的状态模型 —— 策划案 §4.2.1 / §5.1。
#
# 为什么单独一个模块：journal / checkpoint / idempotency / recovery 四层
# 要用**同一套**记录形状（Session / Turn / Event / Checkpoint / ToolResult）。
# 各写各的 dataclass 的话字段名会慢慢漂移，而恢复流程恰恰靠
# 「事件里的 turn_id」对上「轮次表里的 seq/status」—— 字段名一漂就静默错配，
# 而且这种错配只在崩溃恢复时才暴露（平时测试全绿）。
#
# 这里只放**纯数据**（无 IO、无 SQL、无第三方依赖），所以任何一层都能安全 import：
#   journal.py      追加事件
#   checkpoint.py   写快照
#   idempotency.py  幂等键 + 结果缓存
#   recovery.py     恢复流程
#   managed.py      对外的 RuntimeClient 实现
#
# 状态枚举的取值用小写字符串：它们要直接进 SQL 的 TEXT 列，
# 大写枚举名只作为 Python 侧的标识符存在。

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


# ── 状态枚举（策划案 §4.2.1）────────────────────────────

class SessionStatus(str, Enum):
    """会话状态。"""

    ACTIVE = 'active'
    SUSPENDED = 'suspended'
    COMPLETED = 'completed'
    FAILED = 'failed'
    EXPIRED = 'expired'


class TurnStatus(str, Enum):
    """轮次状态。

    AWAITING_APPROVAL 是 rc0 新增的关键状态：审批期间进程退出后，
    重启必须能回到这个状态，而不是从头再跑一遍（策划案 §8.2 用例 3）。
    """

    PENDING = 'pending'
    RUNNING = 'running'
    AWAITING_APPROVAL = 'awaiting_approval'
    SUCCEEDED = 'succeeded'
    FAILED = 'failed'
    INTERRUPTED = 'interrupted'
    CANCELLED = 'cancelled'


class DeploymentStatus(str, Enum):
    """Agent 版本在某 Runtime 上的部署状态（rc0 只定义，rc1 实现调度）。"""

    PENDING = 'pending'
    ROLLOUT = 'rollout'
    HEALTHY = 'healthy'
    DEGRADED = 'degraded'
    ROLLED_BACK = 'rolled_back'


class WorkspaceStatus(str, Enum):
    """一次运行的可写状态空间的状态。"""

    READY = 'ready'
    LOCKED = 'locked'
    RELEASED = 'released'
    EXPIRED = 'expired'


#: 处于「未结束」状态的轮次 —— 恢复时从这里挑出要继续的 turn。
OPEN_TURN_STATUSES: tuple[str, ...] = (
    TurnStatus.PENDING.value,
    TurnStatus.RUNNING.value,
    TurnStatus.AWAITING_APPROVAL.value,
    TurnStatus.INTERRUPTED.value,
)


# ── 副作用分级（策划案 §4.2.3）──────────────────────────
#
# 这里只放**字符串常量**，不 import harness.tools.spec：
# 依赖规则禁止 infra → harness（那是反向依赖）。两边各写一份，
# 由 tests/test_rc0_runtime.py 的交叉测试把公式钉死。

EFFECT_PURE = 'pure'
EFFECT_IDEMPOTENT = 'idempotent'
EFFECT_EFFECTFUL = 'effectful'

KNOWN_EFFECTS: tuple[str, ...] = (EFFECT_PURE, EFFECT_IDEMPOTENT, EFFECT_EFFECTFUL)


def normalize_effect(effect: Any) -> str:
    """把 effect 归一化成已知取值。

    **未知取值一律按 effectful 处理**（fail-safe）：一个没声明清楚副作用的
    工具，恢复时绝不能被自动重放 —— 宁可多问一次人，也不能重复扣款。
    """
    text = str(effect or '').strip().lower()
    return text if text in KNOWN_EFFECTS else EFFECT_EFFECTFUL


def is_replay_safe(effect: Any) -> bool:
    """恢复时能否自动重放。

    pure / idempotent 可以；effectful 不行（要么不重放，要么先重新审批）。
    """
    return normalize_effect(effect) in (EFFECT_PURE, EFFECT_IDEMPOTENT)


# ── 事件 kind（策划案 §5.2 词表 v2 的增量）────────────────
#
# 只新增、不改既有 kind —— 既有消费方（trace / 审计 / 成本）必须容忍。

class EventKind:
    """托管运行时写入的事件 kind。"""

    RUN_STARTED = 'run_started'
    RUN_FINISHED = 'run_finished'
    RUN_FAILED = 'run_failed'
    TOOL_INTENT = 'tool_intent'
    TOOL_RESULT = 'tool_result'
    TOOL_ERROR = 'tool_error'
    TOOL_REUSED = 'tool_reused'
    TOOL_EFFECT_UNKNOWN = 'tool_effect_unknown'
    CHECKPOINT_WRITTEN = 'checkpoint_written'
    SESSION_RESUMED = 'session_resumed'
    TURN_STARTED = 'turn_started'
    TURN_FINISHED = 'turn_finished'


# ── 记录 dataclass ───────────────────────────────────────

@dataclass
class SessionRecord:
    """一次会话/任务的逻辑容器（runtime_session 表）。"""

    id: str
    tenant: str = ''
    artifact_id: str = ''
    artifact_version: str = ''
    deployment_id: str = ''
    workspace_id: str = ''
    status: str = SessionStatus.ACTIVE.value
    budget: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass
class TurnRecord:
    """一次用户输入驱动的执行单元（runtime_turn 表）。"""

    id: str
    session_id: str
    seq: int
    status: str = TurnStatus.PENDING.value
    input: dict[str, Any] = field(default_factory=dict)
    checkpoint_ref: str = ''
    usage: dict[str, Any] = field(default_factory=dict)
    cost: dict[str, Any] = field(default_factory=dict)
    stop_reason: str = ''
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_TURN_STATUSES


@dataclass
class DeploymentRecord:
    """一个 Agent 版本在某 Runtime 上的部署实例（策划案 §4.2.1）。

    rc0 只定义形状：对应的表在 rc1 才建（§5.1 的 rc0 DDL 里没有部署表），
    但状态枚举先定下来 —— 免得 rc1 各自发明一套状态词。
    """

    id: str
    artifact_id: str = ''
    artifact_version: str = ''
    spec: dict[str, Any] = field(default_factory=dict)
    replicas: int = 1
    strategy: str = 'rolling'
    status: str = DeploymentStatus.PENDING.value
    lease_expires_at: float = 0.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass
class WorkspaceRecord:
    """一次运行的可写状态空间（策划案 §4.2.1）。

    spec 里放 fs / net / secret 三类约束 —— 沙箱（R3）按它限定路径与网络。
    """

    id: str
    session_id: str = ''
    root: str = ''
    spec: dict[str, Any] = field(default_factory=dict)
    status: str = WorkspaceStatus.READY.value
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass
class EventRecord:
    """一条只追加的事实（runtime_event 表）。

    seq 在**会话内**单调递增且不复用：消费方按 seq 去重，
    重复投递的事件不会导致重复计费（策划案 §8.2 用例 6）。
    """

    session_id: str
    seq: int
    kind: str
    turn_id: str = ''
    payload: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    idempotency_key: str = ''

    def to_dict(self) -> dict[str, Any]:
        return {
            'session_id': self.session_id,
            'seq': self.seq,
            'kind': self.kind,
            'turn_id': self.turn_id,
            'payload': self.payload,
            'ts': self.ts,
            'idempotency_key': self.idempotency_key,
        }


@dataclass
class CheckpointRecord:
    """一次检查点快照（runtime_checkpoint 表）。

    checkpoint 是**可丢弃的加速器**，不是真相来源 —— 丢了也能从 journal 重放。
    journal_seq 记录写快照时 journal 的水位线，恢复时据此决定「重放哪些事件」。
    """

    session_id: str
    turn_seq: int
    blob: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    journal_seq: int = 0

    @property
    def ref(self) -> str:
        return checkpoint_ref(self.session_id, self.turn_seq)


@dataclass
class ToolResultRecord:
    """一次工具调用的结果缓存（tool_result_cache 表）。"""

    idempotency_key: str
    tool: str = ''
    version: str = ''
    result: Any = None
    effect: str = EFFECT_PURE
    created_at: float = field(default_factory=time.time)


def checkpoint_ref(session_id: str, turn_seq: int) -> str:
    """检查点引用串 —— runtime_turn.checkpoint_ref 里存的就是它。"""
    return f'{session_id}@{turn_seq}'


# ── 工具意图的鸭子类型 ───────────────────────────────────
#
# Kernel 侧用的是 harness.runtime_client.ToolIntent；infra 不能 import harness，
# 所以这里用 Protocol 描述「运行时需要的最小形状」：
# 同名字段即可，传入 harness 的 ToolIntent 实例照样工作。

@runtime_checkable
class ToolIntentLike(Protocol):
    """运行时记录工具意图时需要的字段集合。"""

    session_id: str
    turn_seq: int
    tool: str
    tool_version: str
    idempotency_key: str
    effect: str
    args_digest: str
    created_at: float


__all__ = [
    'SessionStatus', 'TurnStatus', 'DeploymentStatus', 'WorkspaceStatus',
    'OPEN_TURN_STATUSES',
    'EFFECT_PURE', 'EFFECT_IDEMPOTENT', 'EFFECT_EFFECTFUL', 'KNOWN_EFFECTS',
    'normalize_effect', 'is_replay_safe',
    'EventKind',
    'SessionRecord', 'TurnRecord', 'EventRecord', 'CheckpointRecord',
    'DeploymentRecord', 'WorkspaceRecord',
    'ToolResultRecord', 'checkpoint_ref',
    'ToolIntentLike',
]
