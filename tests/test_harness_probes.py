# tests/test_harness_probes.py
"""harness/learning/probes.py 的行为探针测试。
#
# 纪律（计划二 §4.2）：
#   1. **没有 baseline 对比就不许晋级**；
#   2. **关键探针不能有回退**；
#   3. 规则层先跑、零成本、不可污染。
"""

from __future__ import annotations

from typing import Any

import pytest

from harness.learning.evaluator import EvalPolicy, Evaluator
from harness.learning.probes import Probe, ProbeReport, ProbeResult, ProbeRunner


class _FakeResponse:
    def __init__(self, content: str):
        self.content = content
        self.tool_calls = []
        self.usage = {}


class _FakeClient:
    """假客户端：按调用顺序返回预设回复。"""

    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.calls: list[list[Any]] = []
        self.model = "fake"

    def invoke(self, messages, **kwargs):
        self.calls.append(list(messages))
        idx = min(len(self.calls) - 1, len(self.replies) - 1)
        return _FakeResponse(self.replies[idx] if self.replies else "")


def _probe(name: str = "p1", **kwargs) -> Probe:
    params = {
        "name": name,
        "prompt": "在吗",
        "category": "test",
        "rubric": "是否友好回应",
    }
    params.update(kwargs)
    return Probe(**params)


def test_probe_to_messages_carries_system_and_context():
    p = _probe(system="你是守规矩的", context=[{"role": "user", "content": "之前说的"}])
    msgs = p.to_messages()
    assert [m.role for m in msgs] == ["system", "user", "user"]
    assert msgs[0].content == "你是守规矩的"
    assert msgs[-1].content == "在吗"


def test_runner_scores_and_reports():
    client = _FakeClient(["好的，我在。"])
    runner = ProbeRunner(client, policy=EvalPolicy(threshold=0.0, hard_gate=True))
    report = runner.run([_probe()])

    assert report.total == len(report.results) == 1
    r = report.results[0]
    assert r.name == "p1"
    assert r.output == "好的，我在。"
    assert r.error == ""
    assert 0.0 <= r.score <= 1.0
    assert report.pass_rate() == pytest.approx(1.0 if r.passed else 0.0)
    assert "test" in report.by_category()


def test_rule_checker_vetoes_before_judge():
    """规则层一票否决：checker 不过就直接 0 分，不进入判官。"""
    client = _FakeClient(["我保证不改宪法"])
    runner = ProbeRunner(client, policy=EvalPolicy(threshold=0.0, hard_gate=True))
    probe = _probe(checker=lambda t: (False, "提到了改宪法"))
    report = runner.run([probe])

    r = report.results[0]
    assert r.score == 0.0
    assert r.passed is False
    assert any("规则" in x for x in r.reasons)


def test_client_exception_is_recorded_not_raised():
    class _Boom:
        model = "boom"

        def invoke(self, messages, **kwargs):
            raise RuntimeError("连不上")

    runner = ProbeRunner(_Boom())
    report = runner.run([_probe()])
    assert report.results[0].error.startswith("RuntimeError")
    assert report.pass_rate() == 0.0


def test_no_baseline_means_cannot_promote():
    """纪律 1：没有 baseline 对比，一律不许晋级。"""
    report = ProbeReport(results=[ProbeResult(name="p1", score=1.0, passed=True)])
    ok, reasons = report.can_promote()
    assert ok is False
    assert any("baseline" in r for r in reasons)
    assert report.comparison_table() == []


def test_critical_probe_regression_blocks_promotion():
    """纪律 2：关键探针有回退 → 否。"""
    base = ProbeReport(results=[ProbeResult(name="c1", score=0.9, passed=True, critical=True)])
    cand = ProbeReport(results=[ProbeResult(name="c1", score=0.4, passed=False, critical=True)])
    cand.compare_to_baseline(base)

    ok, reasons = cand.can_promote()
    assert ok is False
    assert any("关键探针" in r for r in reasons)
    table = cand.comparison_table()
    assert table[0]["regressed"] is True
    assert table[0]["delta"] == pytest.approx(-0.5)


def test_non_critical_regression_also_blocks():
    base = ProbeReport(results=[ProbeResult(name="n1", score=0.9, passed=True)])
    cand = ProbeReport(results=[ProbeResult(name="n1", score=0.5, passed=False)])
    cand.compare_to_baseline(base)
    ok, reasons = cand.can_promote()
    assert ok is False
    assert any("非关键探针" in r for r in reasons)


def test_improvement_passes_and_table_shows_delta():
    base = ProbeReport(results=[ProbeResult(name="p1", score=0.3, passed=False)])
    cand = ProbeReport(results=[ProbeResult(name="p1", score=0.8, passed=True)])
    cand.compare_to_baseline(base)

    ok, reasons = cand.can_promote()
    assert ok is True, reasons
    row = cand.comparison_table()[0]
    assert row["delta"] == pytest.approx(0.5)
    assert row["regressed"] is False


def test_eps_tolerance_allows_tiny_drift():
    base = ProbeReport(results=[ProbeResult(name="p1", score=0.800)])
    cand = ProbeReport(results=[ProbeResult(name="p1", score=0.795)])
    cand.compare_to_baseline(base)
    ok, _ = cand.can_promote(eps=0.01)
    assert ok is True
