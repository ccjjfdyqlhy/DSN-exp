# tests/fault/test_idempotent_delivery.py
# 策划案 §8.2 用例 2：同一 idempotency_key 重复投递 3 次 → 副作用只发生 1 次
#
# 【这条用例证明什么】
#   R7 的验收标准原文：「重复投递同一 tool_call 不产生第二次副作用」。
#   这是 rc0 最高价值项（策划案 §4.2.3）的端到端证明：
#       idempotency_key = sha256(session_id | turn_seq | tool_name | canonical_args)
#   同一个键投递几次，外部世界只该被碰一次。
#
#   三种「重复投递」的真实来源都在这里覆盖：
#     1. 同一个进程里重试（网络超时后重发）；
#     2. 进程重启后重投（崩溃恢复时上游重新投递同一条 tool_call）；
#     3. 从统一入口 ToolGuard 走一遍（真实调用路径，不是直接调 runtime）。
#
#   副作用次数用文件计数断言 —— 跨进程可见，且不依赖任何内存状态。

from __future__ import annotations

import asyncio

import pytest

from aicf.harness.policy.base import PolicyRule
from aicf.harness.tools.base import Tool
from aicf.harness.tools.guard import ToolGuard
from aicf.harness.tools.spec import ToolSpec
from aicf.infra.policy.engine import RulePolicyEngine
from aicf.infra.runtime import (
    EFFECT_EFFECTFUL,
    ManagedRuntime,
    idempotency_key,
)
from aicf.infra.store.sqlite import SqliteStore

from faultkit import ENV_COUNTER, ENV_DB, run_child

#: L4 故障注入层（策划案 §8.1 / §8.2）
pytestmark = pytest.mark.fault


#: 子进程：同一个 tool_call 连投 3 次。
CHILD_TRIPLE_DELIVERY = '''
db = os.environ['FAULT_DB']
counter = os.environ['FAULT_COUNTER']

from aicf.infra.store.sqlite import SqliteStore
from aicf.infra.runtime import ManagedRuntime, SqliteRuntimeStore, migrate_runtime

store = SqliteStore(db)
migrate_runtime(store)
runtime = ManagedRuntime(SqliteRuntimeStore(store), session_id='s1')
runtime.start_session(tenant='t1')
runtime.start_turn(0, input={'q': 'send the mail'})

def send():
    bump(counter, 'send')
    return 'sent'

statuses = []
for _ in range(3):
    outcome = runtime.execute_tool(tool='send_email', args={'to': 'a@b.c'},
                                   fn=send, effect='effectful')
    statuses.append(outcome.status)

print(','.join(statuses))
'''


# ── 2a：同一进程内连投 3 次 ────────────────────────────

def test_same_idempotency_key_delivered_three_times_runs_side_effect_once(
        runtime, counter):
    """期望：状态序列 executed/reused/reused，副作用文件计数 == 1。"""
    def send() -> str:
        counter.bump('send')
        return 'sent'

    outcomes = [
        runtime.execute_tool(tool='send_email', args={'to': 'a@b.c'},
                             fn=send, effect=EFFECT_EFFECTFUL)
        for _ in range(3)
    ]

    assert [o.status for o in outcomes] == ['executed', 'reused', 'reused'], (
        '同一幂等键的第 2、3 次投递必须复用结果，实际状态 '
        f'{[o.status for o in outcomes]}')
    assert len({o.idempotency_key for o in outcomes}) == 1, (
        '三次投递必须算出同一个幂等键')
    assert outcomes[1].result == 'sent', '复用时必须把上次的**结果**带回来'
    assert counter.count('send') == 1, (
        f'期望副作用只发生 1 次，实际 {counter.count("send")} 次')


def test_different_args_produce_different_keys_and_do_run_again(runtime, counter):
    """幂等的粒度是「键」，不是「工具」：参数不同 → 键不同 → 正常再跑一次。

    这是对上一条的**反向**校验：如果实现按工具名去重（而不是按幂等键），
    参数不同的第二次调用会被错误地吞掉 —— 那同样是缺陷。
    """
    def send() -> str:
        counter.bump('send')
        return 'sent'

    first = runtime.execute_tool(tool='send_email', args={'to': 'a@b.c'},
                                 fn=send, effect=EFFECT_EFFECTFUL)
    second = runtime.execute_tool(tool='send_email', args={'to': 'x@y.z'},
                                  fn=send, effect=EFFECT_EFFECTFUL)

    assert first.status == 'executed'
    assert second.status == 'executed', (
        '参数不同的调用不是同一次调用，必须真的执行')
    assert first.idempotency_key != second.idempotency_key
    assert counter.count('send') == 2


# ── 2b：跨进程 —— 子进程连投 3 次 ─────────────────────

def test_triple_delivery_in_a_real_subprocess_runs_side_effect_once(
        tmp_path, db_path, counter):
    """在真子进程里连投 3 次：只有第一次真的执行，后两次复用。

    期望：子进程输出 executed,reused,reused；副作用计数 == 1。
    实际：如果结果缓存只活在内存里，第二次投递就会重复发消息。
    """
    proc = run_child(CHILD_TRIPLE_DELIVERY,
                     env={ENV_DB: db_path, ENV_COUNTER: counter.path})
    assert proc.returncode == 0, proc.stderr.decode('utf-8', 'replace')
    assert proc.stdout.decode('utf-8').strip() == 'executed,reused,reused'
    assert counter.count('send') == 1, (
        f'期望副作用只发生 1 次，实际 {counter.count("send")} 次')


def test_redelivery_after_restart_still_runs_side_effect_once(
        tmp_path, db_path, counter):
    """崩溃重启后上游重投同一条 tool_call → 仍然不产生第二次副作用。

    期望：重启后第一次投递状态为 reused，副作用计数仍然是 1。
    实际：如果结果只存在内存里，重启后缓存全空 → 重复副作用。
    """
    proc = run_child(CHILD_TRIPLE_DELIVERY,
                     env={ENV_DB: db_path, ENV_COUNTER: counter.path})
    assert proc.returncode == 0, proc.stderr.decode('utf-8', 'replace')
    assert counter.count('send') == 1

    # ── 重启：换一个运行时实例（内存里什么都没有）────────
    store = SqliteStore(db_path)
    try:
        from aicf.infra.runtime import SqliteRuntimeStore

        port = SqliteRuntimeStore(store)
        resumed = ManagedRuntime(port, session_id='s1')
        resumed.resume()

        calls: list[int] = []

        outcome = resumed.execute_tool(
            tool='send_email', args={'to': 'a@b.c'},
            fn=lambda: calls.append(1), effect=EFFECT_EFFECTFUL)

        assert outcome.status == 'reused', (
            f'重启后重投必须复用结果，实际状态 {outcome.status}')
        assert calls == [], '重启后重投触发了重复副作用'
        assert counter.count('send') == 1, (
            f'期望副作用仍然只有 1 次，实际 {counter.count("send")} 次')
    finally:
        store.close()


# ── 2c：从统一入口 ToolGuard 走一遍 ──────────────────

def _effectful_tool(counter) -> Tool:
    """一个会真的产生副作用（写文件计数）的 effectful 工具。"""
    def handler(**_kwargs):
        counter.bump('send')
        return 'sent'

    return Tool(
        name='send_email',
        description='send an email',
        handler=handler,
        spec=ToolSpec(name='send_email', effect='effectful', sandbox='none'),
    )


def test_guard_entry_point_delivered_three_times_runs_side_effect_once(
        port, counter):
    """统一入口（ToolGuard）连投 3 次 → 副作用只发生 1 次。

    这是 R7 验收标准最贴近真实调用路径的形态：
    模型重复请求同一个 tool_call，守卫必须自己吞掉后两次。
    """
    runtime = ManagedRuntime(port, session_id='s1')
    runtime.start_session(tenant='t1')
    runtime.start_turn(0)

    guard = ToolGuard(
        policy=RulePolicyEngine(rules=[PolicyRule(action='allow',
                                                   tool='send_email')]),
        runtime=runtime,
        session_id='s1',
        turn_seq=0,
    )
    tool = _effectful_tool(counter)

    results = [asyncio.run(guard.execute(tool, {'to': 'a@b.c'}))
               for _ in range(3)]

    assert [r.reused for r in results] == [False, True, True], (
        '第 2、3 次投递必须被守卫判为复用，实际 '
        f'{[r.reused for r in results]}')
    assert counter.count('send') == 1, (
        f'期望副作用只发生 1 次，实际 {counter.count("send")} 次')

    # 三次用的是同一个幂等键 —— 键相同才谈得上「重复投递」
    key = idempotency_key('s1', 0, 'send_email', {'to': 'a@b.c'})
    assert runtime.lookup_tool_result(key) is not None
