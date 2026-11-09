# -*- coding: utf-8 -*-
"""dsn_study 功能完整性测试 —— 对照参考实现 DSN-exp（study 分支）逐项验证。"""

from __future__ import annotations

import os
import re
import pathlib

import pytest


@pytest.fixture(scope="module")
def study_app(tmp_path_factory):
    """启动一个隔离的 dsn_study 应用实例。"""
    db = tmp_path_factory.mktemp("study") / "qb.db"
    os.environ["QUESTION_BANK_DB_PATH"] = str(db)
    os.environ["LOG_DIR"] = str(tmp_path_factory.mktemp("logs"))
    os.environ["TASK_MANAGER_ENABLED"] = "true"
    # 语音：测试不拉起真实 GPT-SoVITS（需 GPU + 分钟级加载）
    os.environ["TTS_AUTOSTART"] = "false"
    os.environ["TTS_WARMUP"] = "false"
    from apps.dsn_study import boot
    boot.create_application()
    return boot.engine


# ── 1. 技能系统 ──

def test_all_skills_loaded(study_app):
    tools = study_app.skill_registry.list_active_tools()
    skills = {k.split(".")[0] for k in tools}
    expected = {
        "batch_import", "batch", "doc_to_questions", "document", "exam_review",
        "exam_sim", "knowledge_graph", "plan", "quest_from_image",
        "question_bank", "question_print", "quick_question", "study_memory",
        "study_tasks", "study_timetable", "study_tracking", "text_extract",
    }
    assert expected <= skills, "缺失技能: %s" % (expected - skills)


def test_document_skill_tools_registered(study_app):
    tools = set(study_app.skill_registry.list_active_tools())
    for name in ("process_scan", "read_hmd", "describe_image",
                 "scan_import_questions", "process_answered_scan",
                 "scan", "print_file"):
        assert "document." + name in tools


# ── 2. 题库 ──

def test_question_bank_roundtrip(study_app):
    """走 AI 可调用路径（question_bank.create 工具）做一次真实入库。"""
    inst = study_app.skill_registry.get_tool_instances("question_bank")
    crud = [i for i in inst if type(i).__name__ == "QuestionCRUDTool"]
    assert crud, "QuestionCRUDTool 未实例化"
    created = crud[0].create(subject="math", content="求 1+1 的值",
                             answer="2", difficulty=2, type_name="填空题")
    assert created.get("success"), created
    qid = created.get("question_id")
    assert qid
    got = crud[0].get(question_id=qid)
    assert got.get("content") == "求 1+1 的值", got
    assert got.get("type_name"), "type_name 关联缺失（判分策略依赖它）"
    found = crud[0].search(subject="math", limit=5)
    assert any(f["question_id"] == qid for f in found)


def test_question_compose(study_app):
    from apps.dsn_study.question_bank.composer import ExamComposer, ComposeParams
    composer = ExamComposer(question_store=study_app.question_store)
    result = composer.compose(ComposeParams(subject="math", count=1))
    assert result.get("success"), result


# ── 3. 计划系统 ──

def test_plan_flow(study_app):
    eng = study_app.plan_engine
    goal = eng.create_goal(1, "测试目标", "单元测试")
    assert goal and goal.goal_id
    eng.add_phase(goal.goal_id, "第一阶段")
    tasks = eng.generate_daily_plan(1)
    assert tasks, "未生成日计划任务"
    task_id = tasks[0].task_id

    eng.check_off(task_id)
    summary = eng.daily_summary(1)
    assert summary["done"] >= 1
    assert any(t.get("task_id") == task_id for t in summary["tasks"]),         "daily_summary 必须带 task_id（<plan_check> 需要）"


# ── 4. 任务系统 ──

def test_task_tools_and_complexity(study_app):
    from apps.dsn_study.skills.builtin.study_tasks.tools.task_tools import TaskTools
    tools = TaskTools()
    tools.task_manager = study_app.task_manager
    tools.db = study_app.db_mgr
    from datetime import datetime, timedelta
    when = (datetime.now() + timedelta(hours=2)).isoformat(timespec="seconds")
    res = tools.create_reminder("测试提醒", when)
    tid = res.get("task_id")
    assert tid, res
    listed = tools.list_reminders()
    assert listed.get("reminders") is not None
    assert any(r.get("task_id") == tid for r in listed["reminders"]), listed
    tools.cancel_reminder(tid)

    comp = tools.analyze_complexity("请分析并证明这道关于复杂函数的证明题的解法原理")
    assert "score" in comp and "is_complex" in comp, comp


# ── 5.打卡 / 学习日志 ──

def test_checkin_and_studylog(study_app):
    from apps.dsn_study.skills.builtin.study_tracking.tools.tracking_tools import (
        StudyTrackingTools)
    tools = StudyTrackingTools(studylog=study_app.studylog,
                                checkin_store=study_app.checkin_store)
    rec = tools.record_checkin("单元测试打卡", user_id=1)
    assert rec.get("success"), rec
    assert rec.get("streak", 0) >= 1

    stats = tools.query_checkin_stats(user_id=1)
    assert stats.get("success") and stats.get("checked_in_today"), stats

    sess = tools.record_session("math", 45, "复习函数", user_id=1)
    assert sess.get("success"), sess
    report = tools.daily_report(user_id=1)
    assert report.get("success"), report
    assert "checkin" in report.get("report", {}), "每日报告缺打卡段"


def test_skill_dependencies_injected(study_app):
    """所有技能的运行时依赖必须真的注入到工具实例上。

    回归点：dep_map 的键必须与工具实例属性名一致，否则注入静默失效
    （曾出现 study_tracking 用 studylog/checkin_store，而工具属性是
    _studylog/_checkin，导致 AI 调用打卡直接报"未初始化"）。
    """
    checks = {
        "study_tracking": ("_studylog", "_checkin"),
        "document": ("_question_store", "_models"),
        "question_bank": ("_store", "_tm"),
        "knowledge_graph": ("_store", "_engine"),
        "exam_sim": ("_engine", "_scorer"),
    }
    for skill, attrs in checks.items():
        insts = study_app.skill_registry.get_tool_instances(skill)
        assert insts, "%s 技能未实例化" % skill
        for attr in attrs:
            # 同一技能下可能有多个工具类（document = scanner/printer/DocTools），
            # 只要承载该依赖的实例被注入即可。
            values = [getattr(i, attr, None) for i in insts]
            assert any(v is not None for v in values), \
                "%s 工具未注入依赖 %s" % (skill, attr)


# ── 6. document 技能 ──

def test_document_tools_reachable(study_app):
    inst = study_app.skill_registry.get_tool_instances("document")
    assert inst, "document 技能未实例化"
    doc_tools = [i for i in inst if type(i).__name__ == "DocTools"]
    assert doc_tools, "DocTools 缺失"
    assert callable(doc_tools[0].describe_image)
    assert callable(doc_tools[0].process_answered_scan)


# ── 7. batch ──

def test_batch_execute(study_app):
    from apps.dsn_study.skills.builtin.batch.tools.batch_tools import BatchTools
    tools = BatchTools()
    tools.task_manager = study_app.task_manager
    res = tools.batch_execute([
        {"action_type": "python", "content": "print(1+1)"},
    ])
    assert res.get("submitted") == 1, res
    assert res.get("tasks") and res["tasks"][0].get("task_id")


# ── 8. 对话钩子 ──

def test_plan_check_tag_writes_plan(study_app):
    hooks = study_app.chat_hooks
    tasks = study_app.plan_engine.generate_daily_plan(1)
    task_id = tasks[0].task_id
    payload = '{"task_id": "%s", "action": "done"}' % task_id
    reply = "好的，已经完成。<plan_check>%s</plan_check>" % payload
    cleaned, results = hooks.post_process(reply)
    assert "<plan_check>" not in cleaned
    assert results and results[0]["success"], results
    summary = study_app.plan_engine.daily_summary(1)
    assert summary["done"] >= 1


def test_exam_timeout_auto_submit(study_app):
    """考试会话超时 → 自动交卷（对齐参考实现 ExamSimPlugin）。"""
    hooks = study_app.chat_hooks
    # 先确保题库有题，否则 start_session 组卷失败、状态停在 configuring
    inst = study_app.skill_registry.get_tool_instances("question_bank")
    crud = [i for i in inst if type(i).__name__ == "QuestionCRUDTool"][0]
    crud.create(subject="math", content="超时测试题", answer="1", type_name="填空题")

    sess = study_app.exam_engine.create_session(1, {
        "subject": "math", "total_count": 1, "time_limit_min": 0,
    })
    sid = sess["session_id"]
    started = study_app.exam_engine.start_session(sid)
    assert started.get("success"), started
    ctx = hooks._exam_block(1, "继续做题")
    assert "自动交卷" in ctx or "考试报告" in ctx, ctx


def test_daily_report_after_22h(study_app):
    hooks = study_app.chat_hooks
    hooks._report_date = ""
    hooks._report_user = -1
    # 阶段 3：日终报告的实现已迁到 pipeline 插件（chat_hooks 只是门面），
    # 所以要 patch **插件模块**里的 datetime，而不是 chat_hooks 的。
    import apps.dsn_study.pipeline.plugins as pl
    orig = pl.datetime

    class _FakeDT(orig):
        @classmethod
        def now(cls, tz=None):
            import datetime as _d
            return _d.datetime.now().replace(hour=23, minute=30)

    pl.datetime = _FakeDT
    try:
        block = hooks._daily_report_block(1)
    finally:
        pl.datetime = orig
    assert "日终报告" in block, block


# ── 9. <tool> XML 协议 ──

def test_tagged_tool_adapter():
    from apps.dsn_study.tool_adapter import SkillTagToolCallAdapter
    from infra.models.base import ChatResponse

    adapter = SkillTagToolCallAdapter()
    text = ('好的，我来创建目标。<tool>'
            '{"skill": "plan", "tool": "create_goal", '
            '"params": {"title": "高考 130"}}</tool>')
    resp = ChatResponse(content=text)
    parsed = adapter.parse(resp)
    assert len(parsed.tool_calls) == 1, parsed
    call = parsed.tool_calls[0]
    assert call.name == "plan.create_goal", call.name
    assert call.arguments.get("title") == "高考 130"
    assert "<tool>" not in parsed.text


# ── 10. 完整对话回路（桩模型） ──

class _FakeClient:
    """桩模型：按脚本返回若干轮回复。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def invoke(self, messages, tools=None, **kwargs):
        from infra.models.base import ChatResponse, ToolCall
        self.calls.append(messages)
        if not self.script:
            return ChatResponse(content="（桩模型无更多脚本）")
        item = self.script.pop(0)
        if isinstance(item, tuple):
            content, calls = item
        else:
            content, calls = item, []
        return ChatResponse(
            content=content,
            tool_calls=[ToolCall(id="c%d" % i, name=n, arguments=a)
                        for i, (n, a) in enumerate(calls)],
        )


def test_full_chat_loop_with_native_tool_call(study_app, monkeypatch):
    """一次完整对话：原生工具调用 → 工具执行 → 收束回复。"""
    fake = _FakeClient([
        ("我来查一下题库。", [("question_bank.search_questions",
                            {"subject": "math", "limit": 3})]),
        ("题库里有 1 道相关题目。", []),
    ])
    monkeypatch.setattr(study_app.agent, "chat_client", fake)
    reply = study_app.chat("题库里有哪些数学题？", user_id=1)
    assert "题库" in reply, reply
    assert len(fake.calls) >= 2, "工具循环未执行第二轮"


def test_full_chat_loop_with_xml_tool_tag(study_app, monkeypatch):
    """一次完整对话：<tool> XML 标签协议 → 工具执行 → 收束回复。"""
    fake = _FakeClient([
        ('好的。<tool>{"skill": "plan", "tool": "list_goals", "params": {}}</tool>',
         []),
        ("当前有 1 个学习目标。", []),
    ])
    monkeypatch.setattr(study_app.agent, "chat_client", fake)
    reply = study_app.chat("我有哪些学习目标？", user_id=1)
    assert "目标" in reply, reply
    assert len(fake.calls) >= 2, "XML 标签工具调用未触发第二轮"


def test_chat_applies_plan_check_tag(study_app, monkeypatch):
    """模型回复里的 <plan_check> 应真正回写计划状态。"""
    tasks = study_app.plan_engine.generate_daily_plan(1)
    task_id = tasks[0].task_id
    payload = '{"task_id": "%s", "action": "done"}' % task_id
    fake = _FakeClient([
        ("已完成。<plan_check>%s</plan_check>" % payload, []),
    ])
    monkeypatch.setattr(study_app.agent, "chat_client", fake)
    reply = study_app.chat("今天这道题做完了", user_id=1)
    assert "<plan_check>" not in reply, "标签未从回复中移除"
    summary = study_app.plan_engine.daily_summary(1)
    assert summary["done"] >= 1, "plan_check 未回写计划"


def test_chat_injects_today_plan_context(study_app, monkeypatch):
    """今日计划应注入对话上下文（含 task_id 供 <plan_check> 引用）。"""
    study_app.plan_engine.generate_daily_plan(1)
    fake = _FakeClient([("好的", [])])
    monkeypatch.setattr(study_app.agent, "chat_client", fake)
    study_app.chat("今天要做什么？", user_id=1)
    sent = fake.calls[0]
    text = "".join(str(getattr(m, "content", "")) for m in sent)
    assert "今日计划" in text, text[:300]


# ── 11. 坏导入回归 ──

def test_no_broken_top_level_imports():
    """禁止出现指向参考实现顶层包的未加前缀 import。"""
    mods = {"config", "db", "models", "document", "question_bank",
            "knowledge_graph", "exam_sim", "memory", "skills", "utils",
            "plugins", "tracking", "semantic_cache", "tasks", "workspace",
            "engine_support", "bundles", "settings", "app", "entry"}
    root = pathlib.Path(__file__).resolve().parents[1] / "apps" / "dsn_study"
    bad = []
    for p in root.rglob("*.py"):
        if "__pycache__" in str(p):
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            m = re.match(r"\s*(?:from|import)\s+([A-Za-z_][\w]*)", line)
            if m and m.group(1) in mods:
                bad.append("%s:%d: %s" % (p, i, line.strip()))
    assert not bad, "未加前缀的 import:\n" + "\n".join(bad)
