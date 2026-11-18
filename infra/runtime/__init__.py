# infra/runtime/__init__.py
# 托管运行时（D2 Managed Runtime）—— 策划案 §4.2 / §5.1。
#
# 这里有两样东西，名字必须分清：
#   Runtime        —— DI 容器（历史 API，rc0 冻结；原 infra/runtime.py 迁入 di.py）
#   ManagedRuntime —— 托管运行时，实现 harness.runtime_client.RuntimeClient 协议
#
# 【为什么 DI 容器要搬进包内】
#   策划案要求托管运行时住在 infra/runtime/ 这个**包**里。同名包会遮蔽同名模块：
#   infra/runtime/ 一旦存在，`import infra.runtime` 拿到的就是包，
#   infra/runtime.py 再也不会被加载。所以 DI 容器整体迁到 infra/runtime/di.py，
#   包级 `Runtime` 仍然指向它 —— harness/__init__.py 的
#   `from infra.runtime import Runtime` 行为不变。
#
# 【为什么 infra/runtime 不 import harness】
#   依赖规则：harness 是上层，infra 是下层，反向依赖被禁止。
#   幂等键公式因此在两侧各写一份（infra/runtime/idempotency.py 与
#   harness/runtime_client.py），由 tests/test_rc0_runtime.py 的交叉测试钉死。
#
# 【这一层解决的核心问题】
#   harness/transcript.py 是「对话文本快照」—— 能恢复*说了什么*，
#   但不能保证*副作用不重复*：崩溃重放可能重复发请求、重复写文件。
#   这里是托管运行时的真相来源：
#     journal      只追加的事实（唯一真相）
#     checkpoint   可丢弃的加速器（丢了能从 journal 重放）
#     idempotency  幂等键 + 结果缓存（重复投递不产生第二次副作用）
#     recovery     load checkpoint → replay journal → 继续 turn
#
# 用法:
#     from infra.runtime import ManagedRuntime, SqliteRuntimeStore, migrate_runtime
#     from infra.store.sqlite import SqliteStore
#
#     store = SqliteStore('runtime.db')
#     migrate_runtime(store)
#     runtime = ManagedRuntime(SqliteRuntimeStore(store), session_id='s1')
#     runtime.start_turn(0)
#     outcome = runtime.execute_tool(tool='calc', args={'x': 1}, fn=lambda: 2,
#                                   effect='pure')

from __future__ import annotations

# DI 容器必须**第一个**导入：harness/__init__.py 里的
# `from infra.runtime import Runtime` 会在本包尚未初始化完时执行，
# Runtime 必须那时就已就位。
from .di import Runtime

from .state import (
    EFFECT_EFFECTFUL,
    EFFECT_IDEMPOTENT,
    EFFECT_PURE,
    KNOWN_EFFECTS,
    OPEN_TURN_STATUSES,
    CheckpointRecord,
    DeploymentRecord,
    DeploymentStatus,
    EventKind,
    EventRecord,
    SessionRecord,
    SessionStatus,
    ToolIntentLike,
    ToolResultRecord,
    TurnRecord,
    TurnStatus,
    WorkspaceRecord,
    WorkspaceStatus,
    checkpoint_ref,
    is_replay_safe,
    normalize_effect,
)
from .store import SqliteRuntimeStore, StorePort
from .journal import Journal
from .checkpoint import JOURNAL_SEQ_KEY, CheckpointCorruptError, CheckpointStore
from .idempotency import ResultCache, args_digest, canonical_args, idempotency_key
from .recovery import RecoveryPlan, ReplayableCall, UnknownOutcome, recover
from .managed import ManagedRuntime, ToolOutcome, UnknownOutcomeError
from .migrations import RUNTIME_MIGRATIONS, migrate_runtime

__all__ = [
    # DI 容器（历史 API）
    'Runtime',
    # 托管运行时
    'ManagedRuntime',
    'ToolOutcome',
    'UnknownOutcomeError',
    # 状态模型
    'SessionStatus', 'TurnStatus', 'DeploymentStatus', 'WorkspaceStatus',
    'OPEN_TURN_STATUSES',
    'SessionRecord', 'TurnRecord', 'EventRecord', 'CheckpointRecord',
    'DeploymentRecord', 'WorkspaceRecord',
    'ToolResultRecord', 'checkpoint_ref',
    'EventKind', 'ToolIntentLike',
    # 副作用分级
    'EFFECT_PURE', 'EFFECT_IDEMPOTENT', 'EFFECT_EFFECTFUL', 'KNOWN_EFFECTS',
    'normalize_effect', 'is_replay_safe',
    # 存储
    'StorePort', 'SqliteRuntimeStore',
    'Journal', 'CheckpointStore', 'CheckpointCorruptError', 'JOURNAL_SEQ_KEY',
    'ResultCache', 'canonical_args', 'idempotency_key', 'args_digest',
    # 恢复
    'recover', 'RecoveryPlan', 'UnknownOutcome', 'ReplayableCall',
    # 迁移
    'RUNTIME_MIGRATIONS', 'migrate_runtime',
]
