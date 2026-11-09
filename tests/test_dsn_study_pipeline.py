# -*- coding: utf-8 -*-
"""dsn_study 对话管线（阶段 3）—— harness/pipeline 迁移。

迁移前：能力内联在 chat_hooks.py 的 pre_process/post_process + boot.py 的
StudyEngine.chat 里，靠 if/else 串起来。
迁移后：每个能力一个 Plugin，挂在 harness/pipeline 的钩子上。
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


# ── 插件存在与钩子分配 ──

def test_pipeline_plugins_registered(study_app):
    runner = study_app.pipeline_runner
    assert runner is not None, "管线运行器未装配"
    names = {p["name"] if isinstance(p, dict) else p.name
             for p in runner.pm.list_plugins()}
    for expected in ("study_system_prompt", "study_vision_context",
                     "study_exam_session", "study_daily_report",
                     "study_complexity", "study_plan_check",
                     "study_model_invoke", "study_memory_record",
                     "study_personality_feedback", "study_tts"):
        assert expected in names, "缺少插件: %s" % expected


def test_plugin_hooks_are_correct():
    """钩子分配必须符合语义，否则上下文会串到错误阶段。"""
    from harness.pipeline.base import HookPoint
    from apps.dsn_study.pipeline.plugins import (
        VisionContextPlugin, ExamSessionPlugin, DailyReportPlugin,
        ComplexityPlugin, ModelInvokePlugin, PlanCheckPlugin,
        SystemPromptPlugin, MemoryRecordPlugin,
        PersonalityFeedbackPlugin, TTSPlugin,
    )
    assert VisionContextPlugin().hooks == [HookPoint.PRE_PROCESS]
    assert ExamSessionPlugin().hooks == [HookPoint.PRE_PROCESS]
    assert DailyReportPlugin().hooks == [HookPoint.PRE_PROCESS]
    assert ComplexityPlugin().hooks == [HookPoint.PRE_PROCESS]
    assert ModelInvokePlugin().hooks == [HookPoint.MODEL_INVOKE]
    assert PlanCheckPlugin().hooks == [HookPoint.POST_PROCESS]
    assert SystemPromptPlugin().hooks == [HookPoint.PREPARE]
    assert MemoryRecordPlugin().hooks == [HookPoint.POST_PROCESS]
    assert PersonalityFeedbackPlugin().hooks == [HookPoint.POST_PROCESS]
    assert TTSPlugin().hooks == [HookPoint.POST_TTS]


def test_plugin_priority_is_ascending_semantics():
    """插件 priority 是**升序**（值小者先执行）—— 与技能提示词相反。"""
    from harness.pipeline.base import HookPoint
    from apps.dsn_study.pipeline.plugins import (
        VisionContextPlugin, ExamSessionPlugin, DailyReportPlugin,
        ComplexityPlugin,
    )
    # PRE_PROCESS 内部：视觉 → 考试 → 日终报告 → 复杂度
    order = [VisionContextPlugin().priority, ExamSessionPlugin().priority,
             DailyReportPlugin().priority, ComplexityPlugin().priority]
    assert order == sorted(order), order


def test_plugins_do_not_rely_on_on_load():
    """on_load/on_unload 全仓零调用 —— 初始化必须放 __init__。"""
    import inspect
    from apps.dsn_study.pipeline import plugins as pl
    src = inspect.getsource(pl)
    assert "def on_load" not in src, "插件不应依赖 on_load（基座不会调用）"


# ── 运行器 ──

def test_runner_runs_context():
    """管线能跑完并返回 Context。"""
    from harness.pipeline.base import Context, HookPoint
    from apps.dsn_study.pipeline import StudyPipelineRunner

    runner = StudyPipelineRunner(plugins=[])
    runner.start()
    try:
        ctx = Context(message="你好")
        out = runner.run(ctx)
        assert out is not None
        timing = (out.extra or {}).get("_pipeline_timing") or {}
        assert "total_ms" in timing, timing
    finally:
        runner.stop()


def test_runner_isolates_plugin_exception():
    """插件抛异常 → 不炸管线，异常被隔离。"""
    from harness.pipeline.base import Context, HookPoint, Plugin
    from apps.dsn_study.pipeline import StudyPipelineRunner

    class _Boom(Plugin):
        name = "boom"
        hooks = [HookPoint.PRE_PROCESS]
        priority = 1

        def on_hook(self, hook, ctx):
            raise RuntimeError("插件炸了")

    class _Ok(Plugin):
        name = "ok"
        hooks = [HookPoint.PRE_PROCESS]
        priority = 2

        def on_hook(self, hook, ctx):
            ctx.message = ctx.message + " [ok]"
            return ctx

    runner = StudyPipelineRunner(plugins=[_Boom(), _Ok()])
    runner.start()
    try:
        out = runner.run(Context(message="hi"))
        assert " [ok]" in out.message, "异常插件之后的插件仍应执行"
    finally:
        runner.stop()


# ── 兼容门面 ──

def test_chat_hooks_facade_still_works(study_app):
    """老调用方仍可用 chat_hooks（门面转调插件）。"""
    hooks = study_app.chat_hooks
    assert hooks is not None
    assert hasattr(hooks, "pre_process")
    assert hasattr(hooks, "post_process")


def test_plan_check_via_facade(study_app):
    hooks = study_app.chat_hooks
    eng = study_app.plan_engine
    tasks = eng.generate_daily_plan(1)
    if not tasks:
        goal = eng.create_goal(1, "管线测试目标", "单元测试")
        eng.add_phase(goal.goal_id, "第一阶段")
        tasks = eng.generate_daily_plan(1)
    assert tasks, "生成不出日计划"
    task_id = tasks[0].task_id
    payload = '{"task_id": "%s", "action": "done"}' % task_id
    reply = "好的。<plan_check>%s</plan_check>" % payload
    cleaned, results = hooks.post_process(reply)
    assert "<plan_check>" not in cleaned
    assert results and results[0]["success"], results


def test_chat_hooks_and_pipeline_use_same_plugin_logic(study_app):
    """门面与管线必须走同一份逻辑（不能各写一套）。"""
    from apps.dsn_study.pipeline.plugins import (
        ExamSessionPlugin, PlanCheckPlugin, DailyReportPlugin,
    )
    hooks = study_app.chat_hooks
    assert isinstance(hooks._exam, ExamSessionPlugin)
    assert isinstance(hooks._plan_check, PlanCheckPlugin)
    assert isinstance(hooks._report, DailyReportPlugin)
