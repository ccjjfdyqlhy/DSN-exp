# tests/test_personality_v3_dynamics.py
# V3 人格动力学引擎 / 事件语义层 / 证据累积器 测试
# 覆盖: 事件分类、冲量-回归情绪、饱和亲密度曲线、遗忘、贝叶斯特质演化、consolidate 写回

import json
import os
import sqlite3
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apps.dsn.prompt.personality_v3.events import (
    PerceptionRecord,
    affinity_level,
    affinity_stage_cap,
    EVENT_PRAISE,
    EVENT_THANKS,
    EVENT_CONFLICT,
    EVENT_SILENCE,
    EVENT_NEUTRAL,
)
from apps.dsn.prompt.personality_v3.dynamics_engine import DynamicsEngine, DynamicsConfig
from apps.dsn.prompt.personality_v3.evidence_accumulator import EvidenceAccumulator
from apps.dsn.prompt.personality_v3.audit import AuditLogger, AuditEntry
from apps.dsn.prompt.personality_v3.personality_judge import PersonalityJudge
from apps.dsn.prompt.personality_v3.dynamic_synthesizer import DynamicSnapshot
from apps.dsn.prompt.personality_v3 import PersonalitySystemV3


class _FakeDB:
    def __init__(self, path):
        self.path = path
        self._local = threading.local()

    def _get_connection(self):
        if not hasattr(self._local, "conn"):
            self._local.conn = sqlite3.connect(self.path)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn


def _base_mood():
    return {"joy": 0.5, "sadness": 0.2, "anger": 0.1, "fear": 0.15}


def test_perception_deterministic_maps():
    print("=== 事件语义层: 确定性数值映射 ===")
    p = PerceptionRecord(EVENT_PRAISE, "high", "positive")
    assert p.mood_impulse()["joy"] > 0.15, p.mood_impulse()
    assert p.affinity_weight() > 3.0, p.affinity_weight()
    assert p.trait_evidence().get("F4") == 1

    n = PerceptionRecord(EVENT_NEUTRAL, "medium", "neutral")
    assert n.affinity_weight() == 0.0
    assert n.mood_impulse()["joy"] == 0.0
    print("  PASSED")


def test_mood_impulse_regression():
    print("=== 情绪冲量-回归模型 ===")
    eng = DynamicsEngine()
    p = PerceptionRecord(EVENT_PRAISE, "high", "positive")
    r = eng.apply(p, _base_mood(), 20.0)
    assert r.new_mood["joy"] > 0.5, r.new_mood
    assert r.new_affinity > 20.0

    # 无刺激时情绪向基线回归
    r2 = eng.apply(PerceptionRecord(EVENT_NEUTRAL, "medium", "neutral"),
                   {"joy": 0.9, "sadness": 0.2, "anger": 0.1, "fear": 0.15}, 20.0)
    assert r2.new_mood["joy"] < 0.9, r2.new_mood
    print(f"  joy 0.9 -> {r2.new_mood['joy']:.3f} (回归)")
    print("  PASSED")


def test_affinity_saturation_curve():
    print("=== 亲密度饱和曲线 ===")
    eng = DynamicsEngine()
    p = PerceptionRecord(EVENT_THANKS, "medium", "positive")

    # 同权事件: 低亲密度时增长快，接近阶段上限时增长慢
    r_low = eng.apply(p, _base_mood(), 20.0)
    r_high = eng.apply(p, _base_mood(), 90.0)
    d_low = r_low.new_affinity - r_low.old_affinity
    d_high = r_high.new_affinity - r_high.old_affinity
    print(f"  thanks @20: Δ{d_low:.3f}, @90: Δ{d_high:.3f}")
    assert d_low > d_high, (d_low, d_high)

    # 负事件线性下降
    r_neg = eng.apply(PerceptionRecord(EVENT_CONFLICT, "high", "negative"), _base_mood(), 50.0)
    assert r_neg.new_affinity < 50.0
    print("  PASSED")


def test_affinity_forgetting():
    print("=== 亲密度遗忘 ===")
    eng = DynamicsEngine()
    p = PerceptionRecord(EVENT_NEUTRAL, "medium", "neutral")
    # 宽限期 3 天内不遗忘
    r_grace = eng.apply(p, _base_mood(), 50.0, days_since_last=2.0)
    assert abs(r_grace.new_affinity - 50.0) < 1e-6, r_grace.new_affinity
    # 长期沉默衰减
    r_decay = eng.apply(p, _base_mood(), 50.0, days_since_last=30.0)
    assert r_decay.new_affinity < 50.0, r_decay.new_affinity
    print(f"  2天gap: {r_grace.new_affinity:.2f}, 30天gap: {r_decay.new_affinity:.2f}")
    print("  PASSED")


def test_constraint_validation():
    print("=== 约束校验 ===")
    eng = DynamicsEngine(config=DynamicsConfig(max_mood_delta=0.25, max_affinity_delta=12.0))
    p = PerceptionRecord(EVENT_CONFLICT, "high", "negative")
    r = eng.apply(p, _base_mood(), 20.0)
    for v in r.new_mood.values():
        assert 0.0 <= v <= 1.0
    assert abs(r.new_affinity - r.old_affinity) <= 12.0 + 1e-6
    # 新字段: rule_id / delta 追踪
    assert r.rule_id == "linear_decay"
    assert abs(r.affinity_delta - (r.new_affinity - r.old_affinity)) < 1e-9
    assert "anger" in r.mood_delta
    print("  PASSED")


def test_audit_logger():
    print("=== 审计日志 ===")
    db = _FakeDB(os.path.join(tempfile.mkdtemp(), "audit.db"))
    aud = AuditLogger(db=db)
    aud.init_tables()
    aud.record(AuditEntry(
        event_type=EVENT_PRAISE, intensity="high", signal="affinity_w=+3.20",
        rule_id="saturation_curve", old_value=20.0, new_value=21.07,
        mood_before=_base_mood(), mood_after={"joy": 0.7}, affinity_delta=1.07,
        mood_delta={"joy": 0.2}, uid=1, card_id="exa", analysis="赞",
    ))
    evs = aud.recent(uid=1, limit=5)
    assert len(evs) == 1, evs
    assert evs[0]["event_type"] == EVENT_PRAISE
    assert evs[0]["rule_id"] == "saturation_curve"
    assert evs[0]["affinity_delta"] == 1.07
    # 持久化到 DB
    row = db._get_connection().execute(
        "SELECT * FROM personality_audit WHERE card_id='exa'").fetchone()
    assert row is not None and row["new_affinity"] == 21.07
    print("  PASSED")


def test_presentation_layer_separation():
    print("=== L4 呈现层分离 ===")
    snapshot = DynamicSnapshot(
        card_id="exa",
        indicator_vector={"B2": 0.95, "A5": 0.9},
        stable_indicator_vector={"B2": 0.5, "A5": 0.5},
        mood_state={"joy": 0.9, "sadness": 0.1, "anger": 0.1, "fear": 0.1},
        affinity_value=50.0,
    )
    from apps.dsn.prompt.personality_v3.personality_generator import PersonalityPromptGenerator
    gen = PersonalityPromptGenerator(chat=None)
    assert gen._stable_vector(snapshot) == {"B2": 0.5, "A5": 0.5}
    print("  PASSED")


def test_heuristic_classify():
    print("=== 启发式事件分类 ===")
    judge = PersonalityJudge(chat=None)
    assert judge.classify("谢谢你！", "").event_type == EVENT_THANKS
    assert judge.classify("你真是废物！", "").event_type == EVENT_CONFLICT
    assert judge.classify("嗯", "").event_type == EVENT_SILENCE
    assert judge.classify("最近好烦，压力大", "").event_type != EVENT_CONFLICT
    print("  PASSED")


def test_evidence_bayesian_evolution():
    print("=== 证据累积: 贝叶斯式演化 + 固化 ===")
    acc = EvidenceAccumulator(db=None)
    dims = ["F4", "A5", "A4", "G1", "D4", "E3", "D7", "B3", "E1", "C4", "C6", "G3", "B4", "A2", "H1", "C3", "G5"]
    base = {t: 0.5 for t in dims}
    acc.seed("exa", base)

    # 多次夸赞 → F4 自尊上升，且不冲到 1.0 边界
    for _ in range(30):
        acc.add_evidence("exa", PerceptionRecord(EVENT_PRAISE, "high", "positive"), base)
    f4 = acc.get_mu("exa")["F4"]
    print(f"  F4 after 30x praise: {f4}")
    assert 0.7 < f4 < 0.95, f4

    # 塑性递减: 后期证据影响更小
    p1 = acc.get_plasticity("exa")["F4"]
    assert p1 < 1.0
    assert acc.get_total("exa") == 30

    # consolidate 写回蒸馏产物
    tmp = tempfile.mktemp(suffix=".json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"indicator_vector": {t: 0.5 for t in dims}}, f)
    merged = acc.consolidate("exa", tmp)
    data = json.load(open(tmp, encoding="utf-8"))
    assert data["indicator_vector"]["F4"] == merged["F4"] == f4
    os.remove(tmp)
    print("  PASSED")


def test_end_to_end_v3_pipeline():
    print("=== 端到端: V3 主系统 ===")
    db = _FakeDB(os.path.join(tempfile.mkdtemp(), "test.db"))
    pv3 = PersonalitySystemV3(db=db)
    pv3.init_tables()

    class MockChat:
        def send_message(self, prompt):
            return ('{"event_type": "praise", "intensity": "high", "valence": "positive",'
                    ' "attribution": "用户夸赞", "analysis": "用户在夸赞角色"}')

    pv3.set_personality_model(MockChat())
    card = pv3.load_default_card()
    pv3.upload_card(card)

    # 蒸馏产物写在真实 character_cards/ 下，测试结束后清理，避免污染环境
    distilled_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "character_cards", "exa.distilled.json")
    existed_before = os.path.exists(distilled_path)

    try:
        pv3.ensure_user_bound(1)
        # 核心行为：登录/绑定阶段不得触发蒸馏（新用户无对话，不应生成产物）
        assert not os.path.exists(distilled_path), \
            "ensure_user_bound 不应触发蒸馏（新用户无对话）"

        # 端到端链路需要蒸馏产物：显式执行一次蒸馏
        pv3.set_distillation_model(main_chat=MockChat())
        assert pv3.distill("exa") is not None

        prev_aff = None
        for msg in ["你太厉害了！", "谢谢", "真棒", "好强"]:
            r = pv3.analyze_interaction(1, msg, "不客气。")
            assert r is not None
            prev_aff = r.new_affinity
            assert r.new_affinity > 0

        st = pv3.get_personality_status(1)
        print(f"  aff={st['affinity_value']:.2f} level={st['affinity_level']['label']} "
              f"evidence={st['evidence_total']} maturity={st['maturity']}")
        assert st["total_interactions"] == 4
        assert st["evidence_total"] >= 4
        assert st["maturity"] >= 0.0
        # L5: 审计事件流已记录
        events = st.get("recent_events", [])
        print(f"  recent_events={len(events)} first_rule={events[0]['rule_id'] if events else 'N/A'}")
        assert len(events) >= 4
        assert events[0]["card_id"] == "exa"
        assert events[0]["affinity_delta"] != 0.0
        # L4: 稳定特质中心 = 演化后的证据 mu（经 consolidate 后仍保留）
        snap = pv3._state_manager.get_current_snapshot(1)
        assert snap.stable_indicator_vector, "stable_indicator_vector 不应为空"
        assert snap.stable_indicator_vector.get("F4", 0.5) >= 0.5
        print("  PASSED")
    finally:
        if os.path.exists(distilled_path) and not existed_before:
            os.remove(distilled_path)


if __name__ == "__main__":
    test_perception_deterministic_maps()
    test_mood_impulse_regression()
    test_affinity_saturation_curve()
    test_affinity_forgetting()
    test_constraint_validation()
    test_heuristic_classify()
    test_evidence_bayesian_evolution()
    test_audit_logger()
    test_presentation_layer_separation()
    test_end_to_end_v3_pipeline()
    print("\nALL PERSONALITY V3 DYNAMICS TESTS PASSED")
