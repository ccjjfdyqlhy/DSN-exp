# -*- coding: utf-8 -*-
"""dsn_study system prompt 组装（阶段 1）。

背景：旧实现在 boot 时把 `DEFAULT_SYSTEM_PROMPT` 与各技能指令拼成**死字符串**，
之后永不重建 → 两个问题：
  1. 禁用一个技能，它的指令文本仍留在 prompt 里（工具没了，说明还在）；
  2. 人格 / 学习上下文没有插槽，无法逐轮变化。

新实现基于 `harness/prompts/engine.py`（片段 + 占位符渲染器），逐轮重建。
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="module")
def study_app(tmp_path_factory):
    db = tmp_path_factory.mktemp("study") / "qb.db"
    os.environ["QUESTION_BANK_DB_PATH"] = str(db)
    os.environ["LOG_DIR"] = str(tmp_path_factory.mktemp("logs"))
    os.environ["TTS_AUTOSTART"] = "false"
    os.environ["TTS_WARMUP"] = "false"
    os.environ["MCP_ENABLED"] = "false"
    from apps.dsn_study import boot
    boot.create_application()
    return boot.engine


# ── 片段与组装 ──

def test_builder_assembles_fragments(study_app):
    builder = study_app.prompt_builder
    assert builder is not None, "未装配 StudyPromptBuilder"
    titles = [f.title for f in builder._engine.get_enabled()]
    assert "身份" in titles and "技能" in titles


def test_prompt_contains_identity_and_skills(study_app):
    prompt = study_app.prompt_builder.build()
    assert "你是一名专业的AI学习助手" in prompt
    assert "record_study_session" in prompt, "技能指令应进入 system prompt"


def test_prompt_has_no_unrendered_placeholders(study_app):
    """占位符必须全部被渲染掉（否则模型会看到裸的 {personality}）。"""
    prompt = study_app.prompt_builder.build()
    for token in ("{personality}", "{user_context}", "{skills}"):
        assert token not in prompt, "占位符未渲染: %s" % token


def test_disabled_skill_prompt_disappears(study_app):
    """核心修复：禁用技能后，它的指令文本必须从 prompt 里消失。

    旧实现把 prompt 在 boot 时拼死，禁用技能只摘工具 schema，
    指令文本永久残留 —— 模型仍会按已停用的技能说明行事。
    """
    registry = study_app.skill_registry
    builder = study_app.prompt_builder
    before = builder.build()
    assert "record_study_session" in before

    registry.unregister_skill("study_tracking")
    try:
        after = builder.build()
        assert "record_study_session" not in after, \
            "禁用技能后其指令文本仍留在 prompt 里"
        assert len(after) < len(before), "prompt 未随禁用而缩短"
        # 其他技能的指令不受影响
        assert "generate_daily_plan" in after
    finally:
        # 恢复（模块级 fixture，后续用例仍能看到该技能）
        study_app.skill_manager.enable("study_tracking")


def test_user_context_renderer_is_used(study_app):
    """{user_context} 插槽：begin_turn 提供的上下文必须进 prompt。"""
    builder = study_app.prompt_builder
    builder.begin_turn(1, "(系统上下文·仅供你参考，不要复述) [错题本] 累计 42 道错题待巩固")
    try:
        prompt = builder.build()
        assert "[错题本] 累计 42 道错题待巩固" in prompt
    finally:
        builder.begin_turn(1, "")


def test_personality_provider_slot(study_app):
    """{personality} 插槽：注册提供器后其内容进 prompt。"""
    builder = study_app.prompt_builder
    builder.set_personality_provider(lambda uid: "## 角色设定\n你是小舟，一个耐心的学习学长。")
    try:
        builder.begin_turn(1, "")
        prompt = builder.build()
        assert "## 角色设定" in prompt
        assert "小舟" in prompt
    finally:
        builder.set_personality_provider(None)
        builder.begin_turn(1, "")


def test_personality_provider_failure_degrades(study_app):
    """人格提供器抛异常 → 降级为空，绝不让整轮对话失败。"""
    builder = study_app.prompt_builder

    def boom(uid):
        raise RuntimeError("人格服务挂了")

    builder.set_personality_provider(boom)
    try:
        builder.begin_turn(1, "")
        prompt = builder.build()
        assert "你是一名专业的AI学习助手" in prompt, "人格失败不应影响身份片段"
    finally:
        builder.set_personality_provider(None)
        builder.begin_turn(1, "")


# ── 基座：per-call system prompt ──

def test_agent_runtime_accepts_per_call_system_prompt(study_app):
    """AgentRuntime 必须支持按调用覆盖 system prompt（人格按 uid 变）。"""
    import inspect
    sig = inspect.signature(study_app.agent.run_with_tools)
    assert "system_prompt" in sig.parameters
