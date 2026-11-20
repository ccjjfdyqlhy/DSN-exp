# infra/control/store.py
# 控制面的持久化（策划案 §5.1 的 control_* 三张表）。
#
#   control_artifact         资产（(id, version) 主键 —— 版本不可变）
#   control_lifecycle_event  生命周期迁移（只追加）
#   control_cost_ledger      成本账本（按 session/agent/tool/model 归因）
#
# 版本不可变在这里**强制**（策划案 §4.5.3「不可变，禁止原地改」）：
# 同一个 (id, version) 再 put 一次，内容哈希不同 → 直接拒绝；
# 内容哈希相同 → 幂等放行（重放一次发布申请不算错）。
#
# 存储访问走 infra/store/base.py 的 IStore —— rc1 换 Postgres 时
# 上层不动（策划案风险 R-7 的既定缓解）。

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from infra.store.base import IStore, Migration, MigrationRunner

from .artifact import AgentArtifact
from .cost import CostLedger
from .lifecycle import (
    INITIAL_STATE,
    ArtifactState,
    LifecycleError,
    LifecycleEvent,
    check_transition,
    new_event_id,
)

logger = logging.getLogger('infra.control.store')

_CONTROL_SCHEMA = """
CREATE TABLE IF NOT EXISTS control_artifact (
  id TEXT, version TEXT, kind TEXT, owner TEXT, spec_yaml TEXT,
  content_hash TEXT, state TEXT, created_at REAL,
  PRIMARY KEY (id, version)
);

CREATE TABLE IF NOT EXISTS control_lifecycle_event (
  id TEXT PRIMARY KEY, artifact_id TEXT, version TEXT,
  from_state TEXT, to_state TEXT, action TEXT, actor TEXT, reason TEXT,
  gate_report_id TEXT, created_at REAL
);
CREATE INDEX IF NOT EXISTS idx_lifecycle_artifact
  ON control_lifecycle_event(artifact_id, version, created_at);

CREATE TABLE IF NOT EXISTS control_cost_ledger (
  id TEXT PRIMARY KEY, session_id TEXT, agent_id TEXT, tool TEXT,
  model TEXT, tokens INTEGER, cost REAL, ts REAL
);
CREATE INDEX IF NOT EXISTS idx_cost_session ON control_cost_ledger(session_id);
CREATE INDEX IF NOT EXISTS idx_cost_agent ON control_cost_ledger(agent_id);
"""


def _create_control_tables(conn: Any) -> None:
    conn.executescript(_CONTROL_SCHEMA)


#: 控制面迁移（id 全局唯一且稳定）
CONTROL_MIGRATIONS: list[Migration] = [
    Migration(id='rc1_control_001', up=_create_control_tables),
]


def migrate_control(store: IStore) -> list[str]:
    """把控制面表建好；幂等。"""
    applied = MigrationRunner(store).migrate(CONTROL_MIGRATIONS)
    if applied:
        logger.info('控制面表已就绪: %s', applied)
    return applied


class VersionConflictError(RuntimeError):
    """同一个 (artifact, version) 被写入了一份**不同**的内容。

    版本不可变是控制面的地基：改声明 = 发新版本。
    """


class ArtifactStore:
    """artifact + 生命周期 + 成本账本的统一存储。"""

    def __init__(self, store: IStore, *,
                 gate_lookup: Callable[[str], dict] | None = None,
                 migrate: bool = True) -> None:
        self._store = store
        #: 注入的 Gate 报告查询（评测面），发布迁移时校验用
        self.gate_lookup = gate_lookup
        self.cost = CostLedger(store)
        if migrate:
            migrate_control(store)

    # ── artifact ─────────────────────────────────────────
    def put_artifact(self, artifact: AgentArtifact, *,
                     actor: str = '',
                     state: ArtifactState | str = INITIAL_STATE) -> ArtifactRecord:
        """登记一份 artifact 版本。版本不可变：冲突即拒。"""
        if not artifact.name:
            raise LifecycleError('artifact 没有 metadata.name，无法登记')
        content_hash = artifact.content_hash()
        conn = self._store.get_connection()
        row = conn.execute(
            'SELECT content_hash, state FROM control_artifact '
            'WHERE id = ? AND version = ?',
            (artifact.id, artifact.version)).fetchone()
        if row is not None:
            existing_hash = str(row[0])
            if existing_hash != content_hash:
                raise VersionConflictError(
                    f'{artifact.id}@{artifact.version} 已存在且内容不同'
                    f'（hash {existing_hash[:12]}… != {content_hash[:12]}…）：'
                    '版本不可变，改声明请升 version')
            return self.get_artifact(artifact.id, artifact.version)  # type: ignore[return-value]
        conn.execute(
            'INSERT INTO control_artifact (id, version, kind, owner, spec_yaml,'
            ' content_hash, state, created_at) VALUES (?,?,?,?,?,?,?,?)',
            (artifact.id, artifact.version, artifact.kind,
             artifact.metadata.owner, artifact.raw_yaml or artifact.to_yaml(),
             content_hash, _as_state_value(state), time.time()))
        conn.commit()
        return self.get_artifact(artifact.id, artifact.version)  # type: ignore[return-value]

    def get_artifact(self, artifact_id: str,
                     version: str) -> ArtifactRecord | None:
        conn = self._store.get_connection()
        row = conn.execute(
            'SELECT id, version, kind, owner, spec_yaml, content_hash, state,'
            ' created_at FROM control_artifact WHERE id = ? AND version = ?',
            (artifact_id, version)).fetchone()
        return _record_from_row(row)

    def latest_version(self, artifact_id: str) -> ArtifactRecord | None:
        """按登记时间取最新版本（不是语义化版本比较 —— 那是解析问题）。"""
        conn = self._store.get_connection()
        row = conn.execute(
            'SELECT id, version, kind, owner, spec_yaml, content_hash, state,'
            ' created_at FROM control_artifact WHERE id = ?'
            ' ORDER BY created_at DESC LIMIT 1',
            (artifact_id,)).fetchone()
        return _record_from_row(row)

    def list_artifacts(self, *,
                       artifact_id: str = '',
                       state: ArtifactState | str = '') -> list[ArtifactRecord]:
        sql = ('SELECT id, version, kind, owner, spec_yaml, content_hash,'
               ' state, created_at FROM control_artifact')
        clauses: list[str] = []
        params: list[Any] = []
        if artifact_id:
            clauses.append('id = ?')
            params.append(artifact_id)
        if state:
            clauses.append('state = ?')
            params.append(_as_state_value(state))
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        sql += ' ORDER BY created_at DESC'
        conn = self._store.get_connection()
        rows = conn.execute(sql, params).fetchall()
        return [r for r in (_record_from_row(row) for row in rows) if r]

    # ── 生命周期 ─────────────────────────────────────────
    def transition(self, artifact_id: str, version: str, action: str, *,
                   actor: str = '', reason: str = '',
                   gate_report_id: str = '') -> LifecycleEvent:
        """执行一次生命周期迁移：校验 + 记不可变事件。

        发布（release）必须携带通过判定的 Gate 报告 —— 校验用的
        gate_lookup 在构造时注入。
        """
        record = self.get_artifact(artifact_id, version)
        if record is None:
            raise LifecycleError(
                f'artifact {artifact_id}@{version} 未登记，无法迁移')
        target = check_transition(
            record.state, action,
            gate_report_id=gate_report_id, reason=reason,
            gate_lookup=self.gate_lookup)
        event = LifecycleEvent(
            id=new_event_id(action, artifact_id, version),
            artifact_id=artifact_id, version=version,
            from_state=record.state, to_state=target.value, action=action,
            actor=actor, reason=reason, gate_report_id=gate_report_id,
            created_at=time.time())
        conn = self._store.get_connection()
        conn.execute(
            'INSERT INTO control_lifecycle_event (id, artifact_id, version,'
            ' from_state, to_state, action, actor, reason, gate_report_id,'
            ' created_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
            (event.id, event.artifact_id, event.version, event.from_state,
             event.to_state, event.action, event.actor, event.reason,
             event.gate_report_id, event.created_at))
        conn.execute(
            'UPDATE control_artifact SET state = ? WHERE id = ? AND version = ?',
            (target.value, artifact_id, version))
        conn.commit()
        return event

    def lifecycle_events(self, artifact_id: str,
                         version: str = '') -> list[LifecycleEvent]:
        sql = ('SELECT id, artifact_id, version, from_state, to_state, action,'
               ' actor, reason, gate_report_id, created_at'
               ' FROM control_lifecycle_event WHERE artifact_id = ?')
        params: list[Any] = [artifact_id]
        if version:
            sql += ' AND version = ?'
            params.append(version)
        sql += ' ORDER BY created_at ASC'
        conn = self._store.get_connection()
        rows = conn.execute(sql, params).fetchall()
        return [
            LifecycleEvent(
                id=str(r[0]), artifact_id=str(r[1]), version=str(r[2]),
                from_state=str(r[3]), to_state=str(r[4]), action=str(r[5]),
                actor=str(r[6]), reason=str(r[7]), gate_report_id=str(r[8]),
                created_at=float(r[9] or 0.0))
            for r in rows
        ]

    # ── 发布便捷方法 ─────────────────────────────────────
    def publish(self, artifact: AgentArtifact, *,
                actor: str = '', gate_report_id: str = '') -> LifecycleEvent:
        """登记（如未登记）+ 一键从 DRAFT 走完 review → approve → release。

        这是策划案 §5.4 `aicf artifact publish a.yaml --gate <report_id>`
        的服务端。reason 记录 gate 报告 id，保证可追责。

        每一步都按**当前状态**判断是否还要走 —— 上一次发布在中途失败
        （比如 Gate 报告没过）时，重试不需要从头再来，也不会把已走过的
        迁移再走一遍。

        Gate 报告在**任何迁移之前**先校验：一次失败的发布不应该
        留下「approved 但没人知道为什么」的中间态。
        """
        if gate_report_id:
            report = None
            if self.gate_lookup is not None:
                report = self.gate_lookup(gate_report_id)
            if not report:
                raise LifecycleError(
                    f'Gate 报告 {gate_report_id} 不存在：发布被阻断')
            if str(report.get('verdict') or '') != 'pass':
                raise LifecycleError(
                    f'Gate 报告 {gate_report_id} 的判定是 '
                    f'{report.get("verdict")!r} 而不是 pass：发布被阻断')
        self.put_artifact(artifact, actor=actor)
        reason = f'gate={gate_report_id}' if gate_report_id else ''
        state = self.get_artifact(artifact.id, artifact.version).state  # type: ignore[union-attr]
        if state in ('draft', 'disputed', 'rolled_back'):
            self.transition(artifact.id, artifact.version, 'review',
                            actor=actor, reason='publish')
            state = 'reviewing'
        if state == 'reviewing':
            self.transition(artifact.id, artifact.version, 'approve',
                            actor=actor)
            state = 'approved'
        return self.transition(artifact.id, artifact.version, 'release',
                               actor=actor, reason=reason,
                               gate_report_id=gate_report_id)


def _as_state_value(state: ArtifactState | str) -> str:
    return state.value if isinstance(state, ArtifactState) else str(state)


def _record_from_row(row: Any) -> ArtifactRecord | None:
    if row is None:
        return None
    return ArtifactRecord(
        id=str(row[0]), version=str(row[1]), kind=str(row[2]),
        owner=str(row[3] or ''), spec_yaml=str(row[4] or ''),
        content_hash=str(row[5] or ''), state=str(row[6] or ''),
        created_at=float(row[7] or 0.0))


@dataclass(frozen=True)
class ArtifactRecord:
    """存储里的一份 artifact 版本（含当前状态）。"""

    id: str
    version: str
    kind: str
    owner: str
    spec_yaml: str
    content_hash: str
    state: str
    created_at: float

    def parse(self) -> AgentArtifact:
        return AgentArtifact.from_yaml(self.spec_yaml)

    def to_dict(self) -> dict[str, Any]:
        return {
            'id': self.id, 'version': self.version, 'kind': self.kind,
            'owner': self.owner, 'content_hash': self.content_hash,
            'state': self.state, 'created_at': self.created_at,
        }


__all__ = [
    'CONTROL_MIGRATIONS',
    'ArtifactRecord',
    'ArtifactStore',
    'VersionConflictError',
    'migrate_control',
]
