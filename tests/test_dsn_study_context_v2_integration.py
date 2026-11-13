# -*- coding: utf-8 -*-
"""dsn_study 上下文内核 v2 + 人格内核的**端到端接线**测试。

前面那些测试各自验证一个零件（budget 裁剪、signals 规则、store 幂等）；
这里验证的是**装起来之后是不是真的在干活**：

  * 一轮对话 → 轮次落进 ``context_turns``；
  * 第二轮的上下文里**能看到第一轮的话**（tail 来源真的接上了）；
  * 人格段落进了 system prompt；
  * 规则路径的人格回写**真的推进了状态**（交互计数 + 亲密度）；
  * 学习上下文由内核产出（一条路径，不是旧的四个 preamble 拼的）。
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="module")
def study_app(tmp_path_factory):
    db = tmp_path_factory.mktemp("study_v2") / "qb.db"
    os.environ["QUESTION_BANK_DB_PATH"] = str(db)
    os.environ["LOG_DIR"] = str(tmp_path_factory.mktemp("logs_v2"))
    os.environ["TASK_MANAGER_ENABLED"] = "true"
    os.environ["TTS_AUTOSTART"] = "false"
    os.environ["TTS_WARMUP"] = "false"
    from apps.dsn_study import boot
    boot.create_application()
    return boot.engine


class _StubClient:
    """最小桩客户端：够 AgentLoop 跑完一轮。"""

    def __init__(self, content="好的，我们一步步看。"):
        self.content = content
        self.model = "stub"
        self.calls = []

    def invoke(self, messages, tools=None, **kwargs):
        from infra.orchestrator.base import ChatResponse
        self.calls.append(messages)
        return ChatResponse(content=self.content, model="stub")

    def stream(self, messages, **kwargs):
        async def _gen():
            yield self.content
        return _gen()


@pytest.fixture
def stub_agent(study_app):
    """把主模型换成桩（不触网），并把轮次计数清零。"""
    original = study_app.agent.chat_client
    stub = _StubClient()
    study_app.agent.chat_client = stub
    try:
        yield stub
    finally:
        study_app.agent.chat_client = original


# ── 1) 接线 ──────────────────────────────────────────────────────

def test_engine_wires_new_kernels(study_app):
    """引擎接上了上下文内核与人格薄层。"""
    assert getattr(study_app, "context_kernel", None) is not None, "上下文内核未装配"
    assert getattr(study_app, "persona_engine", None) is not None, "人格薄层未装配"
    assert getattr(study_app, "persona_compat", None) is not None, "人格兼容门面未装配"


def test_feature_gate_is_runtime_evaluable():
    """开关层必须运行时求值（不是 import 期快照）。"""
    from apps.dsn_study import gating
    os.environ["DSN_FLAG_CONTEXT_ENGINE"] = "v9"
    try:
        assert gating.flag("context_engine", "v1") == "v9"
        assert gating.enabled("__不存在的开关__", True) is True
    finally:
        os.environ.pop("DSN_FLAG_CONTEXT_ENGINE", None)


# ── 2) 轮次落库 + tail 回灌 ──────────────────────────────────────

def test_turn_is_recorded_into_context_table(study_app, stub_agent):
    """一轮对话 → ``context_turns`` 有一行。"""
    from apps.dsn_study.context import ContextStore

    store = ContextStore(study_app.db_mgr)
    session = "v2-test-session"
    before = store.count_turns(1, session)

    study_app.chat("第一轮：请讲讲二次函数", user_id=1, session_id=session)

    after = store.count_turns(1, session)
    assert after == before + 1, "轮次没有落进 context_turns"

    rows = store.recent_turns(1, session, limit=5)
    assert rows, "取不到刚写入的轮次"
    assert "二次函数" in (rows[-1].get("user_msg") or "")


def test_second_turn_sees_first_turn(study_app, stub_agent):
    """第二轮的上下文里能看到第一轮的话 —— tail 来源真的接上了。"""
    session = "v2-test-tail"
    study_app.chat("第一轮：什么是导数", user_id=1, session_id=session)
    ctx_text = study_app._learning_context(1, session_key=session,
                                            message="第二轮", round_index=2)
    assert "什么是导数" in ctx_text, \
        "第二轮上下文里没有第一轮的话:\n%s" % ctx_text[:600]


# ── 3) 人格 ──────────────────────────────────────────────────────

def test_persona_block_in_system_prompt(study_app, stub_agent):
    """人格段落进了 system prompt（红线 R5）。"""
    prompt = study_app.prompt_builder.build(uid=1)
    assert "## 角色设定" in prompt, prompt[:400]
    assert "小舟" in prompt, prompt[:400]


def test_rule_based_feedback_advances_state(study_app, stub_agent):
    """规则路径的人格回写**真的推进状态**（红线 R7），且不触网。"""
    from apps.dsn_study.persona import PersonaEngine

    engine = study_app.persona_engine
    assert isinstance(engine, PersonaEngine)
    assert engine.use_llm_judge is False, "默认必须是规则路径（零 LLM、零排队）"

    facade = study_app.persona_compat
    before = facade.get_personality_status(1)
    b_n = int(before.get("total_interactions") or 0)
    b_aff = float(before.get("affinity_value") or 0.0)

    study_app.chat("太棒了，这道题终于搞懂了，谢谢！", user_id=1,
                   session_id="v2-test-persona")

    after = facade.get_personality_status(1)
    a_n = int(after.get("total_interactions") or 0)
    a_aff = float(after.get("affinity_value") or 0.0)
    assert a_n > b_n, "交互计数没有增加（人格回写没跑）"
    assert a_aff != b_aff, "亲密度没有变化"


# ── 4) 上下文来源 ────────────────────────────────────────────────

def test_learning_context_has_kernel_shape(study_app, stub_agent):
    """学习上下文由内核产出：统一前缀 + 分块标签。"""
    session = "v2-shape"
    study_app.chat("先来一题：求导", user_id=1, session_id=session)
    ctx_text = study_app._learning_context(1, session_key=session,
                                            message="你好", round_index=2)
    assert ctx_text, "有历史却没有任何上下文"
    assert "供你参考" in ctx_text or "最近对话" in ctx_text, ctx_text[:400]
    # 统一前缀只出现一次（旧的实现会出现 2~3 次）
    assert ctx_text.count("系统上下文") <= 1, ctx_text[:400]


def test_context_trace_records_sources(study_app):
    """每次组装都产出 trace（可观测）。"""
    kernel = study_app.context_kernel
    from apps.dsn_study.context import TurnContext
    turn = TurnContext(uid=1, session_id="v2-trace", message="hi", round_index=1)
    trace = kernel.build(turn)
    assert trace is not None
    assert hasattr(trace, "blocks")
    assert hasattr(trace, "total_chars")
    assert hasattr(trace, "degraded")
