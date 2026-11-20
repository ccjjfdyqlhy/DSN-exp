# infra/runtime/scheduler.py
# 部署租约与接管（策划案 §4.2.4 / rc2 P1）。
#
# ── 单机语义之外的下一步 ──
# rc0 只保证「实例可替换、状态不丢」的单机语义：状态在 journal 里，
# 进程重启后从 journal 恢复。rc2 P1 要的是**接管**：一个实例失联
# （lease 超时未续约）后，其他实例能接手，且状态不丢、结果不重复。
#
# ── 租约（lease）与围栏令牌（fencing token） ──
# - Deployment 有 lease_expires_at，超时未续约即判定失联（策划案原文）。
# - 接管必须带**纪元（epoch）**：每次接管 epoch+1。旧实例拿旧 epoch 写进
#   来的东西可以被 journal 按 epoch 拒收 —— 没有 epoch 的接管在「旧实例
#   只是慢了没死」的分区场景里会双主，那就是重复副作用。
# - 状态本身不在本模块存 —— 状态永远在 journal（真相来源），
#   这里只是「谁被允许继续写」的仲裁。

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from aicf.infra.store.base import IStore, Migration, MigrationRunner

from .state import DeploymentStatus

#: 默认租约时长（秒）—— 策划案没有定数值；30s 是「心跳 10s、容忍 3 次丢失」
DEFAULT_LEASE_TTL = 30.0

_LEASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS runtime_lease (
  deployment_id TEXT PRIMARY KEY, holder TEXT, epoch INTEGER,
  lease_expires_at REAL, updated_at REAL
);

CREATE TABLE IF NOT EXISTS runtime_deployment (
  id TEXT PRIMARY KEY, artifact_id TEXT, artifact_version TEXT,
  spec_json TEXT, replicas INTEGER, strategy TEXT, status TEXT,
  lease_expires_at REAL, created_at REAL, updated_at REAL
);
"""


def _create_lease_tables(conn: Any) -> None:
    conn.executescript(_LEASE_SCHEMA)


#: 租约迁移（id 全局唯一且稳定，只加不改）
RUNTIME_LEASE_MIGRATIONS: list[Migration] = [
    Migration(id='rc2_lease_001', up=_create_lease_tables),
]


def migrate_lease(store: IStore) -> list[str]:
    applied = MigrationRunner(store).migrate(RUNTIME_LEASE_MIGRATIONS)
    return applied


class LeaseHeldError(RuntimeError):
    """租约被别的实例持有且未过期。"""


@dataclass(frozen=True)
class Lease:
    """一张生效中的租约。

    epoch 是围栏令牌：写入方必须携带它，接收方（journal / store）
    拒收比当前 epoch 旧的写入 —— 这是接管语义里「结果不重复」的保证。
    """

    deployment_id: str
    holder: str
    epoch: int
    expires_at: float
    ttl: float

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at

    def remaining(self) -> float:
        return max(0.0, self.expires_at - time.time())


class DeploymentScheduler:
    """部署与租约仲裁。

    职责边界（策划案 §4.2.4）：rc0/rc2 不做跨机编排 —— 本类只回答
    「这个部署现在归谁写」。接管者在哪台机器上起进程，是部署形态的事。
    """

    def __init__(self, store: IStore, *,
                 lease_ttl: float = DEFAULT_LEASE_TTL,
                 migrate: bool = True):
        self._store = store
        self.lease_ttl = float(lease_ttl)
        if migrate:
            migrate_lease(store)

    # ── 部署登记 ─────────────────────────────────────────
    def register_deployment(self, deployment_id: str, *,
                            artifact_id: str = '',
                            artifact_version: str = '',
                            spec: dict | None = None,
                            replicas: int = 1,
                            strategy: str = 'rolling') -> dict:
        now = time.time()
        conn = self._store.get_connection()
        conn.execute(
            'INSERT OR IGNORE INTO runtime_deployment (id, artifact_id,'
            ' artifact_version, spec_json, replicas, strategy, status,'
            ' lease_expires_at, created_at, updated_at)'
            ' VALUES (?,?,?,?,?,?,?,?,?,?)',
            (deployment_id, artifact_id, artifact_version,
             _json(spec or {}), replicas, strategy,
             DeploymentStatus.PENDING.value, 0.0, now, now))
        conn.commit()
        return self.get_deployment(deployment_id)  # type: ignore[return-value]

    def get_deployment(self, deployment_id: str) -> dict | None:
        conn = self._store.get_connection()
        row = conn.execute(
            'SELECT id, artifact_id, artifact_version, spec_json, replicas,'
            ' strategy, status, lease_expires_at, created_at, updated_at'
            ' FROM runtime_deployment WHERE id = ?',
            (deployment_id,)).fetchone()
        if row is None:
            return None
        import json
        return {
            'id': row[0], 'artifact_id': row[1],
            'artifact_version': row[2],
            'spec': json.loads(row[3] or '{}'), 'replicas': int(row[4]),
            'strategy': row[5], 'status': row[6],
            'lease_expires_at': float(row[7] or 0.0),
            'created_at': float(row[8] or 0.0),
            'updated_at': float(row[9] or 0.0),
        }

    def set_status(self, deployment_id: str, status: DeploymentStatus | str
                   ) -> None:
        value = status.value if isinstance(status, DeploymentStatus) else str(status)
        conn = self._store.get_connection()
        conn.execute(
            'UPDATE runtime_deployment SET status = ?, updated_at = ?'
            ' WHERE id = ?', (value, time.time(), deployment_id))
        conn.commit()

    # ── 租约 ─────────────────────────────────────────────
    def acquire(self, deployment_id: str, holder: str, *,
                ttl: float | None = None) -> Lease:
        """为实例申请一张写租约。

        已有**未过期**租约且是别的实例持有 → LeaseHeldError；
        已过期 → 直接接管（epoch+1）；没有租约 → 新建（epoch=1）。
        """
        now = time.time()
        ttl_value = float(ttl) if ttl is not None else self.lease_ttl
        conn = self._store.get_connection()
        row = conn.execute(
            'SELECT holder, epoch, lease_expires_at FROM runtime_lease'
            ' WHERE deployment_id = ?', (deployment_id,)).fetchone()
        if row is not None:
            existing_holder, epoch, expires_at = (str(row[0]), int(row[1]),
                                                  float(row[2]))
            if expires_at > now and existing_holder != str(holder):
                raise LeaseHeldError(
                    f'部署 {deployment_id} 的租约被 {existing_holder} 持有'
                    f'（{expires_at - now:.1f}s 后过期）')
            # 未过期且是自己 → 续约语义（epoch 不变）；
            # 已过期（失联判定）或换持有者 → 接管语义（epoch+1，围栏令牌）。
            new_epoch = int(epoch) + (1 if existing_holder != str(holder)
                                      else 0)
        else:
            new_epoch = 1
        lease = Lease(deployment_id=deployment_id, holder=str(holder),
                      epoch=new_epoch, expires_at=now + ttl_value,
                      ttl=ttl_value)
        conn.execute(
            'INSERT OR REPLACE INTO runtime_lease (deployment_id, holder,'
            ' epoch, lease_expires_at, updated_at) VALUES (?,?,?,?,?)',
            (deployment_id, lease.holder, lease.epoch, lease.expires_at, now))
        conn.commit()
        return lease

    def renew(self, lease: Lease, *,
              ttl: float | None = None) -> Lease:
        """续约（心跳）。只允许**当前持有者**以**当前纪元**续约 ——
        纪元过期的续约被拒（ fencing：旧主已不能续）。"""
        conn = self._store.get_connection()
        row = conn.execute(
            'SELECT holder, epoch FROM runtime_lease WHERE deployment_id = ?',
            (lease.deployment_id,)).fetchone()
        if row is None:
            raise LeaseHeldError(f'部署 {lease.deployment_id} 没有租约')
        holder, epoch = str(row[0]), int(row[1])
        if holder != lease.holder or epoch != lease.epoch:
            raise LeaseHeldError(
                f'租约已被接管（现在是 {holder}@{epoch}，'
                f'你是 {lease.holder}@{lease.epoch}）：不能再写')
        ttl_value = float(ttl) if ttl is not None else self.lease_ttl
        renewed = Lease(deployment_id=lease.deployment_id,
                        holder=lease.holder, epoch=lease.epoch,
                        expires_at=time.time() + ttl_value, ttl=ttl_value)
        conn.execute(
            'UPDATE runtime_lease SET lease_expires_at = ?, updated_at = ?'
            ' WHERE deployment_id = ?',
            (renewed.expires_at, time.time(), lease.deployment_id))
        conn.commit()
        return renewed

    def release(self, lease: Lease) -> None:
        """主动放租（优雅下线）。只有当前持有者能放。"""
        conn = self._store.get_connection()
        row = conn.execute(
            'SELECT holder, epoch FROM runtime_lease WHERE deployment_id = ?',
            (lease.deployment_id,)).fetchone()
        if row is None:
            return
        if str(row[0]) == lease.holder and int(row[1]) == lease.epoch:
            conn.execute(
                'DELETE FROM runtime_lease WHERE deployment_id = ?',
                (lease.deployment_id,))
            conn.commit()

    def current_lease(self, deployment_id: str) -> Lease | None:
        conn = self._store.get_connection()
        row = conn.execute(
            'SELECT deployment_id, holder, epoch, lease_expires_at'
            ' FROM runtime_lease WHERE deployment_id = ?',
            (deployment_id,)).fetchone()
        if row is None:
            return None
        return Lease(deployment_id=str(row[0]), holder=str(row[1]),
                     epoch=int(row[2]), expires_at=float(row[3]),
                     ttl=self.lease_ttl)

    def takeover(self, deployment_id: str, new_holder: str, *,
                 ttl: float | None = None) -> Lease:
        """显式接管：前置条件是**当前租约已过期**（失联判定）。

        未过期也允许接管吗？不允许 —— 那会制造双主。接管路径有两条：
        租约过期后的 acquire()，或优雅下线后的 release()+acquire()。
        """
        current = self.current_lease(deployment_id)
        if current is not None and not current.expired \
                and current.holder != str(new_holder):
            raise LeaseHeldError(
                f'部署 {deployment_id} 的租约未过期'
                f'（{current.remaining():.1f}s），不能接管')
        return self.acquire(deployment_id, new_holder, ttl=ttl)

    def stale_writes(self, deployment_id: str, epoch: int) -> bool:
        """一个携带 epoch 的写入是否已经过时（围栏判定）。"""
        current = self.current_lease(deployment_id)
        if current is None:
            return False
        return int(epoch) < int(current.epoch)


def _json(payload: dict) -> str:
    import json as _json_mod
    return _json_mod.dumps(payload, ensure_ascii=False, sort_keys=True)


__all__ = [
    'DEFAULT_LEASE_TTL',
    'RUNTIME_LEASE_MIGRATIONS',
    'DeploymentScheduler',
    'Lease',
    'LeaseHeldError',
    'migrate_lease',
]
