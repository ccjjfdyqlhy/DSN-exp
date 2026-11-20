# tests/test_rc1_eval_loop.py
# 线上抽样（infra/eval/sampling.py）与 Bad Case 回流（infra/eval/badcase.py）
# 的测试 —— 策划案 §4.6.6 / rc2 P2。
#
# 验收标准：抽样重放可复现；失败样本自动进入回归集（hard_cases 分组）。

from __future__ import annotations

import pytest

from infra.eval import (
    HARD_CASE_GROUP,
    EvalCase,
    ReplayQueue,
    SessionSampler,
    TraceStore,
)
from infra.eval.badcase import (
    STATUS_DISMISSED,
    STATUS_LABELLED,
    STATUS_NEW,
    STATUS_QUEUED,
    BadCaseIntake,
)


# ── 线上抽样 ─────────────────────────────────────────────
def test_sampler_ratio_bounds():
    with pytest.raises(ValueError):
        SessionSampler(ratio=1.5)
    with pytest.raises(ValueError):
        SessionSampler(ratio=-0.1)


def test_sampler_is_deterministic_and_stable():
    """同一 salt 重跑结果一致 —— 「这批为什么被抽中」要能事后回答。"""
    ids = [f'session-{i}' for i in range(200)]
    s1 = SessionSampler(ratio=0.1, salt='run-a')
    s2 = SessionSampler(ratio=0.1, salt='run-a')
    assert s1.pick(ids) == s2.pick(ids)
    # 比例大致兑现（200 条抽 10% → 允许 ±8 条的散列噪声）
    assert 10 <= len(s1.pick(ids)) <= 20


def test_sampler_salt_changes_the_selection():
    ids = [f'session-{i}' for i in range(200)]
    a = SessionSampler(ratio=0.1, salt='a').pick(ids)
    b = SessionSampler(ratio=0.1, salt='b').pick(ids)
    assert a != b


def test_sampler_decision_is_auditable():
    d = SessionSampler(ratio=0.5, salt='s').decide('sess-1')
    payload = d.to_dict()
    assert payload['session_id'] == 'sess-1'
    assert payload['ratio'] == 0.5
    assert payload['sampled'] == (payload['bucket'] < 0.5)


def test_sampler_edge_ratios():
    all_in = SessionSampler(ratio=1.0, salt='s')
    none = SessionSampler(ratio=0.0, salt='s')
    assert len(all_in.pick(['a', 'b'])) == 2
    assert none.pick(['a', 'b']) == []


# ── 重放队列 ─────────────────────────────────────────────
def test_replay_queue_lifecycle():
    queue = ReplayQueue()
    queue.enqueue('s1', trace_id='t1', reason='sampling')
    queue.enqueue('s2')
    queue.enqueue('s1')     # 同 session 幂等
    assert len(queue) == 2
    items = queue.drain()
    assert [it.session_id for it in items] == ['s1', 's2']
    assert all(it.status == 'replaying' for it in items)
    assert queue.pending() == []
    queue.mark_done('s1')
    queue.mark_done('s2', skipped=True)
    assert queue.pending() == []


# ── Bad Case 回流 ────────────────────────────────────────
def _intake():
    return BadCaseIntake(TraceStore(':memory:'))


def test_intake_requires_a_reason():
    intake = _intake()
    with pytest.raises(ValueError):
        intake.intake(session_id='s1', reason='')


def test_intake_to_label_to_queue_to_dataset():
    """完整回流链：记录 → 标注 → 入队 → 进回归集。"""
    intake = _intake()
    bid = intake.intake(session_id='s-42', trace_id='t-1',
                        reason='tool_call_without_result', source='replay')
    assert intake.open_cases()[0]['status'] == STATUS_NEW

    record = intake.label(bid, label='复现：工具无返回',
                          input_text='读取 a.txt',
                          expect=[{'output_contains': 'hello'}])
    assert record.status == STATUS_LABELLED
    assert intake.open_cases() == []

    item = intake.promote_to_queue(record)
    assert item.status == 'queued'
    assert item.session_id == 's-42'

    cases = intake.to_dataset([record])
    case = cases[0]
    assert isinstance(case, EvalCase)
    assert case.group == HARD_CASE_GROUP
    assert case.critical is True     # hard case 默认进关键集（质量闸门 100%）
    assert case.input == '读取 a.txt'
    assert case.expect == [{'output_contains': 'hello'}]
    assert any(tag.startswith('source_badcase:') for tag in case.tags)


def test_only_labelled_cases_can_enter_the_regression_set():
    intake = _intake()
    bid = intake.intake(session_id='s1', trace_id='t', reason='x')
    from infra.eval.badcase import LabelledBadCase
    raw = LabelledBadCase(id=bid, session_id='s1', trace_id='t', reason='x',
                          status=STATUS_NEW)
    with pytest.raises(ValueError):
        intake.to_dataset([raw])


def test_dismiss_keeps_a_trace():
    """误报也要留痕 —— dismissing 是一次标注，不是删除。"""
    intake = _intake()
    bid = intake.intake(session_id='s1', trace_id='t', reason='误报')
    intake.dismiss(bid)
    rows = intake._store.list_badcases(status=STATUS_DISMISSED)
    assert len(rows) == 1 and rows[0]['id'] == bid


def test_label_rejects_unknown_badcase():
    intake = _intake()
    with pytest.raises(KeyError):
        intake.label('ghost', label='x')


def test_set_badcase_status_round_trip():
    store = TraceStore(':memory:')
    bid = store.record_badcase(session_id='s', trace_id='t', reason='r')
    assert store.set_badcase_status(bid, STATUS_QUEUED) is True
    assert store.list_badcases(status=STATUS_QUEUED)[0]['id'] == bid
    assert store.set_badcase_status('ghost', STATUS_QUEUED) is False
    with pytest.raises(ValueError):
        store.set_badcase_status(bid, '')
