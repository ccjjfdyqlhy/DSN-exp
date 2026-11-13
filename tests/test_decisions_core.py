"""System-1 决策核心（harness/decisions/core）测试。

覆盖：
  1. token 变体归并 —— Y / " Y" / Yes 必须合成同一个选项的概率
  2. 归一化与置信度
  3. 提示词构造（三种决策类型）
  4. 分布解释：yes_no / choice / score
  5. 选项标签生成（A..Z 之后接双字母，保证单 token）

这些是**纯逻辑**，不需要模型、不需要网络。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.decisions.core import (  # noqa: E402
    DecisionError,
    DecisionRequest,
    build_prompt,
    choice_confidence,
    interpret,
    label_variants,
    letter_labels,
    normalize,
    token_probability,
)


# ── 1. token 变体归并 ──

def test_token_probability_merges_spellings():
    """同一个选项的多种写法要加总，不能只取完全相等的那个。

    llama.cpp 的 tokenizer 里 Y / " Y" / Yes 是不同 token，
    漏算会让归一化后的分布失真。
    """
    candidates = {"Y": 0.9, " Y": 0.06, "Yes": 0.03, "N": 0.01}
    got = token_probability(candidates, ["Y", "Yes"])
    assert got == pytest.approx(0.99)


def test_token_probability_ignores_other_tokens():
    candidates = {"The": 0.5, "N": 0.5}
    assert token_probability(candidates, ["Y", "Yes"]) == 0.0


def test_label_variants_cover_case_and_space():
    variants = label_variants("A")
    assert "A" in variants and " a" in variants and "A" not in (" a",)


# ── 2. 归一化与置信度 ──

def test_normalize_sums_to_one():
    dist = normalize({"a": 1.0, "b": 3.0})
    assert sum(dist.values()) == pytest.approx(1.0)
    assert dist["b"] == pytest.approx(0.75)


def test_normalize_empty_when_all_zero():
    assert normalize({"a": 0.0, "b": 0.0}) == {}


def test_choice_confidence_bounds():
    """均匀乱猜 = 0，完全确定 = 1。"""
    assert choice_confidence({"a": 0.5, "b": 0.5}) == pytest.approx(0.0)
    assert choice_confidence({"a": 1.0, "b": 0.0}) == pytest.approx(1.0)
    mid = choice_confidence({"a": 0.75, "b": 0.25})
    assert 0.0 < mid < 1.0


# ── 3. 提示词 ──

def test_prompt_yes_no_has_single_letter_instruction():
    req = DecisionRequest(type="yes_no", question="威胁取消订阅吗？", state="邮件正文")
    prompt = build_prompt(req)
    assert "威胁取消订阅吗？" in prompt
    assert "邮件正文" in prompt
    assert "Y for yes" in prompt and "N for no" in prompt


def test_prompt_choice_lists_options():
    req = DecisionRequest(
        type="choice", question="分派给谁？", state="工单",
        options={"A": "billing", "B": "technical"})
    prompt = build_prompt(req)
    assert "A: billing" in prompt and "B: technical" in prompt
    assert "option label only" in prompt


def test_prompt_score_states_range():
    req = DecisionRequest(type="score", question="多紧急？", max_score=7)
    assert "0 to 7" in build_prompt(req)


def test_prompt_rejects_unknown_type():
    with pytest.raises(DecisionError):
        build_prompt(DecisionRequest(type="wat"))


# ── 4. 分布解释 ──

def test_interpret_yes_no_merges_and_normalizes():
    req = DecisionRequest(type="yes_no", question="q", state="s")
    res = interpret({"Y": 0.9, " Y": 0.06, "N": 0.04}, req)
    assert res.answer is True
    assert res.probability == pytest.approx(0.96)
    assert res.distribution["Y"] + res.distribution["N"] == pytest.approx(1.0)


def test_interpret_yes_no_answers_false_below_half():
    req = DecisionRequest(type="yes_no", question="q")
    res = interpret({"Y": 0.2, "N": 0.8}, req)
    assert res.answer is False
    assert res.probability == pytest.approx(0.2)


def test_interpret_choice_picks_top_and_keeps_label():
    """归一化只在**认出来的选项**之间做 —— 不在选项集里的 token 被丢掉。"""
    req = DecisionRequest(
        type="choice", question="q", options=["billing", "technical"])
    res = interpret({"A": 0.7, "B": 0.25, "C": 0.05}, req)
    assert res.answer == "A"
    assert res.label == "billing"
    # 0.7 / (0.7 + 0.25)
    assert res.probability == pytest.approx(0.7 / 0.95)
    assert sum(res.distribution.values()) == pytest.approx(1.0)


def test_interpret_choice_requires_two_options():
    req = DecisionRequest(type="choice", question="q", options=["only"])
    with pytest.raises(DecisionError):
        interpret({"A": 1.0}, req)


def test_interpret_score_computes_expectation():
    """期望值必须把字符串键转成整数 —— 否则 "5" * 0.3 直接 TypeError。"""
    req = DecisionRequest(type="score", question="q", max_score=5)
    res = interpret({"0": 0.1, "1": 0.1, "2": 0.1, "3": 0.1, "4": 0.2, "5": 0.4}, req)
    assert res.answer == 5
    # 0*.1 + 1*.1 + 2*.1 + 3*.1 + 4*.2 + 5*.4 = 3.4
    assert res.expectation == pytest.approx(3.4)


def test_interpret_raises_when_no_option_recognized():
    req = DecisionRequest(type="yes_no", question="q")
    with pytest.raises(DecisionError):
        interpret({"The": 0.9, "cat": 0.1}, req)


# ── 5. 选项标签 ──

def test_letter_labels_cover_single_and_double():
    assert letter_labels(0) == "A"
    assert letter_labels(25) == "Z"
    assert letter_labels(26) == "AA"
    assert letter_labels(27) == "AB"


def test_normalized_options_numbers_lists():
    req = DecisionRequest(type="choice", options=["a", "b", "c"])
    assert req.normalized_options() == {"A": "a", "B": "b", "C": "c"}
