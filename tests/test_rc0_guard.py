# tests/test_rc0_guard.py
# R1：ToolSpec + 准入策略 + 统一入口。
#
# 这些用例是策划案 §7.1 R1 的验收标准：
#   - 未声明 sandbox 的工具默认按最严格档
#   - 越权调用被拒并记审计
#   - 工具调用必须经过统一入口（审批 / 策略 / 幂等都挂在这条路径上）

from __future__ import annotations

import asyncio

import pytest

from aicf.harness.approval.base import ApprovalDecision, ApprovalRequest
from aicf.harness.policy.base import PolicyRule
from aicf.harness.runtime_client import NullRuntimeClient
from aicf.harness.tools.base import Tool, ToolRegistry
from aicf.harness.tools.guard import ToolGuard, args_digest
from aicf.harness.tools.registry import ManagedToolRegistry
from aicf.harness.tools.spec import ToolSpec
from aicf.infra.auth.base import Identity
from aicf.infra.policy.engine import RulePolicyEngine, compute_risk


# ── 夹具 ────────────────────────────────────────────────
class Collector:
    """收集遥测事件。"""

    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def emit(self, kind, payload):
        self.events.append((kind, payload))

    def kinds(self) -> list[str]:
        return [k for k, _ in self.events]

    def of(self, kind: str) -> list[dict]:
        return [p for k, p in self.events if k == kind]


class FakeApproval:
    """可编排的审批代理。"""

    def __init__(self, decision: ApprovalDecision | None = None,
                 *, delay: float = 0.0):
        self.decision = decision or ApprovalDecision.approve(by='tester')
        self.delay = delay
        self.requests: list[ApprovalRequest] = []

    async def request(self, req: ApprovalRequest) -> ApprovalDecision:
        self.requests.append(req)
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.decision


class CountingTool(Tool):
    """记录被调用了几次的工具。"""

    def __init__(self, name='counter', **kwargs):
        # handler 接受任意 kwargs —— 工具被调用时参数是关键字传入的。
        super().__init__(name=name, description='counts',
                         handler=lambda **_: 1, **kwargs)
        self.calls = 0

    def run(self, **params):
        self.calls += 1
        return super().run(**params)

    async def run_async(self, **params):
        self.calls += 1
        return await super().run_async(**params)


def make_registry(tool: Tool) -> ManagedToolRegistry:
    registry = ManagedToolRegistry()
    registry.register(tool)
    return registry


# ── 策略引擎 ────────────────────────────────────────────
def test_unknown_tool_is_denied_by_default():
    """默认拒绝：没有放行规则的 effectful 工具必须走审批。"""
    engine = RulePolicyEngine()
    decision = engine.admit('mail.send', spec=ToolSpec(name='mail.send'))
    assert decision.allowed is False
    assert decision.needs_approval is True


def test_pure_tools_are_auto_allowed():
    engine = RulePolicyEngine()
    decision = engine.admit('fs.read', spec=ToolSpec.read_only_default('fs.read'))
    assert decision.allowed is True
    assert decision.needs_approval is False


def test_deny_rule_beats_allow_rule():
    """显式 deny 永远赢 —— 哪怕后面有 allow 规则。"""
    engine = RulePolicyEngine(rules=[
        PolicyRule(action='allow', tool='shell', id='allow-shell'),
        PolicyRule(action='deny', tool='shell', id='deny-shell'),
    ])
    decision = engine.admit('shell', spec=ToolSpec(name='shell'))
    assert decision.allowed is False
    assert decision.reason == 'policy'
    assert decision.rule_id == 'deny-shell'


def test_scope_violation_is_denied():
    """越权调用被拒，且理由分类是 scope（审计要能分组）。"""
    engine = RulePolicyEngine()
    identity = Identity(uid='u1', scopes=['fs.read'])
    spec = ToolSpec(name='fs.write', scopes=('fs.write',),
                    effect='idempotent')
    decision = engine.admit('fs.write', spec=spec, identity=identity)
    assert decision.allowed is False
    assert decision.reason == 'scope'
    assert 'fs.write' in decision.detail


def test_risk_escalates_with_destructive_and_network():
    assert compute_risk(ToolSpec(name='x', effect='pure')) == 'low'
    assert compute_risk(ToolSpec(name='x', effect='idempotent')) == 'medium'
    assert compute_risk(ToolSpec(name='x', effect='effectful')) == 'high'
    assert compute_risk(ToolSpec(name='x', effect='pure', destructive=True)) == 'high'
    assert compute_risk(ToolSpec(name='x', effect='pure', network='full')) == 'medium'


def test_policy_failure_fails_closed():
    """策略引擎自己抛异常时必须按拒绝处理，不能当成放行。"""

    class Boom:
        def admit(self, *args, **kwargs):
            raise RuntimeError('策略服务挂了')

    guard = ToolGuard(policy=Boom())
    spec = ToolSpec.read_only_default('fs.read')
    decision = guard._admit(Tool(name='fs.read', description='', handler=lambda: 1),
                            {}, spec)
    assert decision.allowed is False


# ── 守卫：审批链路 ──────────────────────────────────────
def test_effectful_tool_waits_for_approval():
    approval = FakeApproval(ApprovalDecision.approve(by='alice'))
    collector = Collector()
    tool = CountingTool(name='mail.send',
                        spec=ToolSpec(name='mail.send', effect='effectful'))
    guard = ToolGuard(policy=RulePolicyEngine(), approval=approval,
                      telemetry=collector)
    result = asyncio.run(guard.execute(tool, {'to': 'x'}))
    assert result.result.success is True
    assert tool.calls == 1
    assert len(approval.requests) == 1
    assert approval.requests[0].tool == 'mail.send'
    assert 'approval_request' in collector.kinds()
    assert 'approval_decision' in collector.kinds()


def test_denied_approval_blocks_the_tool():
    """审批拒绝 → 工具绝不执行。"""
    approval = FakeApproval(ApprovalDecision.deny(by='bob', reason='不批准'))
    tool = CountingTool(name='mail.send',
                        spec=ToolSpec(name='mail.send', effect='effectful'))
    guard = ToolGuard(policy=RulePolicyEngine(), approval=approval)
    result = asyncio.run(guard.execute(tool, {}))
    assert result.result.success is False
    assert tool.calls == 0
    assert 'mail.send' in result.result.error


def test_approval_timeout_is_treated_as_denial():
    """超时 = 拒绝（fail-closed）。"""
    approval = FakeApproval(ApprovalDecision.timeout())
    tool = CountingTool(name='mail.send',
                        spec=ToolSpec(name='mail.send', effect='effectful'))
    guard = ToolGuard(policy=RulePolicyEngine(), approval=approval)
    result = asyncio.run(guard.execute(tool, {}))
    assert result.result.success is False
    assert tool.calls == 0


def test_missing_approval_broker_denies_by_default():
    """没有审批代理时不能默认放行。"""
    tool = CountingTool(name='mail.send',
                        spec=ToolSpec(name='mail.send', effect='effectful'))
    guard = ToolGuard(policy=RulePolicyEngine(), approval=None)
    result = asyncio.run(guard.execute(tool, {}))
    assert result.result.success is False
    assert tool.calls == 0


def test_blocked_call_emits_tool_blocked_event():
    collector = Collector()
    engine = RulePolicyEngine(rules=[PolicyRule(action='deny', tool='shell',
                                                 id='no-shell')])
    tool = CountingTool(name='shell', spec=ToolSpec(name='shell'))
    guard = ToolGuard(policy=engine, telemetry=collector)
    asyncio.run(guard.execute(tool, {}))
    blocked = collector.of('tool_blocked')
    assert len(blocked) == 1
    assert blocked[0]['reason'] == 'policy'
    assert blocked[0]['tool'] == 'shell'


# ── 统一入口 ────────────────────────────────────────────
def test_registry_routes_through_the_guard():
    """挂上 guard 后，注册表的执行路径必须经过策略。"""
    registry = make_registry(CountingTool(name='shell',
                                          spec=ToolSpec(name='shell')))
    engine = RulePolicyEngine(rules=[PolicyRule(action='deny', tool='shell',
                                                 id='no-shell')])
    registry.attach_guard(ToolGuard(policy=engine))
    text, _diff, error = registry.execute('shell', {})
    assert error is True
    assert 'shell' in text


def test_registry_without_guard_still_works():
    """没挂 guard 的既有用法不能坏 —— 这是向后兼容的底线。"""
    registry = make_registry(Tool(name='add', description='d',
                                   handler=lambda a, b: a + b))
    text, _diff, error = registry.execute('add', {'a': 1, 'b': 2})
    assert error is False
    assert text == '3'


def test_agent_loop_uses_the_registry_entry_point():
    """AgentLoop 必须走注册表入口，否则 guard 形同虚设。"""
    from aicf.harness.agent.loop import AgentLoop

    registry = make_registry(CountingTool(name='shell',
                                          spec=ToolSpec(name='shell')))
    engine = RulePolicyEngine(rules=[PolicyRule(action='deny', tool='shell',
                                                 id='no-shell')])
    registry.attach_guard(ToolGuard(policy=engine))
    loop = AgentLoop(client=None, tools=registry)
    tool = registry.require('shell')
    result = asyncio.run(loop._run_tool(tool, {}))
    assert result.success is False
    assert tool.calls == 0


def test_guard_is_skipped_in_legacy_mode():
    tool = CountingTool(name='mail.send',
                        spec=ToolSpec(name='mail.send', effect='effectful'))
    guard = ToolGuard(policy=RulePolicyEngine(), mode='legacy')
    result = asyncio.run(guard.execute(tool, {}))
    assert result.result.success is True
    assert tool.calls == 1


# ── 未声明 = 最严格 ─────────────────────────────────────
def test_tool_without_spec_is_treated_as_strictest():
    """忘写声明不等于静默放开权限。"""
    tool = Tool(name='mystery', description='d', handler=lambda: 1)
    guard = ToolGuard(policy=RulePolicyEngine())
    spec = guard.spec_for(tool)
    assert spec.effect == 'effectful'
    assert spec.sandbox == 'isolated'
    assert spec.requires_approval is True


def test_read_only_tool_gets_narrow_spec():
    from aicf.harness.tools.registry import AnnotatedTool
    tool = AnnotatedTool(name='fs.read', description='d',
                         handler=lambda: 'x', read_only=True)
    guard = ToolGuard(policy=RulePolicyEngine())
    spec = guard.spec_for(tool)
    assert spec.effect == 'pure'
    assert spec.sandbox == 'readonly'


# ── 幂等 ────────────────────────────────────────────────
def test_idempotent_tool_is_not_executed_twice():
    """同一幂等键重复投递 → 副作用只发生一次。"""
    from aicf.harness.runtime_client import ToolIntent

    class Cache(NullRuntimeClient):
        def __init__(self):
            super().__init__()
            self.results: dict[str, object] = {}

        def record_tool_result(self, key, result, *, effect='pure'):
            self.results[key] = result

        def lookup_tool_result(self, key):
            return self.results.get(key)

    cache = Cache()
    tool = CountingTool(name='counter', spec=ToolSpec.read_only_default('counter'))
    guard = ToolGuard(policy=RulePolicyEngine(), runtime=cache)

    first = asyncio.run(guard.execute(tool, {'x': 1}))
    second = asyncio.run(guard.execute(tool, {'x': 1}))
    assert first.result.success and second.result.success
    assert tool.calls == 1, '第二次应该命中幂等缓存'
    assert second.reused is True


# ── 脱敏 ────────────────────────────────────────────────
def test_args_digest_does_not_leak_plaintext():
    digest = args_digest({'cmd': 'rm -rf /', 'token': 'sk-secret-value'})
    assert 'sk-secret-value' not in digest
    assert 'rm -rf /' not in digest
    assert digest.startswith('sha256:')


def test_preview_truncates_and_hides_nothing_but_length():
    from aicf.harness.tools.guard import preview_args
    text = preview_args({'a': 'x' * 1000})
    assert len(text) < 500
    assert '…' in text


# ── 注册表契约 ──────────────────────────────────────────
def test_base_registry_execute_async_runs_the_tool():
    registry = ToolRegistry()
    registry.register(Tool(name='add', description='d',
                           handler=lambda a, b: a + b))
    result = asyncio.run(registry.execute_async('add', {'a': 2, 'b': 3}))
    assert result.success is True
    assert result.output == 5


# ── 结果未知：不能绕过托管运行时的门 ───────────────────
def test_guard_does_not_execute_when_the_outcome_is_unknown():
    """崩溃恢复后重放一次 effectful 调用 —— 绝不能真的执行。

    这是 R7 的核心断言：guard 自己实现了「查缓存 → 写 intent → 执行 →
    写结果」，如果它不理会托管运行时在**执行前**抛出的
    UnknownOutcomeError，就等于给「重复扣款」开了后门。
    """
    from aicf.harness.runtime_client import UnknownOutcomeError

    class RefusingRuntime(NullRuntimeClient):
        def record_tool_intent(self, intent):
            raise UnknownOutcomeError(
                '上一次调用的结果未知', tool=intent.tool,
                idempotency_key=intent.idempotency_key,
                effect=intent.effect)

    collector = Collector()
    tool = CountingTool(name='mail.send',
                        spec=ToolSpec(name='mail.send', effect='effectful'))
    guard = ToolGuard(policy=RulePolicyEngine(),
                      approval=FakeApproval(ApprovalDecision.approve()),
                      runtime=RefusingRuntime(), telemetry=collector)

    result = asyncio.run(guard.execute(tool, {'to': 'x'}))
    assert tool.calls == 0, '结果未知时绝不能执行工具'
    assert result.result.success is False
    assert '未知' in result.result.error
    assert 'tool_effect_unknown' in collector.kinds()


def test_guard_treats_a_runtime_write_failure_as_a_denial():
    """写意图失败（不是「结果未知」）也要 fail closed。"""

    class BrokenRuntime(NullRuntimeClient):
        def record_tool_intent(self, intent):
            raise RuntimeError('存储挂了')

    tool = CountingTool(name='mail.send',
                        spec=ToolSpec(name='mail.send', effect='effectful'))
    guard = ToolGuard(policy=RulePolicyEngine(),
                      approval=FakeApproval(ApprovalDecision.approve()),
                      runtime=BrokenRuntime())
    result = asyncio.run(guard.execute(tool, {'to': 'x'}))
    assert tool.calls == 0
    assert result.result.success is False


def test_unknown_outcome_marker_is_recognised_across_layers():
    """infra 侧的异常靠标记属性被 harness 认出（infra 不能 import aicf.harness）。"""
    from aicf.harness.runtime_client import UnknownOutcomeError
    assert getattr(UnknownOutcomeError('x'), 'unknown_outcome', False) is True
    try:
        from aicf.infra.runtime.managed import UnknownOutcomeError as InfraError
    except Exception:  # pragma: no cover - runtime 包可能还没就位
        return
    assert getattr(InfraError.__new__(InfraError), 'unknown_outcome', False) is True


# ── 审计：被拒绝的调用要留下痕迹 ───────────────────────
def test_policy_denial_emits_an_audit_denied_event():
    """审计事件词表里有 audit.denied，之前一直没人发 —— 现在策略拒绝要发。"""
    collector = Collector()
    engine = RulePolicyEngine(rules=[PolicyRule(action='deny', tool='shell',
                                                 id='no-shell')])
    tool = CountingTool(name='shell', spec=ToolSpec(name='shell'))
    guard = ToolGuard(policy=engine, telemetry=collector)
    asyncio.run(guard.execute(tool, {}))
    denied = collector.of('audit.denied')
    assert len(denied) == 1
    assert denied[0]['reason'] == 'policy'
    assert denied[0]['tool'] == 'shell'


def test_scope_denial_is_audited_with_the_scope_reason():
    from aicf.infra.auth.base import Identity
    collector = Collector()
    identity = Identity(uid='u1', scopes=['fs.read'])
    spec = ToolSpec(name='fs.write', scopes=('fs.write',), effect='idempotent')
    tool = CountingTool(name='fs.write', spec=spec)
    guard = ToolGuard(policy=RulePolicyEngine(), identity=identity,
                      telemetry=collector)
    asyncio.run(guard.execute(tool, {}))
    denied = collector.of('audit.denied')
    assert len(denied) == 1
    assert denied[0]['reason'] == 'scope'
    assert denied[0]['identity'] == 'u1'


def test_approval_denial_is_audited():
    collector = Collector()
    broker = FakeApproval(ApprovalDecision.deny(by='bob'))
    tool = CountingTool(name='mail.send',
                        spec=ToolSpec(name='mail.send', effect='effectful'))
    guard = ToolGuard(policy=RulePolicyEngine(), approval=broker,
                      telemetry=collector)
    asyncio.run(guard.execute(tool, {}))
    denied = collector.of('audit.denied')
    assert len(denied) == 1
    assert denied[0]['reason'] == 'approval'


def test_sandbox_violation_is_audited_and_the_tool_still_runs():
    """沙箱拒绝：违规要进审计，工具仍返回可读结果给模型。"""
    collector = Collector()

    class DenyingTool(Tool):
        def __init__(self):
            super().__init__(name='proc.run', description='d',
                             handler=lambda **_: 'x',
                             spec=ToolSpec(name='proc.run', effect='effectful'))

        async def run_async(self, **params):
            from aicf.harness.tools.context import current_context
            context = current_context()
            violations = getattr(context, 'violations', None)
            if violations is not None:
                violations.append({'code': 'path:escape', 'detail': '../etc/passwd',
                                   'kind': 'sandbox', 'degraded': True})
            return ToolResult.fail('Error: 沙箱拒绝执行（path:escape）')

    tool = DenyingTool()
    guard = ToolGuard(policy=RulePolicyEngine(),
                      approval=FakeApproval(ApprovalDecision.approve()),
                      telemetry=collector)
    result = asyncio.run(guard.execute(tool, {}))
    assert result.result.success is False
    denied = collector.of('audit.denied')
    assert len(denied) == 1
    assert denied[0]['reason'] == 'sandbox'
    assert denied[0]['violation'] == 'path:escape'
    blocked = collector.of('tool_blocked')
    assert blocked and blocked[0]['reason'] == 'sandbox'
