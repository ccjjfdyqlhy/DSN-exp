# tests/fault/test_checkpoint_corruption.py
# 策划案 §8.2 用例 7：checkpoint 损坏 → 从 journal 重放恢复
#
# 【这条用例证明什么】
#   策划案 §4.2.2 的心智模型：
#       Event Journal (只追加)  ← 事实的唯一真相来源
#               │  周期性
#               ▼
#       Checkpoint (快照, 可丢弃) ← 加速恢复，不是真相来源
#
#   「可丢弃」这三个字是承诺：**快照坏了，恢复不能失败**。
#   checkpoint 存在的唯一理由是加速；它坏了，正确行为是退化成
#   「纯 journal 重放」，而不是把异常一路冒给用户。
#
#   两种损坏都要覆盖：
#     1. blob 不是合法 JSON（写了一半 / 被截断 / 磁盘写坏）；
#     2. blob 是合法 JSON 但不是对象（被写成了数组 / 字符串）——
#        这一种更隐蔽：JSON 解析器不报错，但快照已经没意义了。
#
#   恢复之后还要证明：**工具结果没丢**（journal 里还在）、
#   **工具不重复执行**（幂等缓存被 journal 回灌）。

from __future__ import annotations

import pytest

from infra.runtime import (
    EFFECT_PURE,
    CheckpointCorruptError,
    CheckpointStore,
    Journal,
    ManagedRuntime,
    recover,
)

#: L4 故障注入层（策划案 §8.1 / §8.2）
pytestmark = pytest.mark.fault


#: 两种损坏方式
CORRUPTIONS = {
    'invalid_json': '{oops',                 # 写了一半 / 被截断
    'not_an_object': '[1, 2, 3]',            # 合法 JSON，但不是快照
}


def _corrupt(port, blob: str) -> None:
    """把最新的检查点 blob 改坏（模拟磁盘损坏 / 半写）。"""
    conn = port._store.get_connection()
    conn.execute('UPDATE runtime_checkpoint SET blob_json = ?'
                 " WHERE session_id = 's1'", (blob,))
    conn.commit()


@pytest.fixture()
def prepared(runtime, port):
    """一段「已经跑过一段、并且打过检查点」的会话。"""
    runtime.execute_tool(tool='calc', fn=lambda: 42, args={'x': 1},
                         effect=EFFECT_PURE)
    runtime.emit('custom', {'n': 1})
    runtime.checkpoint({'state': {'step': 1}})
    runtime.emit('custom', {'n': 2})
    return runtime


# ── 7a：损坏被显式识别出来 ────────────────────────────

@pytest.mark.parametrize('blob', list(CORRUPTIONS.values()),
                         ids=list(CORRUPTIONS))
def test_corrupt_checkpoint_raises_explicit_error(prepared, port, blob):
    """损坏的快照必须**显式**报出来，而不是被悄悄吞成空字典。

    期望：CheckpointStore.latest() 抛 CheckpointCorruptError。
    实际：如果损坏被吞成「空快照」，恢复会从一个空状态继续 ——
          已经完成的工具调用会被当成「没做过」→ 重复副作用。
    """
    _corrupt(port, blob)
    with pytest.raises(CheckpointCorruptError) as excinfo:
        CheckpointStore(port).latest('s1')
    assert excinfo.value.session_id == 's1'
    assert excinfo.value.turn_seq == 0


# ── 7b：恢复退化成纯 journal 重放 ────────────────────

@pytest.mark.parametrize('blob', list(CORRUPTIONS.values()),
                         ids=list(CORRUPTIONS))
def test_recovery_falls_back_to_journal_replay_when_checkpoint_corrupt(
        prepared, port, blob):
    """期望：恢复成功，checkpoint_corrupt=True，快照被丢弃，journal 全量重放。

    实际：如果恢复因为快照坏了就失败 —— 那等于「快照丢了 = 任务丢了」，
          §4.2.2 的「可丢弃」承诺就成了空话。
    """
    _corrupt(port, blob)

    plan = recover(port, 's1')
    assert plan.checkpoint_corrupt is True, '损坏必须被标记出来'
    assert plan.checkpoint is None, '损坏的快照不能被采用'

    # 全量重放：损坏的快照不能用，所以从 seq 0 开始
    all_events = Journal(port).events('s1')
    assert len(plan.events) == len(all_events), (
        f'损坏时应当全量重放 journal：期望 {len(all_events)} 条，'
        f'实际 {len(plan.events)} 条')
    assert [e.payload.get('n') for e in plan.events
            if e.kind == 'custom'] == [1, 2], (
        '损坏时检查点之前的事件也必须被重放出来')


@pytest.mark.parametrize('blob', list(CORRUPTIONS.values()),
                         ids=list(CORRUPTIONS))
def test_tool_results_survive_a_corrupt_checkpoint(prepared, port, blob):
    """快照坏了，但工具结果还在 journal 里 —— 恢复不能因此重复执行工具。

    期望：恢复后重投 calc → reused，handler 不再被调用。
    实际：如果结果只在快照里，恢复后会重新执行一次纯工具 ——
          纯工具重放不致命，但它证明「真相只在快照里」这个错误心智模型。
    """
    _corrupt(port, blob)

    resumed = ManagedRuntime(port, session_id='s1')
    plan = resumed.resume()
    assert plan.checkpoint_corrupt is True

    key = resumed.idempotency_key('s1', 0, 'calc', {'x': 1})
    assert resumed.lookup_tool_result(key) == 42, (
        '工具结果必须从 journal 回灌进幂等缓存')

    calls: list[int] = []
    outcome = resumed.execute_tool(tool='calc', fn=lambda: calls.append(1),
                                   args={'x': 1}, effect=EFFECT_PURE)
    assert outcome.status == 'reused', (
        f'期望复用结果，实际状态 {outcome.status}')
    assert calls == [], 'pure 工具被重复执行了'


# ── 7c：恢复事件里要留下「快照损坏」的痕迹 ────────────

def test_resume_event_records_checkpoint_corruption(prepared, port):
    """恢复事件必须带上 checkpoint_corrupt —— 降级要可见，不能静默。

    策划案 §3.3.5「降级而非降智」：降级了就要说，不能假装一切正常。
    """
    _corrupt(port, '{oops')

    resumed = ManagedRuntime(port, session_id='s1')
    resumed.resume()

    events = Journal(port).events('s1')
    resumed_events = [e for e in events if e.kind == 'session_resumed']
    assert len(resumed_events) == 1
    assert resumed_events[0].payload.get('checkpoint_corrupt') is True, (
        'session_resumed 事件必须标明快照损坏，实际 '
        f'{resumed_events[0].payload}')


# ── 7d：压根没有检查点 —— 同一件事的退化形态 ──────────

def test_recovery_without_any_checkpoint_replays_the_whole_journal(runtime,
                                                                    port):
    """没有检查点（还没来得及打 / 已被清理）也必须能恢复。

    期望：全量重放 journal，工具结果照样在，恢复照常成功。
    """
    runtime.execute_tool(tool='calc', fn=lambda: 42, args={'x': 1},
                         effect=EFFECT_PURE)
    runtime.emit('custom', {'n': 1})

    plan = recover(port, 's1')
    assert plan.checkpoint is None
    assert plan.checkpoint_corrupt is False
    assert len(plan.events) == len(Journal(port).events('s1'))

    resumed = ManagedRuntime(port, session_id='s1')
    resumed.resume()
    key = resumed.idempotency_key('s1', 0, 'calc', {'x': 1})
    assert resumed.lookup_tool_result(key) == 42
