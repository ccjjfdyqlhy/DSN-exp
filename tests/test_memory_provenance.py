# tests/test_memory_provenance.py
# roadmap 段 4 的验收测试：可审计的持久记忆。
#
# 验收标准（roadmap 原文）：能回答「这条记忆从哪来、谁改过、
# 为什么被给了模型」。
#
# 落成六组断言：
#   1. 两级模型：Source 不可变，Artifact 带稳定 ID + revision
#   2. 修订/撤回的历史可回放（不物理删除）
#   3. 记忆写入进审计轨（audit.memory_write），内容不进审计（只进摘要）
#   4. 证据闸门：注入由证据决定 —— 撤回的、证据缺失的、证据被篡改的
#      一律不注入；旧 revision 不泄漏
#   5. 披露矩阵：deny 赢 allow；未知受众默认不给；与 L3 ProfileAuthorizer 兼容
#   6. SDK 默认路径：enable_memory=True 时写入真的落审计

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aicf.harness.memory.in_memory import InMemoryStore
from aicf.harness.memory.layers import LayeredMemoryView
from aicf.harness.memory.provenance import (
    ARTIFACT_ACTIVE,
    ARTIFACT_RETRACTED,
    ARTIFACT_SUPERSEDED,
    DisclosureMatrix,
    DisclosureRule,
    MemoryArtifact,
    ProvenanceMemoryStore,
    profile_authorizer_from_matrix,
)
from aicf.infra.observability.audit import AuditLog, AuditStore


@pytest.fixture
def store() -> ProvenanceMemoryStore:
    return ProvenanceMemoryStore(InMemoryStore(), clock=lambda: 1000.0)


# ── 1. 两级模型 ─────────────────────────────────────────────

def test_source_is_immutable_and_digest_sealed(store):
    source = store.add_source('conversation', '用户喜欢清晨跑步', origin='user')
    assert source.source_id.startswith('src-')
    assert source.digest.startswith('sha256:')
    with pytest.raises(Exception):
        source.content = '篡改'  # type: ignore[misc]  frozen dataclass


def test_artifact_has_stable_id_and_revision(store):
    source = store.add_source('user_statement', '用户偏好简洁回复')
    artifact = store.write_artifact('偏好：简洁', [source.source_id], author='alice')
    assert artifact.artifact_id.startswith('art-')
    assert artifact.revision == 1
    assert artifact.status == ARTIFACT_ACTIVE
    assert artifact.author == 'alice'
    assert artifact.source_ids == (source.source_id,)


def test_write_gate_rejects_missing_evidence(store):
    with pytest.raises(KeyError):
        store.write_artifact('凭空解释', ['src-999999'])


# ── 2. 修订 / 撤回历史 ──────────────────────────────────────

def test_revise_creates_new_revision_and_marks_old_superseded(store):
    source = store.add_source('conversation', '原始陈述')
    artifact = store.write_artifact('第一版', [source.source_id])
    revised = store.revise_artifact(artifact.artifact_id, '第二版', author='bob')
    assert revised.revision == 2
    assert revised.author == 'bob'
    history = store.history(artifact.artifact_id)
    assert [a.status for a in history] == [ARTIFACT_SUPERSEDED, ARTIFACT_ACTIVE]
    assert [a.revision for a in history] == [1, 2]
    # 历史**不删除**：第一版文本还在历史里
    assert history[0].text == '第一版'


def test_retract_marks_but_does_not_delete(store):
    source = store.add_source('conversation', '会被撤回的话')
    artifact = store.write_artifact('待撤回', [source.source_id])
    retracted = store.retract_artifact(artifact.artifact_id, reason='用户要求')
    assert retracted.status == ARTIFACT_RETRACTED
    assert store.history(artifact.artifact_id)[-1].status == ARTIFACT_RETRACTED
    # 撤回后再修订是显式错误（先恢复再改，不许悄悄改撤回的记忆）
    with pytest.raises(ValueError):
        store.revise_artifact(artifact.artifact_id, '偷改')


# ── 3. 审计轨 ───────────────────────────────────────────────

def test_memory_writes_landed_in_audit_trail():
    audit = AuditLog(store=AuditStore())
    store = ProvenanceMemoryStore(InMemoryStore(), audit=audit, clock=lambda: 1.0)
    source = store.add_source('conversation', '原始陈述')
    artifact = store.write_artifact('解释一', [source.source_id])
    store.revise_artifact(artifact.artifact_id, '解释二')
    store.retract_artifact(artifact.artifact_id)

    records = audit.of_kind('audit.memory_write')
    actions = [r.payload['action'] for r in records]
    assert actions == ['source_added', 'artifact_written',
                       'artifact_revised', 'artifact_retracted']
    # 「谁改过」可从审计回答
    revised = [r for r in records if r.payload['action'] == 'artifact_revised'][0]
    assert revised.payload['artifact_id'] == artifact.artifact_id
    assert revised.payload['revision'] == 2


def test_audit_payload_has_no_plaintext_content():
    audit = AuditLog(store=AuditStore())
    store = ProvenanceMemoryStore(
        InMemoryStore(), audit=audit, clock=lambda: 1.0)
    secret = '机密内容-不应出现在审计-SECRET-9f3a'
    source = store.add_source('conversation', secret)
    store.write_artifact(f'解释引用了{secret}', [source.source_id])
    for record in audit.of_kind('audit.memory_write'):
        blob = str(record.payload)
        assert secret not in blob
        assert record.payload.get('content_digest') or \
            record.payload.get('action') == 'artifact_retracted'


# ── 4. 证据闸门 ─────────────────────────────────────────────

def test_recall_returns_artifact_text(store):
    source = store.add_source('conversation', '项目使用 SQLite 存储')
    store.write_artifact('存储选型：SQLite', [source.source_id])
    hits = store.recall('存储 选型')
    assert any('SQLite' in e.text for e in hits)


def test_retracted_memory_is_not_injected(store):
    source = store.add_source('conversation', '临时偏好')
    artifact = store.write_artifact('临时偏好：深色主题', [source.source_id])
    assert store.recall('主题')
    store.retract_artifact(artifact.artifact_id)
    assert store.recall('主题') == []


def test_superseded_revision_text_does_not_leak(store):
    source = store.add_source('conversation', '偏好来源')
    artifact = store.write_artifact('旧偏好：咖啡', [source.source_id])
    store.revise_artifact(artifact.artifact_id, '新偏好：茶')
    texts = [e.text for e in store.recall('偏好')]
    assert texts == ['新偏好：茶'], f'旧 revision 泄漏: {texts}'


def test_tampered_evidence_blocks_injection(store):
    source = store.add_source('file', '证据原文')
    store.write_artifact('来自证据的解释', [source.source_id])
    assert store.recall('证据')
    # 绕过 frozen 直接改底层内容 —— 证据闸门靠摘要重算发现篡改
    object.__setattr__(source, 'content', '被篡改的内容')
    assert store.recall('证据') == [], '证据被篡改却不拦截'


def test_missing_evidence_blocks_injection():
    store = ProvenanceMemoryStore(InMemoryStore(), clock=lambda: 1.0)
    source = store.add_source('conversation', '原文')
    store.write_artifact('解释', [source.source_id])
    # 证据被外部清掉（模拟存储丢失）
    store._sources.clear()
    assert store.recall('解释') == []


def test_foreign_entries_are_denied_by_default():
    """没走本库写入的条目（外部直塞 backend）没有证据 → 不注入。"""
    backend = InMemoryStore()
    backend.add_text('来路不明的记忆', role='memo')
    store = ProvenanceMemoryStore(backend, clock=lambda: 1.0)
    assert store.recall('记忆') == []


# ── 5. 披露矩阵 ─────────────────────────────────────────────

def _artifact_with_tags(tags) -> MemoryArtifact:
    return MemoryArtifact(
        artifact_id='art-test', revision=1, text='x', source_ids=(),
        author='', created_at=0.0, updated_at=0.0,
        status=ARTIFACT_ACTIVE, tags=tuple(tags))


def test_disclosure_deny_beats_allow():
    matrix = DisclosureMatrix([
        DisclosureRule(audience='*', tag='*', allow=True),
        DisclosureRule(audience='intern', tag='salary', allow=False),
    ])
    assert matrix.disclose(_artifact_with_tags(('salary',)), 'intern') is False
    assert matrix.disclose(_artifact_with_tags(('salary',)), 'owner') is True
    assert matrix.disclose(_artifact_with_tags(('note',)), 'intern') is True


def test_disclosure_defaults_to_deny():
    matrix = DisclosureMatrix()
    assert matrix.disclose(_artifact_with_tags(('anything',)), 'anyone') is False


def test_disclosure_prefers_most_specific_rule():
    matrix = DisclosureMatrix([
        DisclosureRule(audience='*', tag='*', allow=False),
        DisclosureRule(audience='doctor', tag='medical', allow=True),
    ])
    assert matrix.disclose(_artifact_with_tags(('medical',)), 'doctor') is True
    # 精确受众规则赢过通配受众规则
    strict = DisclosureMatrix([
        DisclosureRule(audience='*', tag='medical', allow=True),
        DisclosureRule(audience='intern', tag='medical', allow=False),
    ])
    assert strict.disclose(_artifact_with_tags(('medical',)), 'intern') is False


def test_recall_respects_disclosure_matrix():
    matrix = DisclosureMatrix([
        DisclosureRule(audience='*', tag='*', allow=True),
        DisclosureRule(audience='guest', tag='private', allow=False),
    ])
    backend = InMemoryStore()
    store = ProvenanceMemoryStore(backend, disclosure=matrix, clock=lambda: 1.0)
    source = store.add_source('user_statement', '私密信息')
    store.write_artifact('私人事项', [source.source_id], tags=('private',))
    assert store.recall('私人', audience='owner')
    assert store.recall('私人', audience='guest') == []


def test_profile_authorizer_uses_matrix_and_fails_closed():
    matrix = DisclosureMatrix([
        DisclosureRule(audience='app', tag='alice', allow=True),
    ])
    authorize = profile_authorizer_from_matrix(matrix, audience='app')
    assert authorize('alice') is True       # 显式 allow 规则
    assert authorize('bob') is False        # 无规则 → 默认拒绝
    empty = profile_authorizer_from_matrix(DisclosureMatrix(), audience='app')
    assert empty('alice') is False          # 没有规则 = 全部拒绝


def test_profile_authorizer_feeds_layered_memory_view():
    """与 L3 的接线：LayeredMemoryView 的 profile_authorized 收矩阵适配器。"""
    matrix = DisclosureMatrix([
        DisclosureRule(audience='app', tag='alice', allow=True),
    ])

    class _Entry:
        def __init__(self, text, layer, meta):
            self.text, self.layer, self.meta = text, layer, meta

    view = LayeredMemoryView(
        profile_authorized=profile_authorizer_from_matrix(matrix, audience='app'))
    memories = [
        _Entry('被授权的偏好', 'L3', {'subject': 'alice'}),
        _Entry('未授权的偏好', 'L3', {'subject': 'bob'}),
    ]
    pairs = view.assemble(memories, 200, query='偏好')
    texts = [text for _layer, text in pairs]
    assert '被授权的偏好' in texts
    assert '未授权的偏好' not in texts


# ── 6. SDK 默认路径 ─────────────────────────────────────────

def test_sdk_enable_memory_writes_into_audit_trail():
    """enable_memory=True 的默认路径：写入落 audit.memory_write。"""
    from aicf.harness import create_agent
    from aicf.infra.orchestrator.base import ChatResponse
    from aicf.infra.orchestrator.stub import StubChatClient

    def respond(messages, tools):
        return ChatResponse(content='好的，我记住了')

    agent = create_agent(client=StubChatClient(model='stub', respond=respond),
                         enable_memory=True)
    agent.chat('我喜欢清晨跑步')

    memory = agent._memory_store()
    assert memory is not None
    # 两级模型在默认路径上生效
    from aicf.harness.memory.provenance import ProvenanceMemoryStore
    assert isinstance(memory, ProvenanceMemoryStore)
    # 审计轨上有完整的「这条记忆从哪来、谁写的」
    audit_log = agent._assembled.runtime.get('audit_log')
    assert audit_log is not None
    records = audit_log.of_kind('audit.memory_write')
    actions = [r.payload['action'] for r in records]
    assert 'source_added' in actions and 'artifact_written' in actions
    # 召回结果过证据闸门（正常路径能召回）
    assert agent._memory_store().recall('清晨 跑步')


def test_sdk_security_audit_false_keeps_plain_store():
    """security_audit=False 是显式关闭 —— 记忆回到普通实现，但得显式选。"""
    from aicf.harness import create_agent
    from aicf.infra.orchestrator.base import ChatResponse
    from aicf.infra.orchestrator.stub import StubChatClient

    agent = create_agent(
        client=StubChatClient(model='stub',
                              respond=lambda m, t: ChatResponse(content='ok')),
        enable_memory=True, security_audit=False)
    memory = agent._memory_store()
    assert isinstance(memory, InMemoryStore)
    assert not isinstance(memory, ProvenanceMemoryStore)
