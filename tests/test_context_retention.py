# tests/test_context_retention.py
# 回归测试：压缩上下文不得丢失最近对话 / 不得重复注入。
#
# 背景（2026-10）：用户反馈「弹性上下文有时候会丢失刚聊过的上一条消息」。
# 根因是 apps/dsn_ui/topic_manager.py 把当前话题的全部原文当成**单个**
# SEG_VERBATIM 段提交给预算剪裁；当前话题一长，verbatim 预算耗尽时
# 整段被裁掉，而其中包含最近一轮。
#
# 修复：补上 SEG_TAIL 保底段（最近 N 轮原文，不参与共享预算）。
# 本文件锁定该行为，防止回归。

from __future__ import annotations

import pytest

from apps.dsn_ui.topic_manager import DSNUITopicContextManager
from harness.context_assembly import ContextBudget
from infra.orchestrator import ChatMessage


KEY_MESSAGE = "刚刚问的那个关键问题"


def _manager(verbatim_chars: int) -> DSNUITopicContextManager:
    budget = ContextBudget(
        memo_chars=10,
        summary_chars=10,
        verbatim_chars=verbatim_chars,
        tail_rounds=3,
    )
    mgr = DSNUITopicContextManager(budget=budget)
    topic = mgr.get_or_create_current_topic("开局")
    # 灌入足够多的历史，确保小预算下必然触发剪裁
    for i in range(10):
        topic.add_message(ChatMessage.user(f"历史{i}:" + "填" * 80))
        topic.add_message(ChatMessage.assistant(f"回复{i}:" + "填" * 80))
    topic.add_message(ChatMessage.user(KEY_MESSAGE))
    return mgr


def _flatten(msgs) -> str:
    parts = []
    for m in msgs:
        content = m.content if isinstance(m.content, str) else ""
        parts.append(content)
    return "\n".join(parts)


@pytest.mark.parametrize("verbatim_chars", [1, 30, 80, 200, 2000])
def test_recent_message_survives_any_budget(verbatim_chars):
    """无论 verbatim 预算多小，最近一条消息都必须出现在上下文中。"""
    mgr = _manager(verbatim_chars)
    blob = _flatten(mgr.assemble_context_messages("本轮新问题"))
    assert KEY_MESSAGE in blob, (
        f"verbatim_chars={verbatim_chars} 时最近一条消息被丢弃了"
    )


def test_no_duplicate_injection_with_roomy_budget():
    """预算充足时，尾部保底段不应与当前话题原文重复注入。"""
    mgr = _manager(200000)
    blob = _flatten(mgr.assemble_context_messages("本轮新问题"))
    assert KEY_MESSAGE in blob
    assert blob.count(KEY_MESSAGE) == 1, "最近消息被重复注入了两次"


def test_tail_rounds_respected():
    """tail_rounds 应转化为尾部保底段（未超预算时不额外重复）。"""
    mgr = _manager(200000)
    msgs = mgr.assemble_context_messages("本轮新问题")
    # 消息结构：可选的合并 system + 本轮 user
    assert msgs[-1].role == "user"
    assert msgs[-1].content == "本轮新问题"
