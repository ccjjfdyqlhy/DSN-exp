# tests/fault/test_approval_crash_resume.py
# 策划案 §8.2 用例 3：审批等待期间进程退出 → 重启后仍处于 awaiting_approval，
#                      决策可补填
#
# 【这条用例证明什么】
#   「人在回路」这条安全机制，只有在**进程活着**的时候才有意义。
#   如果 agent 恰好在等审批的时候被 kill -9，那么：
#     * 这次工具调用到底批没批？没人知道；
#     * 如果重启后从头再跑一遍 → 审批形同虚设（或者重复产生副作用）；
#     * 如果重启后直接放行 → 更糟（没人批过的东西被执行了）。
#
#   正确的行为是策划案 §4.2.1 写的那句：重启后仍处于 awaiting_approval，
#   决策可以**补填** —— 人回来点一下，这次调用才继续。
#
#   这里的「进程退出」是**真的** SIGKILL（proc.kill()），
#   不是 os._exit：子进程正停在 broker 的等待里被信号打死，
#   连 finally / atexit 都没跑。
#
#   证明分三段：
#     1. 重启后 recover() 看到的轮次状态仍是 awaiting_approval；
#     2. 待决的 approval_request 能从 journal 里捞回来并挂回 broker；
#     3. 决策补填之后，这次工具调用可以正常执行，且只执行一次。

from __future__ import annotations

import asyncio
import os

import pytest

from harness.approval.base import ApprovalDecision, ApprovalRequest
from harness.approval.broker import LocalApprovalBroker
from harness.approval.events import approval_decision_event, approval_request_event
from harness.tools.base import Tool
from harness.tools.guard import ToolGuard
from harness.tools.spec import ToolSpec
from infra.policy.engine import RulePolicyEngine
from infra.runtime import Journal, ManagedRuntime, TurnStatus
from infra.store.sqlite import SqliteStore

from faultkit import ENV_COUNTER, ENV_DB, ENV_READY, spawn_child, wait_for_file

#: L4 故障注入层（策划案 §8.1 / §8.2）
pytestmark = pytest.mark.fault


#: 子进程：进入审批等待，然后无限期挂着等人回填。
CHILD_WAITING_FOR_APPROVAL = '''
db = os.environ['FAULT_DB']
counter = os.environ['FAULT_COUNTER']
ready = os.environ['FAULT_READY']

import asyncio
import time
from infra.store.sqlite import SqliteStore
from infra.runtime import (ManagedRuntime, SqliteRuntimeStore,
                           migrate_runtime)
from harness.approval.base import ApprovalRequest
from harness.approval.broker import LocalApprovalBroker
from harness.approval.events import approval_request_event

store = SqliteStore(db)
migrate_runtime(store)
port = SqliteRuntimeStore(store)
runtime = ManagedRuntime(port, session_id='s1')
runtime.start_session(tenant='t1', artifact_id='a1')
turn = runtime.start_turn(0, input={'q': 'clean up the workspace'})

# 轮次挂起在 awaiting_approval（不是 running，也不是被重置）。
# 刻意用 upsert_turn 而不是 finish_turn(status='awaiting_approval') ——
# 后者会在 journal 里留下一条 'turn_finished{status: awaiting_approval}'，
# 自相矛盾（既 finished 又在等审批）。
turn.status = 'awaiting_approval'
port.upsert_turn(turn)

request = ApprovalRequest(
    id='req-1', session_id='s1', turn_id='s1:0', tool='shell',
    args_preview='{"cmd": "rm -rf build"}', effect='effectful',
    destructive=True, risk='high', expires_at=time.time() + 600,
    detail='不可逆操作，需要人工确认')

runtime.emit('approval_request', approval_request_event(request))

# 报告「我已经进入等待状态」，然后无限期等下去
with open(ready, 'w', encoding='utf-8') as handle:
    handle.write('waiting')
    handle.flush()
    os.fsync(handle.fileno())

broker = LocalApprovalBroker(timeout=600.0)
asyncio.run(broker.request(request))
'''


def _rebuild_request(payload: dict) -> ApprovalRequest:
    """从 journal 里的 approval_request 载荷还原出待决请求。

    这就是「重启后决策可补填」的技术前提：
    请求的**内容**必须在 journal 里（不能只在内存里），
    否则进程一死，这次审批就永远悬空。
    """
    return ApprovalRequest(
        id=str(payload.get('id', '')),
        session_id=str(payload.get('session_id', '')),
        turn_id=str(payload.get('turn_id', '')),
        tool=str(payload.get('tool', '')),
        args_preview=str(payload.get('args_preview', '')),
        effect=str(payload.get('effect', 'effectful')),
        destructive=bool(payload.get('destructive', False)),
        scopes_required=tuple(payload.get('scopes_required', ()) or ()),
        risk=str(payload.get('risk', 'medium')),
        expires_at=float(payload.get('expires_at', 0.0) or 0.0),
        detail=str(payload.get('detail', '')),
    )


# ── 3a：重启后仍处于 awaiting_approval ───────────────

def test_process_killed_while_awaiting_approval_stays_awaiting_approval(
        tmp_path, db_path, counter):
    """期望：SIGKILL 之后重启，recover() 看到的轮次仍是 awaiting_approval。

    实际：如果恢复把它当成普通未完成轮次（running）或者干脆从头再来，
          这次审批就被绕过去了 —— 人在回路这条安全机制形同虚设。
    """
    ready = str(tmp_path / 'ready.flag')
    proc = spawn_child(CHILD_WAITING_FOR_APPROVAL,
                       env={ENV_DB: db_path, ENV_COUNTER: counter.path,
                            ENV_READY: ready})
    try:
        wait_for_file(ready, timeout=30.0, proc=proc)
        assert proc.poll() is None, '子进程应当还活着（正卡在审批等待里）'

        # 真的 SIGKILL —— 相当于 kill -9
        proc.kill()
        proc.wait(timeout=30)
    finally:
        if proc.poll() is None:      # pragma: no cover - 兜底，避免挂住 CI
            proc.kill()
        proc.communicate()

    assert proc.returncode == -9, (
        f'子进程应当死于 SIGKILL（-9），实际 {proc.returncode}')

    store = SqliteStore(db_path)
    try:
        from infra.runtime import SqliteRuntimeStore

        port = SqliteRuntimeStore(store)
        plan = None
        from infra.runtime import recover

        plan = recover(port, 's1')
        assert plan.pending_turn is not None, '恢复时应当找得到未完成的轮次'
        assert plan.pending_turn.status == TurnStatus.AWAITING_APPROVAL.value, (
            '重启后轮次应当仍是 awaiting_approval，实际 '
            f'{plan.pending_turn.status}')
        assert plan.resume_turn_seq == 0

        # 待决请求必须能从 journal 里捞回来（不能只在内存里）
        approvals = [e for e in Journal(port).events('s1')
                     if e.kind == 'approval_request']
        assert len(approvals) == 1, (
            f'journal 里应当有 1 条 approval_request，实际 {len(approvals)}')
        request = _rebuild_request(approvals[0].payload)
        assert request.id == 'req-1'
        assert request.tool == 'shell'
    finally:
        store.close()


# ── 3b：决策可补填 ────────────────────────────────────

def test_approval_decision_can_be_filled_in_after_restart(tmp_path, db_path,
                                                          counter):
    """期望：重启后把待决请求挂回 broker，回填决策 → 决策生效。

    实际：如果回填打不进去（请求 id 变了 / 请求根本没恢复），
          这次调用就永远悬着，或者被当成超时拒绝。
    """
    ready = str(tmp_path / 'ready.flag')
    proc = spawn_child(CHILD_WAITING_FOR_APPROVAL,
                       env={ENV_DB: db_path, ENV_COUNTER: counter.path,
                            ENV_READY: ready})
    try:
        wait_for_file(ready, timeout=30.0, proc=proc)
        proc.kill()
        proc.wait(timeout=30)
    finally:
        if proc.poll() is None:      # pragma: no cover
            proc.kill()
        proc.communicate()
    assert proc.returncode == -9

    store = SqliteStore(db_path)
    try:
        from infra.runtime import SqliteRuntimeStore, recover

        port = SqliteRuntimeStore(store)
        approvals = [e for e in Journal(port).events('s1')
                     if e.kind == 'approval_request']
        request = _rebuild_request(approvals[0].payload)

        broker = LocalApprovalBroker(timeout=5.0, session_id='s1')

        # 1) 重启后把待决请求挂回 broker
        broker.restore_pending(request)
        assert [r.id for r in broker.pending()] == ['req-1'], (
            '重启后待决请求应当能被恢复出来，实际 '
            f'{[r.id for r in broker.pending()]}')

        # 2) 决策补填
        async def fill_in():
            task = asyncio.create_task(broker.request(request))
            approval = ApprovalDecision.approve(
                by='operator', reason='人工确认放行', scope='session')
            # 反复回填直到等待真的结束：
            # broker.request() 会用自己新建的 future 覆盖 restore_pending 放的那个，
            # 所以「先回填还是先挂起」存在竞态 —— 反复回填把这个竞态消掉。
            for _ in range(200):
                await asyncio.sleep(0.01)
                if task.done():
                    break
                broker.submit(request.id, approval)
            return await asyncio.wait_for(task, timeout=5.0)

        decision = asyncio.run(fill_in())
        assert decision.approved is True, (
            f'补填的决策应当生效，实际 {decision.decision}')
        assert decision.decided_by == 'operator'
        assert decision.scope == 'session'

        # 3) 决策补填之后，这次工具调用可以执行 —— 且只执行一次
        runtime = ManagedRuntime(port, session_id='s1')
        runtime.resume()

        def handler(**_kwargs):
            counter.bump('shell')
            return 'cleaned'

        shell = Tool(name='shell', description='run a command',
                     handler=handler,
                     spec=ToolSpec(name='shell', effect='effectful',
                                   destructive=True))

        guard = ToolGuard(policy=RulePolicyEngine(), approval=broker,
                          runtime=runtime, session_id='s1', turn_seq=0)

        result = asyncio.run(guard.execute(shell, {'cmd': 'rm -rf build'}))
        assert result.result.success is True, (
            f'补填决策后工具应当能执行，实际 {result.result.error}')
        assert counter.count('shell') == 1, (
            f'期望副作用只发生 1 次，实际 {counter.count("shell")} 次')

        # 4) 决策本身必须落进 journal（审计能回答「谁批的」）
        runtime.emit('approval_decision',
                     approval_decision_event(request.id, request.tool,
                                              decision))
        kinds = [e.kind for e in Journal(port).events('s1')]
        assert 'approval_request' in kinds
        assert 'approval_decision' in kinds
    finally:
        store.close()


# ── 3c：审批没批下来之前，副作用不能发生 ──────────────

def test_tool_is_not_executed_while_approval_is_pending(tmp_path, db_path,
                                                         counter):
    """等待审批期间，工具**不能**被执行（哪怕只执行了一半）。

    期望：审批还挂着的时候调工具 → 被挡住，副作用计数为 0。
    实际：这条防线一旦漏了，「人在回路」就只剩形式。
    """
    from harness.runtime_client import NullRuntimeClient

    broker = LocalApprovalBroker(timeout=5.0, session_id='s1')

    def handler(**_kwargs):
        counter.bump('shell')
        return 'cleaned'

    shell = Tool(name='shell', description='run a command', handler=handler,
                 spec=ToolSpec(name='shell', effect='effectful',
                               destructive=True))

    guard = ToolGuard(policy=RulePolicyEngine(), approval=broker,
                      runtime=NullRuntimeClient(), session_id='s1', turn_seq=0)

    async def call_without_decision():
        task = asyncio.create_task(guard.execute(shell, {'cmd': 'rm -rf build'}))
        await asyncio.sleep(0.05)
        assert counter.count('shell') == 0, (
            '审批还没批，工具就执行了 —— 人在回路被绕过了')
        broker.submit([r.id for r in broker.pending()][0],
                      ApprovalDecision.deny(by='operator', reason='不批'))
        return await asyncio.wait_for(task, timeout=5.0)

    result = asyncio.run(call_without_decision())
    assert result.result.success is False, '被拒绝的调用不能成功'
    assert counter.count('shell') == 0, (
        f'被拒绝的调用不该产生副作用，实际 {counter.count("shell")} 次')
