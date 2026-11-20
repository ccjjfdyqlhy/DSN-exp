# tests/fault/test_crash_recovery.py
# 策划案 §8.2 用例 1：工具执行中途 kill -9 → 重启 → 恢复
#     → `pure` 工具不重复、`effectful` 标记 `unknown_outcome`
#
# 【这条用例证明什么】
#   这是 rc0 完成定义（DoD）第一条的可执行证明：
#       「一个 agent 在被 kill -9 一次的情况下仍能恢复并给出正确结果」
#
#   证明方式不是「跑一遍不崩」，而是**真的杀掉一个进程**：
#     1. 子进程里跑一次会话：
#          - pure 工具 calc 正常完成（intent + result 都落 journal）；
#          - effectful 工具 pay 的副作用**已经发生**，
#            进程在「写 result 之前」被硬杀（os._exit(9)，不走 finally/atexit）；
#     2. 父进程重新打开同一个数据库，走完整恢复流程；
#     3. 重新投递两次调用：
#          - calc（pure，已完成）→ 必须**复用结果**，fn 不能再被调用；
#          - pay（effectful，副作用已发生但结果未知）→ 必须标 unknown_outcome，
#            **绝不能**自动重放（重复扣款）。
#
#   副作用次数用文件计数（跨进程可见）断言，不是内存计数。
#
# 【为什么必须用真子进程】
#   同一进程里模拟崩溃没法验证「内存状态全丢」这件事：
#   任何还在内存里的东西都会让恢复显得比实际更聪明。
#   真正的 kill -9 之后，唯一剩下的东西是磁盘上的 journal。

from __future__ import annotations

import pytest

from aicf.infra.runtime import (
    EFFECT_EFFECTFUL,
    EFFECT_PURE,
    Journal,
    ManagedRuntime,
    recover,
)
from aicf.infra.store.sqlite import SqliteStore

from faultkit import ENV_COUNTER, ENV_DB, run_child

#: L4 故障注入层（策划案 §8.1 / §8.2）
pytestmark = pytest.mark.fault


# ── 子进程脚本 ────────────────────────────────────────

#: pure 工具跑完 + effectful 工具副作用发生后被硬杀。
CHILD_CRASH_IN_EFFECTFUL = '''
db = os.environ['FAULT_DB']
counter = os.environ['FAULT_COUNTER']

from aicf.infra.store.sqlite import SqliteStore
from aicf.infra.runtime import ManagedRuntime, SqliteRuntimeStore, migrate_runtime

store = SqliteStore(db)
migrate_runtime(store)
runtime = ManagedRuntime(SqliteRuntimeStore(store), session_id='s1')
runtime.start_session(tenant='t1', artifact_id='a1')
runtime.start_turn(0, input={'q': 'pay the bill'})

# 1) pure 工具：正常完成 —— intent 与 result 都落 journal
def calc():
    bump(counter, 'calc')
    return 42

runtime.execute_tool(tool='calc', fn=calc, args={'x': 1}, effect='pure')

# 2) effectful 工具：副作用**已经发生**，进程在写 result 之前被 kill -9
def pay():
    bump(counter, 'pay')      # 钱已经扣了 / 消息已经发出去了
    os._exit(9)               # 模拟工具执行中途被 kill -9

runtime.execute_tool(tool='pay', fn=pay, args={'amount': 100},
                     effect='effectful')
'''

#: pure 工具执行到一半被硬杀 —— 这次调用没有结果（intent 有、result 没有）。
CHILD_CRASH_IN_PURE = '''
db = os.environ['FAULT_DB']
counter = os.environ['FAULT_COUNTER']

from aicf.infra.store.sqlite import SqliteStore
from aicf.infra.runtime import ManagedRuntime, SqliteRuntimeStore, migrate_runtime

store = SqliteStore(db)
migrate_runtime(store)
runtime = ManagedRuntime(SqliteRuntimeStore(store), session_id='s1')
runtime.start_session(tenant='t1', artifact_id='a1')
runtime.start_turn(0, input={'q': 'search'})

def search():
    bump(counter, 'search')
    os._exit(9)               # pure 工具执行中途被 kill -9

runtime.execute_tool(tool='search', fn=search, args={'q': 'x'},
                     effect='pure')
'''


# ── 用例 1a：effectful 中途被杀 → unknown_outcome ────

def test_kill9_during_effectful_tool_blocks_automatic_replay(tmp_path, db_path,
                                                              counter):
    """effectful 工具执行中途 kill -9 → 重启后必须标 unknown_outcome，绝不重放。

    期望：pay 的副作用只发生 1 次（文件计数），恢复后重投得到 unknown_outcome，
          pay 的 fn 一次都没有被再次调用。
    实际：若实现擅自重放，文件计数会变成 2 —— 那就是重复扣款。
    """
    proc = run_child(CHILD_CRASH_IN_EFFECTFUL,
                     env={ENV_DB: db_path, ENV_COUNTER: counter.path})
    assert proc.returncode == 9, (
        '子进程应当以 9 退出（模拟 kill -9），实际 '
        f'{proc.returncode}\n{proc.stderr.decode("utf-8", "replace")}')

    # 副作用确实发生过一次（不是「压根没跑」，也不是「跑了两次」）
    assert counter.count('pay') == 1, (
        f'期望 pay 的副作用发生 1 次，实际 {counter.count("pay")} 次')
    assert counter.count('calc') == 1

    # ── 重启：重新打开同一个库，走完整恢复流程 ────────
    store = SqliteStore(db_path)
    try:
        from aicf.infra.runtime import SqliteRuntimeStore

        port = SqliteRuntimeStore(store)

        plan = recover(port, 's1')
        assert [item.tool for item in plan.unknown_outcomes] == ['pay'], (
            '恢复方案里应当只有 pay 是结果未知的 effectful 调用，'
            f'实际 {[item.tool for item in plan.unknown_outcomes]}')
        assert plan.unknown_outcomes[0].effect == EFFECT_EFFECTFUL
        assert plan.unknown_outcomes[0].idempotency_key, '未知结果必须带幂等键'
        assert plan.replayable == [], 'effectful 调用绝不能被标成「可重放」'

        resumed = ManagedRuntime(port, session_id='s1')
        resumed.resume()
        assert resumed.turn_seq == 0, '应当续跑崩溃时那个未完成的轮次'

        pending = resumed.pending_effectful_calls()
        assert [item.tool for item in pending] == ['pay']

        # ── 重新投递 pure 调用：必须复用结果，不能再执行 ──
        calc_calls: list[int] = []

        calc_outcome = resumed.execute_tool(
            tool='calc', fn=lambda: calc_calls.append(1),
            args={'x': 1}, effect=EFFECT_PURE)

        assert calc_outcome.status == 'reused', (
            f'pure 工具应当被复用，实际状态 {calc_outcome.status}')
        assert calc_outcome.result == 42
        assert calc_calls == [], 'pure 工具的 handler 被重复执行了'

        # ── 重新投递 effectful 调用：必须拒绝自动重放 ──
        pay_calls: list[int] = []

        pay_outcome = resumed.execute_tool(
            tool='pay', fn=lambda: pay_calls.append(1),
            args={'amount': 100}, effect=EFFECT_EFFECTFUL)

        assert pay_outcome.status == 'unknown_outcome', (
            '结果未知的 effectful 调用必须返回 unknown_outcome，实际 '
            f'{pay_outcome.status}')
        assert pay_outcome.unknown is not None
        assert pay_outcome.unknown.tool == 'pay'
        assert pay_calls == [], '结果未知的 effectful 调用被自动重放了（重复副作用）'

        # ── 落到文件上的最终事实：副作用只发生了一次 ──
        assert counter.count('pay') == 1, (
            f'期望副作用只发生 1 次，实际 {counter.count("pay")} 次')
        assert counter.count('calc') == 1, (
            f'期望 pure 工具只执行 1 次，实际 {counter.count("calc")} 次')

        # ── 审计线索：journal 里必须有 unknown_outcome 事件 ──
        kinds = [event.kind for event in Journal(port).events('s1')]
        assert 'tool_effect_unknown' in kinds, (
            f'journal 里应当留下 tool_effect_unknown，实际 {kinds}')
    finally:
        store.close()


def test_kill9_leaves_only_intent_for_the_crashed_effectful_call(tmp_path,
                                                                  db_path,
                                                                  counter):
    """崩溃窗口的精确形状：intent 写了、result 没写。

    这是 §4.2.3「先写 intent → 执行 → 写 result」的顺序铁律的直接验证：
    如果顺序反了（先执行后写 intent），崩溃窗口里这次调用在 journal 里
    **根本不存在**，恢复会把它当成「从没发生过」→ 重复执行 → 重复扣款。
    """
    proc = run_child(CHILD_CRASH_IN_EFFECTFUL,
                     env={ENV_DB: db_path, ENV_COUNTER: counter.path})
    assert proc.returncode == 9

    store = SqliteStore(db_path)
    try:
        from aicf.infra.runtime import SqliteRuntimeStore

        port = SqliteRuntimeStore(store)
        events = Journal(port).events('s1')
        tool_events = [e for e in events
                       if e.kind in ('tool_intent', 'tool_result')]

        intents = [e for e in tool_events if e.kind == 'tool_intent']
        results = [e for e in tool_events if e.kind == 'tool_result']

        assert len(intents) == 2, f'期望 2 条 intent，实际 {len(intents)}'
        assert len(results) == 1, (
            f'期望 1 条 result（calc 那次写完了，pay 那次没写完），'
            f'实际 {len(results)}')

        pay_intents = [e for e in intents
                       if e.payload.get('tool') == 'pay']
        assert len(pay_intents) == 1
        assert pay_intents[0].payload['effect'] == EFFECT_EFFECTFUL
        # effectful 的参数原文不进 journal（用不上，还可能含敏感值）
        assert 'args' not in pay_intents[0].payload
    finally:
        store.close()


# ── 用例 1b：pure 中途被杀 → 可重放（不是 unknown） ────

def test_kill9_during_pure_tool_is_replayable_not_unknown(tmp_path, db_path,
                                                           counter):
    """pure 工具执行中途 kill -9 → 恢复后它属于「可重放」，**不是**结果未知。

    期望：plan.replayable 里有 search，plan.unknown_outcomes 为空；
          重新投递 search 时允许真的再跑一次（pure 允许自由重放）。
    实际：如果 pure 也被标成 unknown_outcome，安全是够了但可用性没了 ——
          一个纯计算工具被卡住等人确认，这本身就是缺陷。
    """
    proc = run_child(CHILD_CRASH_IN_PURE,
                     env={ENV_DB: db_path, ENV_COUNTER: counter.path})
    assert proc.returncode == 9
    assert counter.count('search') == 1

    store = SqliteStore(db_path)
    try:
        from aicf.infra.runtime import SqliteRuntimeStore

        port = SqliteRuntimeStore(store)
        plan = recover(port, 's1')

        assert plan.unknown_outcomes == [], (
            'pure 工具不该被标成结果未知，实际 '
            f'{[u.tool for u in plan.unknown_outcomes]}')
        assert [item.tool for item in plan.replayable] == ['search'], (
            '被中断的 pure 调用应当出现在可重放列表里，实际 '
            f'{[item.tool for item in plan.replayable]}')

        resumed = ManagedRuntime(port, session_id='s1')
        resumed.resume()

        search_calls: list[int] = []

        def search():
            search_calls.append(1)
            return 'found'

        outcome = resumed.execute_tool(tool='search', fn=search,
                                       args={'q': 'x'}, effect=EFFECT_PURE)
        assert outcome.status == 'executed', (
            'pure 工具被中断后应当允许重放，实际状态 ' f'{outcome.status}')
        assert search_calls == [1]

        # 重放是**允许**的（pure 幂等无害），但结果必须落进 journal，
        # 这样下一次恢复就不会再重放了。
        events = Journal(port).events('s1')
        results = [e for e in events
                   if e.kind == 'tool_result'
                   and e.payload.get('tool') == 'search']
        assert len(results) == 1
    finally:
        store.close()


# ── 1c：上层入口（守卫）也必须挡住那次未知结果的调用 ──

def test_guard_refuses_to_replay_the_crashed_effectful_call(tmp_path, db_path,
                                                             counter):
    """DoD 级别的验证：重启后统一入口（ToolGuard）不会重放那次调用。

    期望：守卫调用 pay → 明确失败并说明「上一次调用结果未知」，
          工具**没有**被执行，副作用计数仍然是 1。
    实际：守卫是工具调用的唯一入口（策划案 §3.2 依赖规则 5）。
          如果守卫这一层没接住运行时抛出的 UnknownOutcomeError，
          那么「运行时知道结果未知」这件事在实际调用路径上毫无意义 ——
          这正是 UnknownOutcomeError 要在**执行前那道门**上抛的原因。
    """
    import asyncio

    from aicf.harness.policy.base import PolicyRule
    from aicf.harness.tools.base import Tool
    from aicf.harness.tools.guard import ToolGuard
    from aicf.harness.tools.spec import ToolSpec
    from aicf.infra.policy.engine import RulePolicyEngine

    proc = run_child(CHILD_CRASH_IN_EFFECTFUL,
                     env={ENV_DB: db_path, ENV_COUNTER: counter.path})
    assert proc.returncode == 9
    assert counter.count('pay') == 1

    store = SqliteStore(db_path)
    try:
        from aicf.infra.runtime import SqliteRuntimeStore

        port = SqliteRuntimeStore(store)
        resumed = ManagedRuntime(port, session_id='s1')
        resumed.resume()

        def handler(**_kwargs):
            counter.bump('pay')
            return 'paid'

        pay_tool = Tool(name='pay', description='pay the bill',
                        handler=handler,
                        spec=ToolSpec(name='pay', effect='effectful'))

        guard = ToolGuard(
            policy=RulePolicyEngine(rules=[PolicyRule(action='allow',
                                                       tool='pay')]),
            runtime=resumed,
            session_id='s1',
            turn_seq=0,
        )

        result = asyncio.run(guard.execute(pay_tool, {'amount': 100}))

        assert result.result.success is False, (
            '结果未知的调用不能被静默放行')
        assert '结果未知' in (result.result.error or ''), (
            '失败原因必须说清是「上一次调用结果未知」，实际 '
            f'{result.result.error}')
        assert counter.count('pay') == 1, (
            f'守卫放行了重复副作用：计数变成 {counter.count("pay")}')
    finally:
        store.close()
