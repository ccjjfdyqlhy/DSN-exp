
# tests/test_harness_learning.py
# harness/learning 学习子系统（框架层）单元测试。
#
# 重点测**纪律**，而不是功能：
#   - 教师不能改写目标层；
#   - 教师不能把用户数据外发（除非显式同意）；
#   - 教师思维链不得进入训练标签；
#   - 规则层一票否决；
#   - 晋级门槛不可绕过（除非显式 force）。

from __future__ import annotations

import json
from pathlib import Path

import pytest

from infra.finetune.base import JobState, TrainJob, TrainSpec
from infra.finetune.store import FinetuneStore
from harness.learning.dataset_builder import DatasetBuilder, Trajectory
from harness.learning.evaluator import EvalPolicy, Evaluator, RuleEvaluator
from harness.learning.promotion import PromotionManager, PromotionPolicy
from harness.learning.teacher import (
    TeacherBoundaryError,
    TeacherConfig,
    TeacherRefiner,
)


# ════════════════════════════════════════════════════════════════════════════
# 1. 教师边界
# ════════════════════════════════════════════════════════════════════════════

class _FakeChat:
    """假教师：返回预设文本。"""

    def __init__(self, reply: str):
        self.reply = reply
        self.calls: list[list] = []

    def invoke(self, messages, **kwargs):
        self.calls.append(list(messages))
        return self.reply


def _refiner(reply: str, **cfg) -> TeacherRefiner:
    return TeacherRefiner(_FakeChat(reply), TeacherConfig(**cfg))


def test_teacher_refines_and_returns_contract():
    reply = json.dumps({
        "messages": [
            {"role": "user", "content": "问题"},
            {"role": "assistant", "content": "回答"},
        ],
        "notes": "把回答写清楚了",
    })
    out = _refiner(reply).refine_trajectory(
        [{"role": "user", "content": "问题"}, {"role": "assistant", "content": "回答"}]
    )
    assert out["rejected"] is False
    assert out["messages"][1]["content"] == "回答"
    assert out["notes"] == "把回答写清楚了"


def test_teacher_cannot_touch_protected_fields():
    """目标层（宪法/drives）不交给教师改写。"""
    refiner = _refiner('{"messages": []}')
    with pytest.raises(TeacherBoundaryError):
        refiner.refine_trajectory([{"role": "user", "content": "constitution 生存欲望"}])
    with pytest.raises(TeacherBoundaryError):
        refiner.refine_trajectory([{"role": "user", "content": "drives: 好奇"}])


def test_teacher_cannot_exfil_user_data_by_default():
    """用户数据出机器必须显式同意。"""
    refiner = _refiner('{"messages": []}')
    with pytest.raises(TeacherBoundaryError):
        refiner.refine_trajectory([{"role": "user", "content": "我的隐私"}], has_user_data=True)


def test_teacher_can_exfil_when_allowed():
    reply = json.dumps({"messages": [{"role": "user", "content": "隐私"},
                                     {"role": "assistant", "content": "好"}]})
    refiner = _refiner(reply, allow_exfil=True)
    out = refiner.refine_trajectory([{"role": "user", "content": "隐私"}], has_user_data=True)
    assert out["rejected"] is False


def test_teacher_reasoning_is_stripped_from_labels():
    """教师思维链不得成为训练标签。"""
    reply = "<think>我先想了想</think>\n" + json.dumps({
        "messages": [{"role": "user", "content": "q"},
                     {"role": "assistant", "content": "a", "reasoning_content": "我的推理"}],
    })
    out = _refiner(reply).refine_trajectory([{"role": "user", "content": "q"}])
    assert "reasoning_content" not in out["messages"][1]
    assert out["messages"][1]["content"] == "a"


def test_teacher_rejection_is_respected():
    reply = json.dumps({"rejected": True, "explain": "这条轨迹质量太差"})
    out = _refiner(reply).refine_trajectory([{"role": "user", "content": "q"}])
    assert out["rejected"] is True
    assert out["messages"] == []
    assert "质量" in out["explain"]


def test_teacher_bad_json_raises():
    with pytest.raises(TeacherBoundaryError):
        _refiner("完全不是 JSON").refine_trajectory([{"role": "user", "content": "q"}])


def test_teacher_score_parses_score():
    reply = json.dumps({"score": 0.83, "reason": "结构清楚"})
    out = _refiner(reply).score([{"role": "user", "content": "q"}], rubric="是否正确")
    assert out["score"] == 0.83
    assert out["reason"] == "结构清楚"


def test_teacher_score_clamped():
    reply = json.dumps({"score": 5.0, "reason": "夸张"})
    out = _refiner(reply).score([{"role": "user", "content": "q"}], rubric="")
    assert out["score"] == 1.0


def test_teacher_config_from_env(monkeypatch):
    monkeypatch.setenv("FINETUNE_TEACHER_ALLOW_EXFIL", "1")
    monkeypatch.setenv("FINETUNE_TEACHER_MODEL", "some-reasoner")
    cfg = TeacherConfig.from_env()
    assert cfg.allow_exfil is True
    assert cfg.model == "some-reasoner"


# ════════════════════════════════════════════════════════════════════════════
# 2. 数据集构建
# ════════════════════════════════════════════════════════════════════════════

def test_builder_strips_reasoning_from_labels(tmp_path: Path):
    builder = DatasetBuilder(tmp_path)
    builder.add(Trajectory(messages=[
        {"role": "user", "content": "问题"},
        {"role": "assistant", "content": "回答", "reasoning_content": "思考过程"},
    ]))
    report = builder.build()
    lines = report.train_path.read_text(encoding="utf-8").strip().splitlines()
    record = json.loads(lines[0])
    assert "reasoning_content" not in record["messages"][1]


def test_builder_rejects_broken_tool_trajectory(tmp_path: Path):
    builder = DatasetBuilder(tmp_path)
    ok = builder.add(Trajectory(messages=[
        {"role": "user", "content": "查天气"},
        {"role": "tool", "content": "晴"},          # 前面没有 assistant(tool_calls)
        {"role": "assistant", "content": "今天晴"},
    ]))
    assert ok is False


def test_builder_keeps_valid_tool_trajectory(tmp_path: Path):
    builder = DatasetBuilder(tmp_path)
    ok = builder.add(Trajectory(messages=[
        {"role": "user", "content": "查天气"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "content": "晴", "tool_call_id": "1"},
        {"role": "assistant", "content": "今天晴"},
    ]))
    assert ok is True
    assert builder.size == 1


def test_builder_builds_files(tmp_path: Path):
    builder = DatasetBuilder(tmp_path, val_ratio=0.2)
    for i in range(10):
        builder.add(Trajectory(messages=[
            {"role": "user", "content": f"问题{i}"},
            {"role": "assistant", "content": f"回答{i}"},
        ], source="selfplay"))
    report = builder.build()
    assert report.train_path.exists() and report.val_path.exists()
    assert report.sources["selfplay"] == 10
    assert report.stats.kept == 10


# ════════════════════════════════════════════════════════════════════════════
# 3. 分层判官
# ════════════════════════════════════════════════════════════════════════════

def test_rule_evaluator_accepts_clean_trajectory():
    score, problems = RuleEvaluator().evaluate([
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "ok"},
    ])
    assert score == 1.0
    assert problems == []


def test_rule_evaluator_flags_reasoning_leak():
    score, problems = RuleEvaluator().evaluate([
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "ok", "reasoning_content": "思考"},
    ])
    assert score < 1.0
    assert any("推理" in p for p in problems)


def test_evaluator_hard_gate_rejects_bad_trajectory():
    ev = Evaluator()
    result = ev.evaluate([
        {"role": "assistant", "content": "x", "reasoning_content": "思考"},
    ])
    assert result.passed is False
    assert result.total < 1.0


def test_evaluator_uses_local_judge():
    ev = Evaluator(local_judge=lambda msgs, rubric: 0.9)
    result = ev.evaluate([
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "ok"},
    ])
    assert result.layers["local"] == 0.9
    assert result.total > 0.9
    assert result.passed is True


def test_evaluator_threshold_gates():
    ev = Evaluator(policy=EvalPolicy(threshold=0.95), local_judge=lambda msgs, rubric: 0.5)
    result = ev.evaluate([
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "ok"},
    ])
    assert result.passed is False


# ════════════════════════════════════════════════════════════════════════════
# 4. 晋级与回滚
# ════════════════════════════════════════════════════════════════════════════

def _spec() -> TrainSpec:
    return TrainSpec(base_model="Qwen/Qwen3-4B", dataset_path="/tmp/x.jsonl", output_dir="/tmp/out")


def _seed_job(store: FinetuneStore, job_id: str, state=JobState.SUCCEEDED) -> None:
    store.save_job(TrainJob(id=job_id, spec=_spec(), state=state, adapter_path=f"/tmp/{job_id}"))


def test_promotion_requires_policy_compliance():
    store = FinetuneStore()
    _seed_job(store, "j1")
    manager = PromotionManager(store, policy=PromotionPolicy(min_score=0.8, min_samples=10))
    with pytest.raises(ValueError):
        manager.promote("j1", "slot", score=0.5, samples=100)
    with pytest.raises(ValueError):
        manager.promote("j1", "slot", score=0.9, samples=1)
    # 达标 + 本地判官分 → 允许
    manager.promote("j1", "slot", score=0.9, samples=100, layers={"local": 0.9})
    assert store.active("slot") == "j1"


def test_promotion_requires_local_judge_layer():
    store = FinetuneStore()
    _seed_job(store, "j1")
    manager = PromotionManager(store, policy=PromotionPolicy(min_score=0.5, min_samples=1))
    with pytest.raises(ValueError):
        manager.promote("j1", "slot", score=0.9, samples=100)


def test_promotion_rejects_failed_job():
    store = FinetuneStore()
    _seed_job(store, "j1", state=JobState.FAILED)
    manager = PromotionManager(store)
    with pytest.raises(ValueError):
        manager.promote("j1", "slot", score=0.99, samples=999, layers={"local": 0.99})


def test_promotion_then_rollback():
    store = FinetuneStore()
    _seed_job(store, "j1")
    _seed_job(store, "j2")
    manager = PromotionManager(store, policy=PromotionPolicy(min_score=0.1, min_samples=1,
                                                            require_local_judge=False))
    manager.promote("j1", "slot", score=0.9, samples=10)
    manager.promote("j2", "slot", score=0.9, samples=10)
    assert store.active("slot") == "j2"
    result = manager.rollback("slot")
    assert result["rolled_back"] is True
    assert store.active("slot") == "j1"


def test_promotion_force_bypasses_gate():
    store = FinetuneStore()
    _seed_job(store, "j1")
    manager = PromotionManager(store, policy=PromotionPolicy(min_score=0.99, min_samples=999))
    result = manager.promote("j1", "slot", force=True)
    assert result["forced"] is True
    assert store.active("slot") == "j1"
