# tests/test_dsn_study_boot.py
# dsn_study 装配与端点冒烟测试（不依赖真实 LLM）。

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest


@pytest.fixture(scope="module")
def study_app():
    os.environ["QUESTION_BANK_DB_PATH"] = tempfile.mkdtemp(prefix="dsn_study_test_") + "/qb.db"
    from apps.dsn_study.boot import create_application
    return create_application()


@pytest.fixture(scope="module")
def study_engine(study_app):
    return study_app.config["ENGINE"]


@pytest.fixture()
def client(study_app):
    return study_app.test_client()


# ── 装配 ──

def test_boot_assembles_skills_and_tools(study_engine):
    tools = study_engine.skill_registry.list_active_tools()
    assert len(tools) >= 40
    # 关键学习域工具在位
    for expected in ("question_bank.create_question", "exam_sim.create_exam",
                     "knowledge_graph.update_knowledge_state", "plan.create_goal",
                     "exam_review.get_exam_history"):
        assert expected in tools, f"缺少工具: {expected}"
    # AgentLoop 工具注册表同步
    assert len(study_engine.agent.tools) >= 40


def test_boot_mounts_routes(client):
    rv = client.get("/api/plan/goals")
    assert rv.status_code == 200
    assert "goals" in rv.get_json()


# ── 题库（type_name JOIN 修复验证） ──

def _mk_question(engine, content, answer="A", difficulty=2):
    """经 AI 面工具建题（subject/type 解析走模板管理器）。"""
    out = engine.skill_registry.call_tool("question_bank", "create_question", {
        "subject": "math", "content": content, "answer": answer,
        "type_name": "选择题", "difficulty": difficulty,
        "options": ["A", "B", "C", "D"],
    })
    assert out.get("success"), out
    return out["question_id"]


def test_question_store_crud_with_type_name(study_engine):
    store = study_engine.question_store
    qid = _mk_question(study_engine, "1+1=?")
    q = store.get_question(qid)
    assert q["type_name"] == "选择题"  # LEFT JOIN question_types 生效
    found = store.find_by_content("1+1=?", subject="math")
    assert found and found["type_name"] == "选择题"
    assert store.search_questions(subject="math", limit=5)


# ── 组卷 ──

def test_composer_composes(study_engine):
    from apps.dsn_study.question_bank.composer import ComposeParams
    for i in range(6):
        _mk_question(study_engine, f"组卷测试题{i}")
    result = study_engine.composer.compose(ComposeParams(subject="math", count=5))
    assert result["success"]
    assert len(result["questions"]) == 5


# ── 模考（scorer 注入 + exact 判分，无 LLM） ──

def test_exam_engine_scores_without_llm(study_engine):
    engine = study_engine.exam_engine
    session = engine.create_session(1, {"subject": "math", "total_count": 3,
                                        "time_limit_min": 5})
    started = engine.start_session(session["session_id"])
    assert started["success"], started
    questions = started["questions"]
    assert len(questions) == 3

    # 全部答对（选择题走 exact 判分，不触发 LLM）
    for idx, q in enumerate(questions):
        assert engine.submit_answer(session["session_id"], idx, q["answer"])["success"]

    result = engine.submit_session(session["session_id"])
    assert result["score"] == result["max_score"] == 3
    # 判分结果落库
    results = study_engine.question_store.get_exam_results(user_id=1)
    assert results and results[0]["score"] == 3


# ── 计划闭环 ──

def test_plan_roundtrip(client):
    rv = client.post("/api/plan/goals", json={"title": "测试目标"})
    assert rv.status_code == 200
    gid = rv.get_json()["goal_id"]
    rv = client.post("/api/plan/phases",
                     json={"goal_id": gid, "title": "阶段一",
                           "start_date": "2026-01-01", "end_date": "2026-12-31"})
    assert rv.status_code == 200
    today = client.get("/api/plan/today").get_json()
    assert today["total"] >= 1


# ── 学习时间表闭环 ──

def test_timetable_roundtrip(client):
    rv = client.post("/api/study/timetable/slots",
                     json={"day_of_week": 1, "start_time": "08:00",
                           "end_time": "10:00", "subject": "物理"})
    assert rv.status_code == 201
    slots = client.get("/api/study/timetable/slots").get_json()
    assert any(s["subject"] == "物理" for s in slots["slots"])


# ── Agent 工具桥接（不经 LLM 直接执行工具） ──

def test_bridged_tool_executes(study_engine):
    tool = study_engine.agent.tools.get("question_bank.get_subjects")
    assert tool is not None
    result = tool.run()
    assert result.success, result.error


def test_plan_tool_via_registry(study_engine):
    out = study_engine.skill_registry.call_tool(
        "plan", "create_goal", {"title": "工具桥接目标"})
    assert out["success"] and out["goal_id"]


def test_timetable_tool_via_registry(study_engine):
    out = study_engine.skill_registry.call_tool("study_timetable", "check_in",
                                                {"subject": "数学"})
    assert out["success"] and out["session_id"]
    out = study_engine.skill_registry.call_tool("study_timetable", "check_out", {})
    assert out["success"] and out["duration_min"] >= 0
    stats = study_engine.skill_registry.call_tool("study_timetable", "get_stats", {})
    assert stats["success"] and "weekly" in stats


# ── 对话端点（打桩 chat client） ──

class _StubResponse:
    def __init__(self, content, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []
        self.reasoning_content = None


class _StubClient:
    """单轮回复的假聊天客户端。"""

    def __init__(self, content="好的，已收到。"):
        self.content = content
        self.last_messages = None

    def invoke(self, messages, tools=None, **kwargs):
        self.last_messages = messages
        return _StubResponse(self.content)


def test_chat_endpoint_with_stub(study_app, study_engine, monkeypatch):
    stub = _StubClient("测试回复")
    study_engine.agent.chat_client = stub
    rv = study_app.test_client().post("/api/chat/send", json={"message": "你好"})
    assert rv.status_code == 200
    assert rv.get_json()["reply"] == "测试回复"


class _ToolCallScriptClient:
    """脚本化假客户端：第 1 轮发起工具调用，第 2 轮给最终回复。

    验证 AgentLoop 完整闭环：模型发起 tool call → harness 执行注册的
    技能工具 → 结果回喂 → 模型总结。
    """

    def __init__(self, tool_name, arguments, final_text):
        self.calls = [(
            {"id": "call_1", "name": tool_name, "arguments": arguments},
            final_text,
        )]
        self.round = 0
        self.seen_messages = []

    def invoke(self, messages, tools=None, **kwargs):
        from harness.models import ToolCall
        self.seen_messages = list(messages)
        call, final = self.calls[min(self.round, len(self.calls) - 1)]
        self.round += 1
        if self.round == 1:
            tc = ToolCall(id=call["id"], name=call["name"],
                          arguments=call["arguments"])
            return _StubResponse("", tool_calls=[tc])
        return _StubResponse(final)


def test_agent_loop_tool_roundtrip(study_engine):
    from apps.dsn_study.engine_support import LLMService  # noqa: F401  确认可导入

    script = _ToolCallScriptClient(
        tool_name="plan__create_goal",  # wire 名（点号编码）
        arguments={"title": "AgentLoop 闭环目标"},
        final_text="已为你创建目标。",
    )
    study_engine.agent.chat_client = script
    try:
        reply = study_engine.chat("帮我创建一个目标：AgentLoop 闭环目标", user_id=1)
    finally:
        study_engine.agent.chat_client = study_engine.chat_client

    assert reply == "已为你创建目标。"
    goals = study_engine.plan_engine._store.list_goals(1)
    assert any(g.title == "AgentLoop 闭环目标" for g in goals)
