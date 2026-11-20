# tests/test_rc1_control.py
# 控制面（infra/control）的测试 —— 策划案 §4.5 / rc1 C2 C4 C5。
#
# 每条用例对应策划案的一条验收标准：
#   - artifact 版本不可变（§4.5.3）
#   - 发布必须携带通过的 Gate 报告（§4.5.2）
#   - 生命周期迁移是**不可变事件**（§4.5.2）
#   - 成本账本按 session/agent/tool/model 归因（§4.5.3）
#   - BYO 按 RuntimeClient 协议接入（§4.5.4）

from __future__ import annotations

import os

import pytest

from infra.control import (
    AgentArtifact,
    AgentIdentity,
    ArtifactError,
    ArtifactState,
    ArtifactStore,
    ByoRegistry,
    CostLedger,
    DelegationError,
    LifecycleError,
    VersionConflictError,
    check_transition,
    delegate,
    derive_child,
    load_artifact,
    price_tokens,
    validate_delegation,
)
from infra.control.lifecycle import allowed_actions
from infra.store.sqlite import SqliteStore

ARTIFACT_YAML = """
apiVersion: aicf.dev/v1
kind: Agent
metadata:
  name: research-assistant
  owner: team-research
  version: 0.4.2
spec:
  kernel: react
  model:
    primary: deepseek-chat
    fallback: [glm-4.6]
  context:
    layers: [L0, L1, L2]
    budget: 128000
  tools:
    - shell@v3
    - fs.read@v1
  policies:
    approval: [shell@v3]
    network: allowlist
  cost_model:
    per_1k_tokens: {input: 0.002, output: 0.008}
"""


def _store(tmp_path):
    return ArtifactStore(SqliteStore(str(tmp_path / 'control.db')))


# ── artifact 声明 ─────────────────────────────────────────
def test_artifact_parses_the_design_doc_shape():
    a = AgentArtifact.from_yaml(ARTIFACT_YAML)
    assert a.name == 'research-assistant'
    assert a.version == '0.4.2'
    assert a.metadata.owner == 'team-research'
    assert a.spec_kernel == 'react'
    assert a.spec_tools == ('shell@v3', 'fs.read@v1')
    assert a.spec_model.primary == 'deepseek-chat'
    assert a.spec_context.layers == ('L0', 'L1', 'L2')
    assert a.spec_policies.approval == ('shell@v3',)


def test_artifact_content_hash_is_canonical():
    a1 = AgentArtifact.from_yaml(ARTIFACT_YAML)
    # 同一内容、不同键序 → 同一哈希（规范 JSON）
    reordered = ARTIFACT_YAML.replace(
        'name: research-assistant\n  owner: team-research',
        'owner: team-research\n  name: research-assistant')
    a2 = AgentArtifact.from_yaml(reordered)
    assert a1.content_hash() == a2.content_hash()
    # 内容不同 → 哈希不同
    a3 = AgentArtifact.from_yaml(ARTIFACT_YAML.replace('budget: 128000',
                                                       'budget: 64000'))
    assert a1.content_hash() != a3.content_hash()


def test_artifact_rejects_unknown_kernel_and_bad_tool_ref():
    with pytest.raises(ArtifactError):
        AgentArtifact.from_yaml(ARTIFACT_YAML.replace('kernel: react',
                                                      'kernel: quantum'))
    with pytest.raises(ArtifactError):
        AgentArtifact.from_yaml(ARTIFACT_YAML.replace('- shell@v3',
                                                      '- shell @v3'))
    with pytest.raises(ArtifactError):
        # 没有 metadata.name 的资产无法被纳管
        AgentArtifact.from_yaml(ARTIFACT_YAML.replace('name: research-assistant',
                                                      'name: ""'))


def test_example_artifacts_ship_with_the_repo():
    """策划案 §6.1：agents/ 目录要有示例 artifact。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    research = load_artifact(os.path.join(root, 'agents', 'research.yaml'))
    assert research.name == 'research-assistant'
    study = load_artifact(os.path.join(root, 'agents', 'study.yaml'))
    assert study.spec_kernel == 'planner'
    # run_version 的默认 artifact 路径必须真的存在
    from infra.eval.run_version import DEFAULT_ARTIFACT
    assert os.path.exists(os.path.join(root, DEFAULT_ARTIFACT))


# ── 生命周期 ──────────────────────────────────────────────
def test_lifecycle_requires_gate_report_for_release():
    # release 不带报告 → 拒绝（§4.5.2「必须携带通过的 Gate 报告」）
    with pytest.raises(LifecycleError):
        check_transition('approved', 'release', gate_report_id='')
    # 带了但不存在的报告 → 拒绝
    with pytest.raises(LifecycleError):
        check_transition('approved', 'release', gate_report_id='g1',
                         gate_lookup=lambda gid: None)
    # 带了但判定不是 pass → 拒绝
    with pytest.raises(LifecycleError):
        check_transition('approved', 'release', gate_report_id='g1',
                         gate_lookup=lambda gid: {'verdict': 'fail'})
    # 通过的报告 → 放行（release 还必须给 reason —— 迁移要可追责）
    with pytest.raises(LifecycleError):
        check_transition('approved', 'release', gate_report_id='g1',
                         gate_lookup=lambda gid: {'verdict': 'pass'})
    assert check_transition('approved', 'release', gate_report_id='g1',
                            reason='rc1 发布', gate_lookup=lambda gid: {'verdict': 'pass'}) \
        is ArtifactState.RELEASED


def test_lifecycle_rejects_illegal_transitions():
    with pytest.raises(LifecycleError):
        check_transition('draft', 'release')
    with pytest.raises(LifecycleError):
        check_transition('archived', 'review')      # 终态
    with pytest.raises(LifecycleError):
        check_transition('approved', 'nonsense')
    # reject / rollback 必须给理由（迁移要可追责）
    with pytest.raises(LifecycleError):
        check_transition('reviewing', 'reject', reason='')
    assert check_transition('reviewing', 'reject', reason='不合格') \
        is ArtifactState.DISPUTED


def test_lifecycle_rollback_only_goes_one_step():
    assert check_transition('released', 'rollback', reason='回归') \
        is ArtifactState.ROLLED_BACK
    assert check_transition('rolled_out', 'rollback', reason='回归') \
        is ArtifactState.ROLLED_BACK
    # 回滚后回到评审线，可再次发布
    assert check_transition('rolled_back', 'review') is ArtifactState.REVIEWING
    assert 'release' in allowed_actions('approved')


# ── 存储 ──────────────────────────────────────────────────
def test_store_publish_requires_passing_gate(tmp_path):
    store = _store(tmp_path)
    # 没有 gate_lookup 时发布被拒 —— 发布绝不能默认放行
    art = AgentArtifact.from_yaml(ARTIFACT_YAML)
    with pytest.raises(LifecycleError):
        store.publish(art, actor='op', gate_report_id='g1')
    assert store.list_artifacts() == []   # 失败的发布不留下任何中间态


def test_store_publish_with_passing_gate(tmp_path):
    store = ArtifactStore(SqliteStore(str(tmp_path / 'control.db')),
                          gate_lookup=lambda gid: {'verdict': 'pass'})
    art = AgentArtifact.from_yaml(ARTIFACT_YAML)
    event = store.publish(art, actor='op', gate_report_id='g1')
    assert event.to_state == 'released'
    assert event.gate_report_id == 'g1'
    record = store.get_artifact(art.id, art.version)
    assert record.state == 'released'
    # 生命周期事件链完整且不可变（只追加）
    events = store.lifecycle_events(art.id, art.version)
    assert [(e.action, e.to_state) for e in events] == [
        ('review', 'reviewing'), ('approve', 'approved'),
        ('release', 'released')]


def test_store_version_is_immutable(tmp_path):
    """策划案 §4.5.3：版本不可变，禁止原地改。"""
    store = _store(tmp_path)
    art = AgentArtifact.from_yaml(ARTIFACT_YAML)
    store.put_artifact(art)
    # 同版本不同内容 → 拒绝
    mutated = AgentArtifact.from_yaml(ARTIFACT_YAML.replace('budget: 128000',
                                                            'budget: 1'))
    with pytest.raises(VersionConflictError):
        store.put_artifact(mutated)
    # 同版本同内容 → 幂等放行
    store.put_artifact(art)
    # 改内容要升版本 —— 新版本正常登记
    bumped = AgentArtifact.from_yaml(
        ARTIFACT_YAML.replace('version: 0.4.2', 'version: 0.4.3'))
    store.put_artifact(bumped)
    assert store.latest_version(art.id).version == '0.4.3'


# ── 成本账本 ──────────────────────────────────────────────
def test_cost_ledger_attributions(tmp_path):
    store = SqliteStore(str(tmp_path / 'control.db'))
    ledger = CostLedger(store)
    ledger.record(session_id='s1', agent_id='research', tool='fs.read',
                  model='m1', tokens=1000,
                  cost=price_tokens({'input': 0.002}, 1000, 0))
    ledger.record(session_id='s1', agent_id='research', tool='fs.write',
                  model='m1', tokens=500, cost=0.01)
    ledger.record(session_id='s2', agent_id='study', tool='fs.read',
                  model='m2', tokens=2000, cost=0.02)
    assert abs(ledger.session_total('s1') - 0.012) < 1e-9
    assert ledger.by_agent('research')['cost'] == pytest.approx(0.012)
    assert ledger.by_tool('fs.read')['calls'] == 2
    assert ledger.by_model('m2')['tokens'] == 2000
    breakdown = ledger.breakdown(session_id='s1')
    assert {row['tool'] for row in breakdown} == {'fs.read', 'fs.write'}


def test_price_tokens_never_guesses_prices():
    # 没声明单价时返回 0 —— 记账要全量（tokens 照记），折价不猜
    assert price_tokens({}, 1000, 1000) == 0.0
    assert price_tokens({'input': 0.002, 'output': 0.008}, 1000, 500) \
        == pytest.approx(0.002 + 0.004)


# ── BYO 纳管 ──────────────────────────────────────────────
class FakeRuntimeHost:
    """满足 RuntimeClient 协议的假外部进程。"""

    def __init__(self):
        self.events = []

    def emit(self, kind, payload):
        self.events.append((kind, payload))

    def record_tool_intent(self, intent):
        pass

    def record_tool_result(self, key, result, *, effect='pure'):
        pass

    def lookup_tool_result(self, key):
        return None

    def idempotency_key(self, session_id, turn_seq, tool, args=None):
        return 'key'

    def checkpoint(self, state):
        return None


class Mirror:
    def __init__(self):
        self.seen = []

    def emit(self, payload):
        self.seen.append(payload)


def test_byo_adoption_requires_the_runtime_client_protocol():
    from infra.control.adoption import AdoptionError
    reg = ByoRegistry()
    with pytest.raises(AdoptionError):
        reg.adopt('bad-agent', object())          # 缺协议方法
    with pytest.raises(AdoptionError):
        reg.adopt('', FakeRuntimeHost())          # 没名字
    view = reg.adopt('ext-agent', FakeRuntimeHost(),
                     capabilities=('events', 'cost'))
    assert view.record.mode == 'byo'
    assert reg.get('ext-agent') is view
    assert reg.record_of('ext-agent').capabilities == ('events', 'cost')
    assert [r.agent_id for r in reg.agents()] == ['ext-agent']
    assert reg.release('ext-agent') is True
    assert reg.get('ext-agent') is None


def test_byo_view_mirrors_events_to_the_platform():
    """BYO 进程的事件要能被平台看到 —— 纳管的意义。"""
    mirror = Mirror()
    reg = ByoRegistry(mirror=mirror)
    host = FakeRuntimeHost()
    view = reg.adopt('ext-agent', host)
    view.emit('run_started', {'session_id': 's1'})
    view.record_tool_result('key', {'ok': True}, effect='pure')
    # 宿主收到了原样事件
    assert host.events[0][0] == 'run_started'
    # 平台镜像也收到了（带 agent 归属）
    assert mirror.seen[0]['agent_id'] == 'ext-agent'
    assert mirror.seen[0]['kind'] == 'run_started'


def test_byo_lookup_and_idempotency_pass_through():
    reg = ByoRegistry()
    view = reg.adopt('ext', FakeRuntimeHost())
    assert view.lookup_tool_result('nope') is None
    assert view.idempotency_key('s', 1, 't', {}) == 'key'
    assert view.checkpoint({}) is None


# ── AgentIdentity / 委托 ─────────────────────────────────
def test_delegation_requires_subset_scopes():
    """策划案 §4.4.5：父授子的 scope 必须是父 scope 的子集。"""
    parent = AgentIdentity(agent_id='root',
                           scopes=('fs.read', 'fs.write', 'net.call'))
    child = derive_child(parent, agent_id='sub', scopes=('fs.read',))
    assert child.scopes == ('fs.read',)
    assert child.delegated_by == 'root'
    assert child.delegation_chain == ('root',)
    # 越权 → 拒绝（§4.4.5「越权即拒」）
    with pytest.raises(DelegationError):
        derive_child(parent, agent_id='bad', scopes=('net.admin',))
    with pytest.raises(DelegationError):
        validate_delegation(parent, ('fs.read', 'not-granted'))


def test_delegation_chain_records_the_full_path():
    """delegation_chain 完整记录授权路径，可回答「权限最初从哪来」。"""
    root = AgentIdentity(agent_id='root', scopes=('a', 'b'))
    mid = derive_child(root, agent_id='mid', scopes=('a',))
    leaf = derive_child(mid, agent_id='leaf', scopes=('a',))
    assert leaf.delegation_chain == ('root', 'mid')
    assert leaf.delegated_by == 'mid'
    # 链条上每一跳都只能收窄（§4.4.5「可审计、可截断」）
    with pytest.raises(DelegationError):
        derive_child(leaf, agent_id='rogue', scopes=('b',))


def test_delegate_records_an_audit_event():
    from infra.observability.audit import AuditLog
    audit = AuditLog()
    parent = AgentIdentity(agent_id='root', scopes=('fs.read',))
    _child, payload = delegate(parent, agent_id='sub', scopes=('fs.read',),
                               audit=audit)
    records = audit.of_kind('audit.delegation')
    assert len(records) == 1
    data = dict(records[0].payload)
    assert data['from'] == 'root'
    assert data['to'] == 'sub'
    assert data['scopes'] == ['fs.read']
    # payload 是审计的内存镜像（可被上层再消费）
    assert payload.to_dict()['from'] == 'root'


def test_delegate_survives_audit_backend_failure():
    class BrokenAudit:
        def delegation(self, *args, **kwargs):
            raise RuntimeError('audit backend down')

    parent = AgentIdentity(agent_id='root', scopes=('fs.read',))
    child, _ = delegate(parent, agent_id='sub', scopes=('fs.read',),
                        audit=BrokenAudit())
    assert child.agent_id == 'sub'    # 授权成立；审计失败不回滚授权


def test_agent_identity_scope_check_helper():
    ident = AgentIdentity(agent_id='a', scopes=('fs.read',))
    assert ident.missing_scopes(('fs.read', 'net.call')) == ('net.call',)
    assert ident.has_scope('fs.read')
    assert not ident.has_scope('net.call')
    # spawn 前校验入口与委托校验同义
    with pytest.raises(DelegationError):
        from infra.control import check_spawn_scopes
        check_spawn_scopes(ident, ('net.call',))


def test_identity_round_trip():
    ident = AgentIdentity(agent_id='x', tenant='t1', scopes=('s',),
                          delegated_by='p', delegation_chain=('p',),
                          credential_refs=('vault://x',))
    assert AgentIdentity.from_dict(ident.to_dict()) == ident
