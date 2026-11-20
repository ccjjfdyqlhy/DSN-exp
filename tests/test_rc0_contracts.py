# tests/test_rc0_contracts.py
# rc0 共享契约层的契约测试。
#
# 这一层的价值在于：所有并行开发的工作流都编译在同一组协议上。
# 协议一旦漂移，后面每个工作流的测试都会以「莫名其妙的方式」失败。
# 所以这里把协议的**形状**（字段名、默认值、方向性）钉死。

from __future__ import annotations

import dataclasses
import importlib

import pytest


# ── 导入面 ──────────────────────────────────────────────
CONTRACT_MODULES = [
    'aicf.harness.tools.spec',
    'aicf.harness.policy.base',
    'aicf.harness.approval.base',
    'aicf.harness.tools.sandbox.base',
    'aicf.harness.telemetry.base',
    'aicf.harness.runtime_client',
]


@pytest.mark.parametrize('name', CONTRACT_MODULES)
def test_contract_modules_import(name):
    importlib.import_module(name)


#: 允许在模块级依赖 infra 的 harness 模块 —— 每个都要有理由。
#:
#: 端口与共享数据类型住在 infra（IChatClient、IStore、Identity、PolicyDecision
#: 都是这个模式），harness 往上依赖它们是**允许**的方向。
#: 反过来（infra import aicf.harness）才是违规。
INFRA_DEPENDENCY_EXEMPT = {
    # 只是 infra/policy/base.py 的再导出薄壳，让 harness 侧能用短路径。
    'aicf.harness.policy.base': '端口定义在 aicf/infra/policy/base.py，这里只做再导出',
    # 同理：span 的数据形状与 id 生成住在 infra/observability/span.py
    # （共享原语住 infra，harness 往上依赖它），这里只做再导出。
    # TelemetryPort 协议本身仍然**定义**在内核侧，没有被搬走。
    'aicf.harness.telemetry.base': '共享原语定义在 aicf/infra/observability/span.py，这里只做再导出',
}


@pytest.mark.parametrize('name', CONTRACT_MODULES)
def test_contract_modules_do_not_import_infra(name):
    """契约层属于 harness：它不得依赖 infra 的**实现**，否则依赖方向就反了。

    只允许在函数体里延迟 import（那是应用装配时的事），
    模块级 import aicf.infra 一律不允许 —— 除非在白名单里且写明理由。
    """
    module = importlib.import_module(name)
    source = open(module.__file__, encoding='utf-8').read()
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith(('import aicf.infra', 'from aicf.infra')):
            if name in INFRA_DEPENDENCY_EXEMPT:
                continue
            pytest.fail(f'{name} 在模块级依赖了 infra: {stripped}')


# ── ToolSpec ────────────────────────────────────────────
def test_tool_spec_defaults_are_the_strictest():
    """未声明 = 最严格（策划案 §3.3.1「默认拒绝」）。"""
    from aicf.harness.tools.spec import ToolSpec
    spec = ToolSpec(name='x')
    assert spec.effect == 'effectful'
    assert spec.sandbox == 'isolated'
    assert spec.network == 'none'
    assert spec.requires_approval is True
    assert spec.replay_safe is False


def test_tool_spec_read_only_default_is_narrow():
    from aicf.harness.tools.spec import ToolSpec
    spec = ToolSpec.read_only_default('x')
    assert spec.effect == 'pure'
    assert spec.sandbox == 'readonly'
    assert spec.requires_approval is False
    assert spec.replay_safe is True


def test_stricter_than_never_loosens():
    """合并两份声明时只能取更严格的那一份 —— 取宽松的等于静默放开权限。"""
    from aicf.harness.tools.spec import ToolSpec, stricter_than
    strict = ToolSpec(name='x', effect='effectful', sandbox='isolated',
                       network='none')
    loose = ToolSpec(name='x', effect='pure', sandbox='readonly',
                      network='full')
    for a, b in ((strict, loose), (loose, strict)):
        merged = stricter_than(a, b)
        assert merged.effect == 'effectful'
        assert merged.sandbox == 'isolated'
        assert merged.network == 'full'


# ── PolicyDecision ──────────────────────────────────────
def test_policy_decision_field_defaults_are_bools():
    """回归：classmethod 与 dataclass 字段同名会让默认值变成 bound method。

    这个坑踩过一次 —— needs_approval 既是字段又是 classmethod，
    类体里后定义的方法覆盖了字段默认值 False，于是每个 PolicyDecision
    的 needs_approval 都成了一个 bound method（真值），等于「永远需要审批」。
    """
    from aicf.harness.policy.base import PolicyDecision
    decision = PolicyDecision.deny('scope')
    assert decision.needs_approval is False
    assert isinstance(decision.needs_approval, bool)
    assert PolicyDecision.allow().needs_approval is False
    assert PolicyDecision.require_approval().needs_approval is True


def test_policy_rule_matching():
    from aicf.harness.policy.base import PolicyRule
    rule = PolicyRule(action='deny', tool='shell')
    assert rule.matches('shell')
    assert not rule.matches('fs.read')
    prefix = PolicyRule(action='deny', tool='*', tool_prefix='fs.')
    assert prefix.matches('fs.read')
    assert not prefix.matches('shell')
    effect = PolicyRule(action='allow', tool='*', effect='pure')
    assert effect.matches('anything', effect='pure')
    assert not effect.matches('anything', effect='effectful')


# ── Approval ────────────────────────────────────────────
def test_approval_decision_timeout_is_not_approved():
    """超时 = 拒绝（fail-closed）。把 timeout 当成同意是安全事故。"""
    from aicf.harness.approval.base import ApprovalDecision
    assert ApprovalDecision.timeout().approved is False
    assert ApprovalDecision.deny().approved is False
    assert ApprovalDecision.approve().approved is True
    assert ApprovalDecision.approve(scope='session').scope == 'session'


def test_approval_request_serialises():
    from aicf.harness.approval.base import ApprovalRequest
    req = ApprovalRequest(id='r1', tool='shell', scopes_required=('fs.write',))
    data = req.to_dict()
    assert data['id'] == 'r1'
    assert data['scopes_required'] == ['fs.write']


# ── Sandbox ─────────────────────────────────────────────
def test_sandbox_result_reports_degradation():
    """降级必须如实标注 —— 绝不允许「以为自己在沙箱里」。"""
    from aicf.harness.tools.sandbox.base import SandboxResult
    degraded = SandboxResult(exit_code=0, degraded=True, backend='restricted')
    assert degraded.degraded is True
    assert degraded.ok is True
    violated = SandboxResult(exit_code=0, violation='path escape')
    assert violated.ok is False


# ── Telemetry ───────────────────────────────────────────
def test_span_handle_emits_once():
    from aicf.harness.telemetry.base import Span, SpanHandle, new_trace_id

    class Collector:
        def __init__(self):
            self.events = []

        def emit(self, kind, payload):
            self.events.append((kind, payload))

    collector = Collector()
    handle = SpanHandle(collector, Span(trace_id=new_trace_id(), span_id='s'))
    with handle:
        handle.set_attr('model', 'x')
    handle.end()  # 重复结束应当是 no-op
    assert len(collector.events) == 1
    kind, payload = collector.events[0]
    assert kind == 'span_end'
    assert payload['attrs']['model'] == 'x'
    assert payload['end'] is not None


# ── RuntimeClient ───────────────────────────────────────
def test_null_runtime_client_is_a_runtime_client():
    from aicf.harness.runtime_client import NullRuntimeClient, RuntimeClient
    assert isinstance(NullRuntimeClient(), RuntimeClient)


def test_null_runtime_client_does_nothing():
    from aicf.harness.runtime_client import NullRuntimeClient, ToolIntent
    client = NullRuntimeClient()
    assert client.emit('x', {}) is None
    assert client.record_tool_result('k', 'v') is None
    assert client.lookup_tool_result('k') is None
    assert client.checkpoint({}) is None
    assert client.record_tool_intent(
        ToolIntent(session_id='s', turn_seq=0, tool='t', tool_version='1',
                   idempotency_key='k')) is None


# ── 事件词表 v2 ─────────────────────────────────────────
def test_event_vocabulary_added_without_breaking_old_kinds():
    from aicf.harness.agent.events import EVENT_KINDS
    # 既有 kind 必须还在（向后兼容）
    for kind in ('turn_start', 'tool_start', 'tool_end', 'usage', 'turn_end'):
        assert kind in EVENT_KINDS
    # v2 新增
    for kind in ('approval_request', 'approval_decision', 'approval_timeout',
                 'tool_blocked', 'sandbox_degraded', 'tool_intent',
                 'tool_effect_unknown', 'run_started', 'run_finished',
                 'run_failed', 'checkpoint_written', 'session_resumed'):
        assert kind in EVENT_KINDS, kind


def test_contract_dataclasses_are_frozen_where_it_matters():
    """契约对象不可变：策略判定、审批决策被下游改掉会破坏审计可信度。"""
    from aicf.harness.policy.base import PolicyDecision, PolicyRule
    from aicf.harness.approval.base import ApprovalDecision, ApprovalRequest
    from aicf.harness.tools.spec import ToolSpec
    for cls in (PolicyDecision, PolicyRule, ApprovalDecision, ApprovalRequest,
                ToolSpec):
        assert dataclasses.is_dataclass(cls)
        assert cls.__dataclass_params__.frozen, cls.__name__
