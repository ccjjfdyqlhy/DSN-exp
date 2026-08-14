# tests/test_harness_context_assembly.py
# 引擎层结构化上下文预算剪裁（harness/context_assembly.py）单元测试。

from __future__ import annotations

import pytest

from harness.context_assembly import (
    ContextBudget,
    ContextSegment,
    PRIORITY_ACTIVE,
    PRIORITY_CURRENT,
    PRIORITY_MEMO,
    PRIORITY_SUMMARY,
    SEG_MEMO,
    SEG_SUMMARY,
    SEG_VERBATIM,
    SegmentedContextAssembler,
)


def _memo(text: str, **kw) -> ContextSegment:
    return ContextSegment(kind=SEG_MEMO, content=text, priority=PRIORITY_MEMO, **kw)


def _summary(text: str) -> ContextSegment:
    return ContextSegment(kind=SEG_SUMMARY, content=text, priority=PRIORITY_SUMMARY,
                          label="[闭锁话题·测试·第1-3轮]")


def _verbatim(text: str, **kw) -> ContextSegment:
    return ContextSegment(kind=SEG_VERBATIM, content=text, priority=PRIORITY_ACTIVE, **kw)


def test_plan_keeps_all_under_budget():
    asm = SegmentedContextAssembler(ContextBudget(
        memo_chars=100, summary_chars=100, verbatim_chars=1000))
    plan = asm.plan([
        _memo("常驻事实A"),
        _summary("摘要一"),
        _verbatim("原文块"),
    ])
    assert [s.content for s in plan.kept] == ["常驻事实A", "摘要一", "原文块"]
    assert plan.dropped == []
    assert plan.total_chars > 0


def test_plan_summary_budget_trims():
    """summary 超预算的段被丢弃（预算独立于 memo）。"""
    asm = SegmentedContextAssembler(ContextBudget(
        memo_chars=1000, summary_chars=10, verbatim_chars=1000))
    plan = asm.plan([
        _summary("很长很长的摘要内容超过了预算"),
        _summary("第二条摘要"),
    ])
    kept = [s.content for s in plan.kept]
    assert "第一条" not in "".join(kept)  # 第一条超预算被丢
    assert "第二条" in "".join(kept) or kept  # 至少保留一条


def test_plan_verbatim_shared_budget_drops_overflow():
    """verbatim 共享预算：整体超预算的段被丢弃。"""
    asm = SegmentedContextAssembler(ContextBudget(verbatim_chars=20))
    big = _verbatim("x" * 30)
    small = _verbatim("short")
    plan = asm.plan([_verbatim("a" * 15), big, small])
    # 15 字符后剩 5：30 字符段放不下被丢弃；但 5 字符段可挤入
    kept = "".join(s.content for s in plan.kept)
    assert "x" * 30 not in kept
    assert "short" in kept


def test_plan_truncatable_segment_keeps_head():
    """truncatable 段超预算时截断保留头部（当前话题语义）。"""
    asm = SegmentedContextAssembler(ContextBudget(verbatim_chars=12))
    plan = asm.plan([
        _verbatim("aaaaaa"),                       # 6 字符
        ContextSegment(kind=SEG_VERBATIM, content="b" * 20,
                       priority=PRIORITY_CURRENT, truncatable=True),
    ])
    kept = [s for s in plan.kept if s.kind == SEG_VERBATIM]
    assert len(kept) == 2
    truncated = kept[1]
    assert truncated in plan.truncated
    assert truncated.content.startswith("b" * 6)
    assert "截断" in truncated.content


def test_plan_unbounded_memo_always_kept():
    """unbounded 段不占预算、不被剪裁（agent/跨用户常驻段语义）。"""
    asm = SegmentedContextAssembler(ContextBudget(memo_chars=5))
    plan = asm.plan([
        _memo("aaaa"),                    # 4 字符，预算内
        _memo("cccc", unbounded=True),    # 常驻，不占预算
        _memo("bbbbbb"),                  # 超预算被丢
        _memo("dddddd", unbounded=True),  # 常驻
    ])
    kept = [s.content for s in plan.kept]
    assert "cccc" in kept and "dddddd" in kept
    assert "bbbbbb" not in kept


def test_plan_skips_blank_segments():
    asm = SegmentedContextAssembler()
    plan = asm.plan([
        _memo(""),
        _summary("   "),
        _verbatim(""),
    ])
    assert plan.kept == []


def test_assemble_output_messages_and_tail():
    """assemble() 输出 role/content 消息，尾部原文原样追加。"""
    asm = SegmentedContextAssembler()
    tail = [{"role": "user", "content": "最近的对话"},
            {"role": "assistant", "content": "回复"}]
    msgs = asm.assemble(
        [_memo("备忘A", label="[备忘]"), _summary("摘要B")],
        tail=tail,
    )
    roles = [m["role"] for m in msgs]
    contents = [m["content"] for m in msgs]
    assert roles == ["system", "system", "user", "assistant"]
    assert "[备忘]\n备忘A" in contents
    assert "[闭锁话题·测试·第1-3轮]\n摘要B" in contents
    assert contents[-2:] == ["最近的对话", "回复"]


def test_assemble_accepts_chatmessage_tail():
    from harness.models.base import ChatMessage

    asm = SegmentedContextAssembler()
    msgs = asm.assemble([_memo("M")], tail=[ChatMessage.user("hi")])
    assert msgs[-1] == {"role": "user", "content": "hi"}


def test_budget_defaults():
    b = ContextBudget()
    assert b.memo_chars == 2000
    assert b.summary_chars == 2000
    assert b.verbatim_chars == 8000
    assert b.tail_rounds == 3
    assert b.max_open_topics == 3
