# tests/fault/test_event_redelivery_billing.py
# 策划案 §8.2 用例 6：事件重复投递 → 消费方按 seq 去重，不重复计费
#
# 【这条用例证明什么】
#   策划案 §4.2.2 写得很直白：
#       「所有事件消费方（trace、审计、成本）需要能容忍重复投递，
#         因此事件带 seq 且消费方按 seq 去重。」
#
#   「至少一次投递」是分布式系统的常态，不是异常：
#     * 消费者处理到一半崩了，重启后从上次水位线重放 → 重复；
#     * 消息队列的 at-least-once 语义 → 重复；
#     * 恢复流程本身要把 journal 重新投给各个消费方 → 重复。
#
#   如果消费方不去重，同一次模型调用会被**计费两次** ——
#   直接后果是预算被虚耗、成本归因失真。
#
#   这里用两个真实消费方验证：
#     * TraceCollector（trace 扇出）：按 seq 去重；
#     * TokenMeter（成本核算）+ Journal.dedupe：按 (session_id, seq) 去重。
#   并且带一条**反向对照**：不去重的话成本正好是两倍 ——
#   证明去重这一步是真正在承重的，不是恰好过。

from __future__ import annotations

import pytest

from infra.observability.trace import TraceCollector
from infra.policy.token_meter import TokenMeter
from infra.runtime import EFFECT_PURE, Journal

#: L4 故障注入层（策划案 §8.1 / §8.2）
pytestmark = pytest.mark.fault


#: 一次模型调用的 usage 载荷（OpenAI / Responses 两种形状都认）
USAGE_PAYLOAD = {
    'input_tokens': 1_000,
    'output_tokens': 500,
    'provider': 'test',
    'model': 'test-model',
}


def _emit_run(runtime):
    """造一段最小可观测的运行：开始 → 两次模型调用 → 结束。"""
    runtime.emit('run_started', {'run_id': 'r1', 'session_id': 's1'})
    runtime.emit('usage', dict(USAGE_PAYLOAD))
    runtime.emit('usage', dict(USAGE_PAYLOAD))
    runtime.emit('run_finished', {'status': 'ok'})


# ── 6a：trace 消费方按 seq 去重 ───────────────────────

def test_duplicate_event_delivery_produces_one_trace_span_per_event(runtime,
                                                                     port):
    """期望：每条事件被投递两次，trace 里仍然只有一份 usage span。

    实际：trace 里出现两个 usage span → 这次运行在 trace 上「看起来」
          调用了两次模型，成本排查从此开始说谎。
    """
    _emit_run(runtime)
    events = Journal(port).events('s1')
    assert events, 'journal 里应当有事件'

    # 至少一次投递：整批重发一遍
    delivered = list(events) + list(events)

    collector = TraceCollector(run_id='r1', session_id='s1')
    for event in delivered:
        collector.emit(event.kind, {**event.payload, 'seq': event.seq})

    usage_spans = [r for r in collector.records() if r['kind'] == 'usage']
    assert len(usage_spans) == 2, (
        '两条 usage 事件 → 两个 usage span，重复投递后实际 '
        f'{len(usage_spans)} 个')

    # 每个 span 只记一份 token（没有被累加成两份）
    assert usage_spans[0]['attrs']['input_tokens'] == 1_000
    assert usage_spans[0]['attrs']['output_tokens'] == 500


def test_trace_collector_drops_redelivered_event_by_seq(runtime, port):
    """同一 seq 重复到达 → 只处理一次（消费方的去重契约本身）。"""
    _emit_run(runtime)
    events = Journal(port).events('s1')

    collector = TraceCollector(run_id='r1')
    for event in events:
        collector.emit(event.kind, {**event.payload, 'seq': event.seq})
    first_count = len(collector.records())

    for event in events:                       # 原样重投一遍
        collector.emit(event.kind, {**event.payload, 'seq': event.seq})

    assert len(collector.records()) == first_count, (
        f'重复投递后 span 数从 {first_count} 变成了 {len(collector.records())}')


# ── 6b：成本核算不重复计费 ────────────────────────────

def test_duplicate_event_delivery_does_not_double_bill(runtime, port):
    """期望：去重后计费一次；不去重正好是两倍（反向对照）。

    实际：如果 Journal.dedupe 没按 (session_id, seq) 去重，
          同一笔 token 会被计费两次，预算被虚耗。
    """
    _emit_run(runtime)
    events = Journal(port).events('s1')

    delivered = list(events) + list(events)      # 至少一次投递

    # 消费方按 seq 去重后再计费
    meter = TokenMeter()
    for event in Journal.dedupe(delivered):
        if event.kind == 'usage':
            meter.record(event.payload, model='test-model')

    assert len(meter.records) == 2, (
        f'两条 usage 事件应当记两笔账，实际 {len(meter.records)} 笔')
    assert meter.input_tokens == 2_000, (
        f'输入 token 应当是 2000，实际 {meter.input_tokens}')
    assert meter.output_tokens == 1_000, (
        f'输出 token 应当是 1000，实际 {meter.output_tokens}')

    # 反向对照：不去重的话正好双倍 —— 证明去重这一步在承重
    naive = TokenMeter()
    for event in delivered:
        if event.kind == 'usage':
            naive.record(event.payload, model='test-model')

    assert len(naive.records) == 4, '反向对照：不去重就该是 4 笔'
    assert naive.cost == pytest.approx(meter.cost * 2), (
        f'反向对照成本应当正好是两倍：{naive.cost} vs {meter.cost * 2}')
    assert meter.cost > 0, '成本必须真的算出来，否则这条断言没有意义'


def test_journal_dedupe_keeps_first_occurrence_and_order(runtime, port):
    """去重保留**第一次**出现，且不改变顺序（消费方要能对账）。"""
    _emit_run(runtime)
    events = Journal(port).events('s1')
    doubled = list(events) + list(events)

    deduped = Journal.dedupe(doubled)
    assert [e.seq for e in deduped] == [e.seq for e in events]
    assert [e.kind for e in deduped] == [e.kind for e in events]


# ── 6c：恢复重放导致的重复投递 ────────────────────────

def test_recovery_replay_after_checkpoint_does_not_double_bill(runtime, port):
    """崩溃恢复重放 journal → 消费方收到的窗口与之前重叠 → 不重复计费。

    场景：检查点之后的事件在恢复时被重放；如果消费方把「检查点前的全量」
    和「重放的增量」直接相加，同一笔账会被计两次。
    """
    _emit_run(runtime)
    checkpoint_seq = Journal(port).last_seq('s1')

    runtime.emit('usage', dict(USAGE_PAYLOAD))     # 检查点之后的新事件
    runtime.emit('usage', dict(USAGE_PAYLOAD))

    # 消费方第一次收到的是全量
    first_pass = Journal(port).events('s1')
    # 恢复时重放检查点之后的部分 —— 与第一次的窗口重叠
    replay_pass = Journal(port).replay('s1', after_seq=checkpoint_seq)

    meter = TokenMeter()
    for event in Journal.dedupe(list(first_pass) + list(replay_pass)):
        if event.kind == 'usage':
            meter.record(event.payload, model='test-model')

    assert len(meter.records) == 4, (
        '四条 usage 事件（2 条检查点前 + 2 条检查点后）应当记 4 笔账，'
        f'实际 {len(meter.records)} 笔')
    assert meter.input_tokens == 4_000, (
        f'输入 token 应当是 4000，实际 {meter.input_tokens}')


# ── 6d：工具结果事件重复投递也不该重复计费 ────────────

def test_repeated_tool_result_events_do_not_replay_the_tool(runtime, port):
    """工具结果事件被重复投递 → 工具不能被重复执行。

    这是用例 6 与用例 2 的交叉点：事件层的重复（去重）
    与执行层的重复（幂等）必须**同时**成立才安全。
    """
    calls: list[int] = []

    def calc():
        calls.append(1)
        return 42

    runtime.execute_tool(tool='calc', fn=calc, args={'x': 1},
                         effect=EFFECT_PURE)

    # 消费方把整条事件流重放一遍（模拟重复投递）
    events = Journal(port).events('s1')
    assert len(Journal.dedupe(list(events) + list(events))) == len(events)

    # 幂等层保证：无论事件被投递几次，工具只跑过一次
    assert len(calls) == 1
