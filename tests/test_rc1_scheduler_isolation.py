# tests/test_rc1_scheduler_isolation.py
# 部署租约与接管（infra/runtime/scheduler.py，策划案 §4.2.4 / rc2 P1）
# 与工作区隔离（infra/runtime/isolation.py，策划案 §4.2.5 / rc2 P3）。
#
# P1 的验收标准（策划案 §7.3）：实例 lease 超时可被接管；
# 状态不丢、结果不重复 —— 「结果不重复」由围栏令牌（epoch）保证。

from __future__ import annotations

import os
import time

import pytest

from aicf.infra.runtime.isolation import (
    IsolationError,
    WorkspaceManager,
    WorkspaceSpec,
    contains_path,
)
from aicf.infra.runtime.scheduler import (
    DEFAULT_LEASE_TTL,
    DeploymentScheduler,
    LeaseHeldError,
)
from aicf.infra.runtime.state import DeploymentStatus
from aicf.infra.store.sqlite import SqliteStore


@pytest.fixture()
def scheduler(tmp_path):
    return DeploymentScheduler(SqliteStore(str(tmp_path / 'rt.db')))


# ── 租约 ─────────────────────────────────────────────────
def test_acquire_gives_epoch_one(scheduler):
    scheduler.register_deployment('dep-1', artifact_id='research',
                                  artifact_version='0.4.2')
    lease = scheduler.acquire('dep-1', 'instance-a')
    assert lease.holder == 'instance-a'
    assert lease.epoch == 1
    assert not lease.expired
    assert lease.remaining() > 0
    assert lease.ttl == DEFAULT_LEASE_TTL


def test_second_instance_cannot_acquire_a_live_lease(scheduler):
    """策划案 §4.2.4：失联（超时未续约）之前，别人不能接管。"""
    scheduler.register_deployment('dep-1')
    scheduler.acquire('dep-1', 'a')
    with pytest.raises(LeaseHeldError):
        scheduler.acquire('dep-1', 'b')


def test_same_holder_reacquires_without_bumping_epoch(scheduler):
    scheduler.register_deployment('dep-1')
    lease = scheduler.acquire('dep-1', 'a', ttl=60)
    again = scheduler.acquire('dep-1', 'a', ttl=60)
    assert again.epoch == lease.epoch


def test_takeover_after_lease_expiry_bumps_epoch(scheduler):
    """lease 超时 → 其他实例接管（epoch+1 = 围栏令牌）。"""
    scheduler.register_deployment('dep-1')
    old = scheduler.acquire('dep-1', 'a', ttl=0.05)
    time.sleep(0.08)
    new = scheduler.takeover('dep-1', 'b')
    assert new.holder == 'b'
    assert new.epoch == old.epoch + 1


def test_takeover_is_refused_while_lease_is_live(scheduler):
    scheduler.register_deployment('dep-1')
    scheduler.acquire('dep-1', 'a', ttl=60)
    with pytest.raises(LeaseHeldError):
        scheduler.takeover('dep-1', 'b')


def test_stale_holder_cannot_renew_after_takeover(scheduler):
    """围栏：旧实例的续约在接管后必须被拒 —— 这是「结果不重复」的保证。"""
    scheduler.register_deployment('dep-1')
    old = scheduler.acquire('dep-1', 'a', ttl=0.05)
    time.sleep(0.08)
    scheduler.takeover('dep-1', 'b')
    with pytest.raises(LeaseHeldError):
        scheduler.renew(old)


def test_stale_writes_are_fenced(scheduler):
    scheduler.register_deployment('dep-1')
    old = scheduler.acquire('dep-1', 'a', ttl=0.05)
    time.sleep(0.08)
    scheduler.takeover('dep-1', 'b')
    assert scheduler.stale_writes('dep-1', old.epoch) is True
    assert scheduler.stale_writes('dep-1', old.epoch + 1) is False


def test_release_then_reacquire(scheduler):
    """优雅下线 → 新实例立刻接手（不用等过期）。"""
    scheduler.register_deployment('dep-1')
    lease = scheduler.acquire('dep-1', 'a', ttl=60)
    scheduler.release(lease)
    assert scheduler.current_lease('dep-1') is None
    fresh = scheduler.acquire('dep-1', 'b')
    assert fresh.holder == 'b'
    # 旧实例不能用旧租约放租或续约
    scheduler.release(lease)          # 幂等：不是持有者，什么都不发生
    with pytest.raises(LeaseHeldError):
        scheduler.renew(lease)


def test_renew_extends_expiry(scheduler):
    scheduler.register_deployment('dep-1')
    lease = scheduler.acquire('dep-1', 'a', ttl=0.1)
    renewed = scheduler.renew(lease, ttl=30)
    assert renewed.remaining() > 20
    assert renewed.epoch == lease.epoch


def test_deployment_status_transitions(scheduler):
    scheduler.register_deployment('dep-1')
    dep = scheduler.get_deployment('dep-1')
    assert dep['status'] == DeploymentStatus.PENDING.value
    scheduler.set_status('dep-1', DeploymentStatus.HEALTHY)
    assert scheduler.get_deployment('dep-1')['status'] == 'healthy'


def test_lease_migration_is_idempotent(tmp_path):
    store = SqliteStore(str(tmp_path / 'm.db'))
    from aicf.infra.runtime.scheduler import migrate_lease
    first = migrate_lease(store)
    assert first == ['rc2_lease_001']
    assert migrate_lease(store) == []


# ── 工作区隔离 ───────────────────────────────────────────
@pytest.fixture()
def manager(tmp_path):
    return WorkspaceManager(base=tmp_path / 'workspaces')


def test_workspace_allocates_a_per_session_root(manager, tmp_path):
    ws = manager.allocate('sess-1')
    assert ws.root == str(tmp_path / 'workspaces' / 'sess-1')
    assert os.path.isdir(ws.root)
    assert ws.status == 'ready'
    ws2 = manager.allocate('sess-2')
    assert ws2.root != ws.root


def test_workspace_requires_a_session():
    manager = WorkspaceManager(base='/tmp/never-created-rc1')
    with pytest.raises(IsolationError):
        manager.allocate('')


def test_path_inside_the_workspace_passes(manager):
    ws = manager.allocate('sess-1')
    resolved = manager.check_path(ws, os.path.join(ws.root, 'out', 'a.txt'),
                                  write=True)
    assert str(resolved).startswith(ws.root)


def test_path_escape_is_blocked(manager, tmp_path):
    """策划案 §8.2 用例 4：`../` 与符号链接逃逸要被拦。"""
    ws = manager.allocate('sess-1')
    outside = tmp_path / 'secret.txt'
    outside.write_text('x')
    with pytest.raises(IsolationError):
        manager.check_path(ws, outside)
    with pytest.raises(IsolationError):
        manager.check_path(ws, os.path.join(ws.root, '..', 'escape.txt'))
    # 符号链接逃逸
    link = os.path.join(ws.root, 'link')
    os.symlink(str(tmp_path), link)
    with pytest.raises(IsolationError):
        manager.check_path(ws, os.path.join(link, 'secret.txt'))


def test_fs_none_rejects_all_file_access(manager):
    ws = manager.allocate('sess-1', spec=WorkspaceSpec(fs='none'))
    with pytest.raises(IsolationError):
        manager.check_path(ws, os.path.join(ws.root, 'a.txt'))


def test_fs_full_allows_outside_paths_only_when_declared(manager, tmp_path):
    ws = manager.allocate('sess-1', spec=WorkspaceSpec(fs='full'))
    assert manager.check_path(ws, tmp_path / 'anywhere.txt') is not None


def test_locked_workspace_refuses_writes(manager):
    ws = manager.allocate('sess-1')
    manager.lock(ws)
    with pytest.raises(IsolationError):
        manager.check_path(ws, os.path.join(ws.root, 'a.txt'), write=True)
    manager.release(ws)
    # released = 一次运行的工作区已交还 —— 写入同样被拒（状态面的闸门）
    with pytest.raises(IsolationError):
        manager.check_path(ws, os.path.join(ws.root, 'a.txt'), write=True)
    # 只读访问仍允许（产物要能被取走）
    assert manager.check_path(ws, os.path.join(ws.root, 'a.txt')) is not None


def test_net_check_enforces_the_allowlist(manager):
    ws = manager.allocate('sess-1', spec=WorkspaceSpec(
        net='allowlist', net_allowlist=('example.com',)))
    assert manager.net_check(ws, 'example.com') is True
    assert manager.net_check(ws, 'sub.example.com') is True   # 子域包含
    assert manager.net_check(ws, 'evil-example.com') is False
    assert manager.net_check(ws, 'evil.com') is False
    none_ws = manager.allocate('sess-2', spec=WorkspaceSpec(net='none'))
    assert manager.net_check(none_ws, 'example.com') is False
    full_ws = manager.allocate('sess-3', spec=WorkspaceSpec(net='full'))
    assert manager.net_check(full_ws, 'anything.dev') is True


def test_workspace_spec_round_trip():
    spec = WorkspaceSpec(net='allowlist', net_allowlist=('a.com',))
    assert WorkspaceSpec.from_dict(spec.to_dict()) == spec
    assert WorkspaceSpec.from_dict(None) == WorkspaceSpec()


def test_contains_path_matches_the_sandbox_judgement():
    """与 harness/tools/sandbox/paths.py 的判定钉在一起（R-10 模式）。"""
    from aicf.harness.tools.sandbox.paths import is_within
    root = '/tmp/rc1-cross-check/root'
    inside = '/tmp/rc1-cross-check/root/sub/file.txt'
    outside = '/tmp/rc1-cross-check/other/file.txt'
    assert contains_path(root, inside) is True
    assert contains_path(root, outside) is False
    # 两份实现方向一致（API 形状允许不同，结论必须一致）
    assert is_within(root, inside) == contains_path(root, inside)
    assert is_within(root, outside) == contains_path(root, outside)
