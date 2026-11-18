# tests/test_rc0_approval.py
# R2：审批链路。
#
# 策划案 §7.1 R2 的验收标准：
#   - shell 类工具调用必须等待审批
#   - 超时 = 拒绝
#   - approval_decision 进 trace
#
# 以及 §8.2 用例 3：审批等待期间进程退出，重启后仍处于 awaiting_approval。

from __future__ import annotations

import asyncio

import pytest

from harness.approval.base import ApprovalDecision, ApprovalRequest
from harness.approval.broker import AutoDenyBroker, LocalApprovalBroker
from harness.approval.events import (
    approval_decision_event,
    approval_request_event,
    approval_timeout_event,
)
from harness.approval.session import ApprovalCache
from harness.policy.base import PolicyRule
from harness.tools.base import Tool
from harness.tools.guard import ToolGuard
from harness.tools.spec import ToolSpec
from infra.policy.engine import RulePolicyEngine


class Collector:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def emit(self, kind, payload):
        self.events.append((kind, payload))

    def kinds(self) -> list[str]:
        return [k for k, _ in self.events]

    def of(self, kind: str) -> list[dict]:
        return [p for k, p in self.events if k == kind]


def shell_tool() -> Tool:
    return Tool(name='shell', description='run a command',
                handler=lambda **_: 'ok',
                spec=ToolSpec(name='shell', effect='effectful'))


# ── 缓存作用域 ──────────────────────────────────────────
def test_cache_scope_once_is_not_remembered():
    cache = ApprovalCache()
    cache.remember('shell', session_id='s1', scope='once')
    assert cache.is_allowed('shell', session_id='s1') is False


def test_cache_scope_session_only_applies_to_that_session():
    cache = ApprovalCache()
    cache.remember('shell', session_id='s1', scope='session')
    assert cache.is_allowed('shell', session_id='s1') is True
    assert cache.is_allowed('shell', session_id='s2') is False


def test_cache_scope_always_crosses_sessions():
    cache = ApprovalCache()
    cache.remember('shell', scope='always')
    assert cache.is_allowed('shell', session_id='s1') is True
    assert cache.is_allowed('shell', session_id='s2') is True


def test_cache_unknown_scope_is_not_remembered():
    """未知作用域不能被当成「永久放行」。"""
    cache = ApprovalCache()
    cache.remember('shell', session_id='s1', scope='随便什么')
    assert cache.is_allowed('shell', session_id='s1') is False


# ── broker：三种等待形态 ────────────────────────────────
def test_broker_with_resolver_returns_the_decision():
    broker = LocalApprovalBroker(
        resolver=lambda req: ApprovalDecision.approve(by='alice'))
    decision = asyncio.run(broker.request(ApprovalRequest(id='1', tool='shell')))
    assert decision.approved is True
    assert decision.decided_by == 'alice'


def test_broker_timeout_is_denial():
    broker = LocalApprovalBroker(timeout=0.05)
    decision = asyncio.run(broker.request(ApprovalRequest(id='1', tool='shell')))
    assert decision.decision == 'timeout'
    assert decision.approved is False


def test_broker_async_submit_path():
    """异步回填：另一个协程 submit 决策。"""
    broker = LocalApprovalBroker(timeout=5.0)

    async def main():
        task = asyncio.create_task(
            broker.request(ApprovalRequest(id='42', tool='shell')))
        await asyncio.sleep(0.01)
        assert broker.submit('42', ApprovalDecision.approve(by='bob'))
        return await task

    decision = asyncio.run(main())
    assert decision.approved is True
    assert decision.decided_by == 'bob'


def test_broker_submit_for_unknown_id_is_false():
    broker = LocalApprovalBroker()
    assert broker.submit('nope', ApprovalDecision.approve()) is False


def test_auto_deny_broker_denies_everything():
    broker = AutoDenyBroker()
    decision = asyncio.run(broker.request(ApprovalRequest(id='1', tool='shell')))
    assert decision.approved is False
    assert decision.decided_by == 'auto-deny'


def test_broker_remembers_session_scope_after_approval():
    """approve + scope=session → 同会话内不再询问。"""
    calls: list[str] = []

    def resolver(req):
        calls.append(req.id)
        return ApprovalDecision.approve(by='alice', scope='session')

    broker = LocalApprovalBroker(resolver=resolver, session_id='s1')
    asyncio.run(broker.request(ApprovalRequest(id='1', tool='shell',
                                               session_id='s1')))
    asyncio.run(broker.request(ApprovalRequest(id='2', tool='shell',
                                               session_id='s1')))
    assert len(calls) == 1, '第二次应命中缓存'


# ── 挂起与恢复 ──────────────────────────────────────────
def test_pending_requests_survive_and_can_be_resumed():
    """审批等待期间进程退出 → 重启后仍能补填决策。"""
    broker = LocalApprovalBroker(timeout=5.0)

    async def main():
        task = asyncio.create_task(
            broker.request(ApprovalRequest(id='99', tool='shell')))
        await asyncio.sleep(0.01)
        pending = broker.pending()
        assert [p.id for p in pending] == ['99']

        # 模拟进程退出：把待决请求导出，重启后恢复
        exported = pending[0]
        fresh = LocalApprovalBroker(timeout=5.0)
        fresh.restore_pending(exported)

        restored = asyncio.create_task(fresh.request(exported))
        await asyncio.sleep(0.01)
        assert fresh.submit('99', ApprovalDecision.approve(by='carol'))
        result = await restored
        assert result.approved is True
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(main())


# ── 端到端：守卫 + 审批 ─────────────────────────────────
def test_shell_tool_waits_for_approval_end_to_end():
    """shell 类工具调用必须等待审批；决策进 trace。"""
    collector = Collector()
    broker = LocalApprovalBroker(
        resolver=lambda req: ApprovalDecision.approve(by='alice'))
    guard = ToolGuard(policy=RulePolicyEngine(), approval=broker,
                      telemetry=collector)
    result = asyncio.run(guard.execute(shell_tool(), {'cmd': 'ls'}))
    assert result.result.success is True
    assert 'approval_request' in collector.kinds()
    assert 'approval_decision' in collector.kinds()


def test_timeout_emits_its_own_event():
    """超时是独立事件，不能混进 deny 里 —— 复盘时「没人理」和「被拒绝」不同。"""
    collector = Collector()
    broker = LocalApprovalBroker(timeout=0.05)
    guard = ToolGuard(policy=RulePolicyEngine(), approval=broker,
                      telemetry=collector)
    result = asyncio.run(guard.execute(shell_tool(), {'cmd': 'ls'}))
    assert result.result.success is False
    assert 'approval_timeout' in collector.kinds()


def test_audit_denial_is_recorded():
    """被拒绝的调用要留下审计痕迹。"""
    collector = Collector()
    broker = LocalApprovalBroker(
        resolver=lambda req: ApprovalDecision.deny(by='bob', reason='不批'))
    guard = ToolGuard(policy=RulePolicyEngine(), approval=broker,
                      telemetry=collector)
    asyncio.run(guard.execute(shell_tool(), {'cmd': 'ls'}))
    assert 'tool_blocked' in collector.kinds()


def test_deny_rule_short_circuits_before_approval():
    """显式 deny 规则命中时根本不该走到审批。"""
    collector = Collector()
    asked: list[str] = []

    def resolver(req):
        asked.append(req.id)
        return ApprovalDecision.approve()

    broker = LocalApprovalBroker(resolver=resolver)
    engine = RulePolicyEngine(rules=[PolicyRule(action='deny', tool='shell')])
    guard = ToolGuard(policy=engine, approval=broker, telemetry=collector)
    result = asyncio.run(guard.execute(shell_tool(), {}))
    assert result.result.success is False
    assert asked == [], '策略拒绝后不应再问人'


# ── 事件载荷形状 ────────────────────────────────────────
def test_event_payload_shapes():
    req = ApprovalRequest(id='r1', tool='shell', args_preview='ls',
                          effect='effectful', risk='high')
    payload = approval_request_event(req)
    assert payload['id'] == 'r1'
    assert payload['tool'] == 'shell'
    assert payload['risk'] == 'high'

    decision = ApprovalDecision.approve(by='alice', scope='session')
    payload = approval_decision_event('r1', 'shell', decision)
    assert payload['decision'] == 'approve'
    assert payload['scope'] == 'session'

    payload = approval_timeout_event('r1', 'shell')
    assert payload == {'id': 'r1', 'tool': 'shell'}
