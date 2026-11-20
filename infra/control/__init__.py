# infra/control/
# 控制面（策划案 §4.5）：资产模型 + 生命周期 + 成本账本 + BYO 纳管。
#
# ── 依赖边界 ──
# infra/control 不 import harness（依赖规则：infra → harness 是反向依赖）。
# 它只依赖 infra 内部的 artifact / lifecycle / cost / adoption / identity
# 与 infra/store 的 IStore。

from .adoption import (
    AdoptionError,
    AdoptionRecord,
    ByoRegistry,
    RuntimeClientView,
)
from .artifact import (
    API_VERSION,
    KIND_AGENT,
    AgentArtifact,
    ArtifactError,
    load_artifact,
    parse_tool_ref,
)
from .cost import CostLedger, price_tokens
from .identity import (
    AgentIdentity,
    DelegationAudit,
    DelegationError,
    check_spawn_scopes,
    delegate,
    derive_child,
    validate_delegation,
)
from .lifecycle import (
    INITIAL_STATE,
    ArtifactState,
    LifecycleError,
    LifecycleEvent,
    allowed_actions,
    check_transition,
)
from .store import (
    ArtifactRecord,
    ArtifactStore,
    VersionConflictError,
    migrate_control,
)

__all__ = [
    'API_VERSION',
    'INITIAL_STATE',
    'KIND_AGENT',
    'AdoptionError',
    'AdoptionRecord',
    'AgentArtifact',
    'AgentIdentity',
    'ArtifactError',
    'ArtifactRecord',
    'ArtifactState',
    'ArtifactStore',
    'ByoRegistry',
    'CostLedger',
    'DelegationAudit',
    'DelegationError',
    'LifecycleError',
    'LifecycleEvent',
    'RuntimeClientView',
    'VersionConflictError',
    'allowed_actions',
    'check_spawn_scopes',
    'check_transition',
    'delegate',
    'derive_child',
    'load_artifact',
    'migrate_control',
    'parse_tool_ref',
    'price_tokens',
    'validate_delegation',
]
