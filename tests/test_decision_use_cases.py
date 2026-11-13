"""System-1 决策用例适配器（harness/decisions/use_cases）测试。

覆盖：
  1. 情绪读取 —— 语义名取自 label 而不是自动编号的选项标签
  2. 危机判定 —— 阈值行为与保守取向
  3. 工具路由 —— 置信度不足时不路由
  4. 检索闸门 —— 语义是反的（问「够不够答」，要的是「要不要检索」）
  5. 通用分类
  6. **降级** —— 决策器抛异常时用例必须照常返回，不能打断主链路

全部用假决策器，不碰模型、不碰网络。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.decisions.core import DecisionRequest, DecisionResult  # noqa: E402
from harness.decisions.use_cases import (  # noqa: E402
    DecisionGate,
    classify,
    detect_crisis,
    needs_retrieval,
    probe_emotion,
    route_tool,
)


def _fixed(decider_type="choice", **kwargs):
    """造一个返回固定结果的假决策器。"""
    def _fn(req: DecisionRequest) -> DecisionResult:
        if req.normalized_type() == "yes_no":
            p = float(kwargs.get("yes", 0.9))
            return DecisionResult(
                type="yes_no", answer=p >= 0.5, probability=p,
                distribution={"Y": p, "N": 1 - p},
                confidence=abs(p - 0.5) * 2)
        options = req.normalized_options()
        labels = list(options.keys())
        top = kwargs.get("top", labels[0] if labels else "A")
        dist = {k: 0.1 for k in labels}
        if top in dist:
            dist[top] = 0.6
        total = sum(dist.values())
        dist = {k: v / total for k, v in dist.items()}
        best = max(dist, key=dist.get)
        from harness.decisions.core import choice_confidence
        return DecisionResult(
            type="choice", answer=best, label=options.get(best, ""),
            probability=dist[best], distribution=dist,
            confidence=choice_confidence(dist))
    return _fn


def _boom(req):
    raise RuntimeError("决策端点不可用")


# ── 情绪 ──

def test_probe_emotion_returns_semantic_label():
    """列表形式的选项会被编号成 A/B/C，语义名在 label 上。

    读错字段（取 answer）会让情绪永远变成 "A"。
    """
    reading = probe_emotion("今天太开心了！", _fixed(top="B"))
    assert reading.label == "开心"
    assert reading.valence > 0
    assert reading.arousal > 0.4
    assert reading.degraded is False


def test_probe_emotion_degrades_to_calm():
    reading = probe_emotion("随便说点什么", _boom)
    assert reading.degraded is True
    assert reading.label == "平静"
    assert reading.reason


# ── 危机 ──

def test_detect_crisis_flags_high_probability():
    out = detect_crisis("我真的不想活了", _fixed(yes=0.93))
    assert out.is_crisis is True
    assert out.confident is True
    assert out.level == "critical"


def test_detect_crisis_weak_signal_is_watch_not_critical():
    """没过阈值 → 只标记为「留意」，不当成「立即介入」。"""
    out = detect_crisis("最近有点烦", _fixed(yes=0.62))
    assert out.is_crisis is True
    assert out.confident is False
    assert out.level == "watch"


def test_detect_crisis_degrades_without_raising():
    out = detect_crisis("你好", _boom)
    assert out.degraded is True
    assert out.is_crisis is False


# ── 工具路由 ──

def test_route_tool_picks_top_candidate():
    """工具名是多 token 词，所以选项标签用字母、语义名回填。"""
    route = route_tool("我要退款", {"refund": "处理退款", "search": "搜索资料"},
                       _fixed(top="A"))
    assert route.name == "refund"
    assert route.degraded is False
    assert route.alternatives


def test_route_tool_options_are_single_token_labels():
    """发给模型的选项标签必须是单 token 字母。"""
    seen = {}

    def _spy(req):
        seen.update(req.normalized_options())
        return _fixed(top="A")(req)

    route_tool("x", {"refund": "处理退款"}, _spy)
    assert set(seen.keys()) == {"A"}
    assert "refund" in seen["A"]


def test_route_tool_skips_when_confidence_too_low():
    """置信度不足时不路由 —— 路由错误的代价通常高于不路由。"""
    route = route_tool("随便聊聊", {"a": "x", "b": "y", "c": "z"},
                       _fixed(top="A"), min_confidence=0.9)
    assert route.name == ""
    assert "confidence" in route.reason


def test_route_tool_without_candidates_degrades():
    route = route_tool("x", {}, _fixed())
    assert route.degraded is True
    assert route.name == ""


# ── 检索闸门 ──

def test_needs_retrieval_inverts_semantics():
    """模型答的是「已知信息够不够答」，我们要的是「要不要检索」。"""
    out = needs_retrieval("2024 年 GDP 是多少", "我不知道", _fixed(yes=0.1))
    assert out.value is True          # 答不上来 → 需要检索
    assert out.probability == pytest.approx(0.9, abs=0.01)


def test_needs_retrieval_false_when_context_suffices():
    out = needs_retrieval("我刚才说的那个数是多少", "你刚才说的是 42", _fixed(yes=0.95))
    assert out.value is False


# ── 通用分类 ──

def test_classify_returns_label():
    out = classify("下面哪个是质数？", ["选择题", "填空题"], _fixed(top="A"))
    assert out.label == "选择题"
    assert out.degraded is False


def test_classify_degrades_on_failure():
    out = classify("x", ["a", "b"], _boom)
    assert out.degraded is True
    assert out.label == ""


# ── 闸门 ──

def test_gate_reports_confidence_against_threshold():
    gate = DecisionGate("需要介入吗？", threshold=0.7)
    out = gate.evaluate("情况描述", decider=_fixed(yes=0.75))
    assert out.value is True
    assert out.confident is True


def test_gate_without_decider_degrades():
    gate = DecisionGate("q")
    out = gate.evaluate("s")
    assert out.degraded is True
    assert out.value is False


import pytest  # noqa: E402  (放在文件末尾仅为让上面的用法读起来顺)
