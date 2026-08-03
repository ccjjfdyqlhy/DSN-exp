# tests/test_question_print.py
# 出题打印技能 — 单元测试（不触发真实打印）

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def _load_tool():
    from skills.loader import SkillLoader
    from skills.registry import SkillRegistry
    loader = SkillLoader()
    skill = loader.load('skills/builtin/question_print')
    reg = SkillRegistry()
    reg.register_skill(skill)
    return reg._tool_instances['question_print.print_paper']


def _mk_store(tmp_path):
    from db.question_bank import QuestionBankDBManager
    from question_bank.store import QuestionStore
    from question_bank.template_manager import SubjectTemplateManager
    db = QuestionBankDBManager(db_path=str(tmp_path / "qb.db"))
    tm = SubjectTemplateManager(db=db)
    tm.init_builtin_templates()
    if not tm.has_subjects():
        tm.apply_template("6_subjects")
    store = QuestionStore(db=db)
    subj = tm.get_subject_by_code("math")
    type_id = tm.get_type_id("解答题", "计算")
    store.create_question({
        "subject_id": subj["subject_id"], "type_id": type_id,
        "difficulty": 2, "content": "计算: 2x+3=7",
        "answer": "x=2", "explanation": "移项得 x=2",
    })
    return store


def test_tool_loads():
    tool = _load_tool()
    assert hasattr(tool, "print_paper")
    assert hasattr(tool, "_build_html")


def test_render_pdf_empty_bank(tmp_path):
    """题库无题时组卷应返回错误提示"""
    tool = _load_tool()
    tool._store = _mk_store(tmp_path)
    # 用不存在的学科触发空题库
    res = tool.print_paper(subject="no_such_subj", count=5, user_id=1)
    assert res.get("success") is False
    assert "没有可用题目" in res.get("error", "")


def test_print_paper_composes_from_bank(tmp_path):
    tool = _load_tool()
    tool._store = _mk_store(tmp_path)
    res = tool.print_paper(subject="math", count=1, include_answer=True,
                           user_id=1)
    assert res.get("success") is True
    assert res.get("question_count") == 1
    assert res.get("pdf_path") and os.path.isfile(res["pdf_path"])
    # 打印结果应为 dict（不要求成功，环境可能无打印机）
    assert isinstance(res.get("print"), dict)


def test_print_paper_uses_provided_questions(tmp_path):
    tool = _load_tool()
    qs = [
        {"content": "1+1=?", "options": ["A. 1", "B. 2"],
         "answer": "B", "explanation": "1+1=2", "type_name": "选择题"},
    ]
    res = tool.print_paper(subject="math", questions=qs,
                           include_answer=True, user_id=1)
    assert res.get("success") is True
    assert res.get("question_count") == 1
    assert res.get("pdf_path") and os.path.isfile(res["pdf_path"])


def test_build_html_escapes():
    tool = _load_tool()
    qs = [{"content": "a<b>c & d", "options": [], "answer": "x",
           "explanation": "<script>"}]
    html = tool._build_html(qs, "math", "T", include_answer=True)
    assert "&lt;b&gt;" in html
    assert "&lt;script&gt;" in html
