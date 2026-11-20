# tests/test_rc1_audit_wiring.py
# 不可删审计接线的测试 —— 策划案 §4.4.7 / roadmap 诚实清单第一条。
#
# 验收标准：守卫发出的 audit.* 事件不仅进 trace（会被轮转），
# 还落进**独立且不可删**的 AuditStore；SDK / CLI 两条默认路径都接上了。

from __future__ import annotations

import asyncio

import pytest

from aicf.harness.policy.base import PolicyDecision
from aicf.harness.tools.base import Tool, ToolResult
from aicf.harness.tools.guard import ToolGuard
from aicf.harness.tools.registry import ManagedToolRegistry
from aicf.infra.observability.audit import AuditImmutableError, AuditLog


def echo_tool():
    return Tool(name='demo.echo', description='',
                handler=lambda **kw: ToolResult.ok({'echo': kw}))


class Allow:
    def admit(self, tool, args=None, spec=None, identity=None):
        return PolicyDecision.allow(risk='low')


class Deny:
    def admit(self, tool, args=None, spec=None, identity=None):
        return PolicyDecision.deny('policy', detail='nope')


def _registry(guard):
    registry = ManagedToolRegistry()
    registry.register(echo_tool())
    registry.attach_guard(guard)
    return registry


def test_denied_call_lands_in_the_immutable_store():
    """策略拒绝 → audit.denied 落独立存储（trace 面之外的另一份）。"""
    audit = AuditLog()
    registry = _registry(ToolGuard(policy=Deny(), audit=audit))
    result = asyncio.run(registry.execute_async('demo.echo', {}))
    assert result.success is False
    records = audit.of_kind('audit.denied')
    assert len(records) == 1
    payload = dict(records[0].payload)
    assert payload['tool'] == 'demo.echo'
    assert payload['reason'] == 'policy'
    # 审计记录带 trace 上下文字段，能回答「属于哪次运行」
    assert records[0].seq >= 1
    assert records[0].ts > 0


def test_successful_call_lands_in_the_immutable_store():
    audit = AuditLog()
    registry = _registry(ToolGuard(policy=Allow(), audit=audit))
    result = asyncio.run(registry.execute_async('demo.echo', {'a': 1}))
    assert result.success is True
    record = audit.of_kind('audit.tool_call')[-1]
    payload = dict(record.payload)
    assert payload['tool'] == 'demo.echo'
    assert payload['outcome'] == 'ok'
    assert payload['decision'] == 'auto'
    # args 只有摘要，没有明文（§4.4.7 args_digest）
    assert '"a":' not in json_dumps(payload)   # 参数明文不进审计
    assert str(payload['args_digest']).startswith('sha256:')


def json_dumps(value):
    import json
    return json.dumps(value, ensure_ascii=False, default=str)


def test_audit_store_refuses_deletion():
    """「审计可被业务删除 = 没有审计」（AuditLog.clear 的既定语义）。"""
    audit = AuditLog()
    registry = _registry(ToolGuard(policy=Allow(), audit=audit))
    asyncio.run(registry.execute_async('demo.echo', {}))
    assert len(audit) >= 1
    with pytest.raises(AuditImmutableError):
        audit.clear()
    # 没有 audit 参数时不报错 —— 纯 SDK 最小用法保持可用
    registry2 = _registry(ToolGuard(policy=Allow()))
    assert asyncio.run(registry2.execute_async('demo.echo', {})).success


def test_audit_backend_failure_does_not_break_the_call():
    """审计存储故障不阻断调用（trace 面的审计仍在 —— 同流兜底）。"""

    class BrokenAudit:
        def record(self, kind, payload):
            raise RuntimeError('disk full')

    registry = _registry(ToolGuard(policy=Allow(), audit=BrokenAudit()))
    result = asyncio.run(registry.execute_async('demo.echo', {}))
    assert result.success is True     # 调用没有被审计可用性劫持


def test_audit_records_survive_a_trace_export_round_trip():
    """同流但独立：trace 导出与审计导出的内容一致（同一 payload）。"""
    import json
    import tempfile

    class Collector:
        def __init__(self):
            self.events = []

        def emit(self, kind, payload):
            self.events.append({'kind': kind, 'payload': dict(payload or {})})

    collector = Collector()
    audit = AuditLog()
    registry = _registry(ToolGuard(policy=Allow(), telemetry=collector,
                                   audit=audit))
    asyncio.run(registry.execute_async('demo.echo', {'k': 'v'}))
    trace_audit = [e for e in collector.events if e['kind'] == 'audit.tool_call']
    assert trace_audit, 'trace 面有审计'
    store_audit = audit.of_kind('audit.tool_call')
    assert store_audit, '独立存储面有审计'
    # 同一条调用，两边字段一致
    assert trace_audit[0]['payload']['tool'] == \
        dict(store_audit[0].payload)['tool']

    # 审计可以独立导出成 JSONL（与业务 trace 分开存放，§4.4.7）
    with tempfile.TemporaryDirectory() as tmp:
        path = f'{tmp}/audit.jsonl'
        count = audit.export(path)
        assert count >= 1
        with open(path, encoding='utf-8') as handle:
            lines = [json.loads(line) for line in handle if line.strip()]
        assert lines[0]['type'] == 'audit'


def test_sdk_default_path_attaches_an_audit_log():
    """SDK 装配路径默认带不可删审计（assembler 的接线）。"""

    from aicf.harness.agent.assembler import AgentAssembler, AgentSpec

    class DummyClient:
        model = 'dummy'

        def invoke(self, messages, tools=None, **kwargs):
            from aicf.infra.orchestrator.base import ChatResponse
            return ChatResponse(content='ok')

        def stream(self, messages, tools=None, **kwargs):
            raise NotImplementedError

    spec = AgentSpec(name='sdk-audit-check', system_prompt='test',
                     tools=[lambda **kw: 'ok'])
    assembled = AgentAssembler(DummyClient()).assemble(spec)
    runtime = assembled.runtime
    audit_log = runtime.get('audit_log')
    assert audit_log is not None
    guard = runtime.get('guard')
    assert guard.audit is audit_log
    # 守卫真的把 audit 写进了独立存储
    asyncio.run(guard.execute(echo_tool(), {}))
    assert len(audit_log) >= 1
    # 显式关掉也是合法配置（security_audit=False）
    spec2 = AgentSpec(name='no-audit', system_prompt='test',
                      tools=[lambda **kw: 'ok'], security_audit=False)
    assembled2 = AgentAssembler(DummyClient()).assemble(spec2)
    assert assembled2.runtime.get('audit_log') is None


def test_toolguard_accepts_any_object_with_record():
    """鸭子类型契约：audit 参数只要会 record(kind, payload) 就能用。"""

    class MinimalAudit:
        def __init__(self):
            self.seen = []

        def record(self, kind, payload):
            self.seen.append((kind, payload))

    audit = MinimalAudit()
    registry = _registry(ToolGuard(policy=Allow(), audit=audit))
    asyncio.run(registry.execute_async('demo.echo', {}))
    assert audit.seen and audit.seen[0][0] == 'audit.tool_call'
