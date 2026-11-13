# -*- coding: utf-8 -*-
"""dsn_study 主AI「没有上下文 / 只能短回复 / 固定假记忆」的回归测试。

三条根因，各自钉一条：

1. **没有上下文** —— 学习上下文（今日计划 / 到期复习 / 错题本 / 长期备忘）
   算好之后没进 system prompt：
   * `StudyPromptBuilder.build(uid=...)` 把 contextvars 里的上下文清成空串；
   * 管线跑在自己的事件循环线程里，contextvars 根本不跨线程继承 ——
     上下文必须经 `ctx.extra` 显式传进插件。
2. **只能短回复** —— 语音轮无条件注入「不超过 40 字」指令，
   把主AI 钉死在只回一两句话。现在改成开关（默认关）。
3. **固定假记忆** —— 关话题时写死的占位摘要
   「与【X】相关的过往探讨」被当作 [话题回顾] 注入 system prompt，
   主AI 每次都带着同一条假记忆（本机是「找物理卷子」那条）。
"""

from __future__ import annotations

import os

import pytest


# ── 1) 学习上下文必须进 prompt ───────────────────────────────────

def test_build_with_uid_keeps_turn_context():
    """build(uid=...) 不能把本轮上下文清空（旧实现 context or "" → 空串）。"""
    from apps.dsn_study.prompts.builder import StudyPromptBuilder

    b = StudyPromptBuilder()
    b.begin_turn(1, "(系统上下文·仅供你参考，不要复述) [错题本] 累计 42 道错题待巩固")
    try:
        prompt = b.build(uid=1)
        assert "[错题本] 累计 42 道错题待巩固" in prompt, \
            "build(uid=...) 把学习上下文清空了"
    finally:
        b.begin_turn(1, "")


def test_build_with_explicit_context_overrides():
    """显式传入的上下文优先于 contextvars 里的旧值。"""
    from apps.dsn_study.prompts.builder import StudyPromptBuilder

    b = StudyPromptBuilder()
    b.begin_turn(1, "旧上下文")
    try:
        prompt = b.build(uid=1, context="新上下文")
        assert "新上下文" in prompt
        assert "旧上下文" not in prompt
    finally:
        b.begin_turn(1, "")


def test_system_prompt_plugin_renders_learning_context():
    """插件从 ctx.extra 取学习上下文（管线线程拿不到 contextvars）。"""
    from harness.pipeline.base import Context, HookPoint
    from apps.dsn_study.pipeline import plugins
    from apps.dsn_study.prompts.builder import StudyPromptBuilder

    b = StudyPromptBuilder()
    p = plugins.SystemPromptPlugin(prompt_builder=b)
    ctx = Context(user_id=1, message="今天做什么", session_id="s")
    ctx.extra["learning_context"] = "(系统上下文·仅供你参考，不要复述) [今日计划] 1/3 已完成"
    out = p.on_hook(HookPoint.PREPARE, ctx)
    assert "[今日计划] 1/3 已完成" in (out.system_prompt or ""), \
        "学习上下文没进 system prompt"
    assert "{user_context}" not in (out.system_prompt or ""), "占位符没渲染"


def test_voice_mode_also_renders_learning_context():
    """语音轮同样要带上下文（之前只有身份+人格）。"""
    from harness.pipeline.base import Context, HookPoint
    from apps.dsn_study.pipeline import plugins
    from apps.dsn_study.prompts.builder import StudyPromptBuilder

    b = StudyPromptBuilder()
    p = plugins.SystemPromptPlugin(prompt_builder=b)
    ctx = Context(user_id=1, message="在吗", session_id="s", is_asr_input=True)
    ctx.extra["learning_context"] = "[错题本] 累计 7 道错题待巩固"
    out = p.on_hook(HookPoint.PREPARE, ctx)
    assert "[错题本] 累计 7 道错题待巩固" in (out.system_prompt or "")


def test_engine_exposes_learning_context_helper():
    """StudyEngine 有统一的上下文入口（boot 注入管线的就是它）。"""
    from apps.dsn_study.boot import StudyEngine

    assert hasattr(StudyEngine, "_learning_context"), \
        "缺 _learning_context —— boot 无从把学习上下文送进管线"


# ── 2) 语音轮不该被强制短回复 ───────────────────────────────────

def test_voice_short_reply_off_by_default():
    from apps.dsn_study.config import Config
    assert getattr(Config, "VOICE_SHORT_REPLY", False) is False, \
        "短回复限制默认应当关闭（主AI 要能完整回答）"


def test_voice_mode_has_no_length_cap_by_default(monkeypatch):
    from harness.pipeline.base import Context, HookPoint
    from apps.dsn_study.config import Config
    from apps.dsn_study.pipeline import plugins
    from apps.dsn_study.prompts.builder import StudyPromptBuilder

    monkeypatch.setattr(Config, "VOICE_SHORT_REPLY", False, raising=False)
    b = StudyPromptBuilder()
    p = plugins.SystemPromptPlugin(prompt_builder=b)
    ctx = Context(user_id=1, message="讲讲动能定理", session_id="s",
                  is_asr_input=True)
    out = p.on_hook(HookPoint.PREPARE, ctx)
    text = out.system_prompt or ""
    assert "不超过 40 个字" not in text, "语音轮仍被钉死在 40 字以内"
    assert "语音对话模式" not in text


def test_voice_short_reply_can_be_enabled(monkeypatch):
    """开关打开时短回复指令回来（要「快答」的场景用）。"""
    from harness.pipeline.base import Context, HookPoint
    from apps.dsn_study.config import Config
    from apps.dsn_study.pipeline import plugins
    from apps.dsn_study.prompts.builder import StudyPromptBuilder

    monkeypatch.setattr(Config, "VOICE_SHORT_REPLY", True, raising=False)
    b = StudyPromptBuilder()
    p = plugins.SystemPromptPlugin(prompt_builder=b)
    ctx = Context(user_id=1, message="在吗", session_id="s", is_asr_input=True)
    out = p.on_hook(HookPoint.PREPARE, ctx)
    assert "语音对话模式" in (out.system_prompt or "")


# ── 3) 话题摘要不能是零信息占位串 ───────────────────────────────

def test_content_summary_uses_real_messages():
    from apps.dsn_study.memory.topics import TopicManager

    msgs = [
        {"role": "user", "content": "找一套最新的高三物理期中卷子做"},
        {"role": "assistant", "content": "卷子找到了，北师大附中那套，已下载到本地。"},
    ]
    summary = TopicManager._content_summary(msgs)
    assert "物理" in summary and "北师大附中" in summary, \
        "兜底摘要必须带真实内容"


def test_close_topic_writes_content_summary(tmp_path):
    """关话题时写下的摘要必须含事实，不能是「与【X】相关的过往探讨」。"""
    from apps.dsn_study.memory.topics import TopicManager

    mgr = TopicManager(str(tmp_path / "topics.db"), summary_model=None,
                       embedding_client=None, judge_chat=None)
    uid, cid = 1, 1
    mgr.on_new_message(uid, cid, "找一套最新的高三物理期中卷子做", round_idx=1)
    tid = mgr.current_topic(uid, cid)["topic_id"]
    mgr.record_turn(uid, cid, "找一套最新的高三物理期中卷子做",
                     "卷子找到了，已下载到本地 workspace。", round_idx=1)
    mgr.close_topic(uid, cid, tid)

    topic = mgr.store.get_topic(tid)
    assert topic and topic["summary"], "关话题必须写摘要"
    assert "相关的过往探讨" not in topic["summary"], \
        "仍在写零信息占位摘要"
    assert "物理" in topic["summary"], "摘要应含话题的真实内容"


def test_assemble_skips_placeholder_summaries(tmp_path):
    """占位摘要不进上下文（否则主AI 每次都带着同一条假记忆）。"""
    from apps.dsn_study.memory.topics import TopicManager

    mgr = TopicManager(str(tmp_path / "topics.db"), summary_model=None,
                       embedding_client=None, judge_chat=None)
    uid, cid = 1, 1
    mgr.on_new_message(uid, cid, "找一套最新的高三物理期中卷子做", round_idx=1)
    tid = mgr.current_topic(uid, cid)["topic_id"]
    mgr.record_turn(uid, cid, "找一套最新的高三物理期中卷子做", "好", round_idx=1)
    mgr.close_topic(uid, cid, tid,
                    summary="与【找一套最新的高三物理期中卷子做】相关的过往探讨")

    assembled = mgr.assemble_topic_context(uid, cid)
    blob = "\n".join(m.get("content", "") for m in assembled)
    assert "相关的过往探讨" not in blob, "占位摘要仍被注入上下文"
