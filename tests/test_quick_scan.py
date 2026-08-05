# tests/test_quick_scan.py
# 快速扫题 API 测试 — 题目 JSON 解析 + VLM 提取入库 + 批量汇总一次反馈

import os
import sys
import tempfile
import time
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.scan import _parse_questions, _extract_and_store, _build_batch_message
from db.question_bank import QuestionBankDBManager
from question_bank.store import QuestionStore
from question_bank.template_manager import SubjectTemplateManager
from async_task_store import AsyncTaskStore


class _FakeEngine:
    def __init__(self, store, tm):
        self.question_store = store
        self.template_manager = tm
        self.pipeline = None


class _FakePipeline:
    async def process(self, ctx):
        class _R:
            reply = "共扫了2张，识别3题已全部入库。"
            original_reply = "共扫了2张，识别3题已全部入库。"
            chat_id = ctx.chat_id
            audio_b64 = ""
            tts_error = ""
            filtered = False
            extra = {}
        return _R()


def _make_qb():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    qb = QuestionBankDBManager(db_path=tmp.name)
    tm = SubjectTemplateManager(db=qb)
    tm.init_builtin_templates()
    if not tm.has_subjects():
        tm.apply_template("6_subjects")
    store = QuestionStore(db=qb)
    return tmp.name, qb, store, tm


def _patch_vision(raw_response):
    import models.clients as mc
    orig = mc.VisionModel.ask
    mc.VisionModel.ask = classmethod(lambda cls, data_url, prompt="", max_tokens=2048,
                                     temperature=0.1, extra_body=None: raw_response)
    return orig


def test_parse_questions():
    print("=== _parse_questions 解析 ===")
    assert _parse_questions('[{"content":"1+1="}]')[0]["content"] == "1+1="
    raw = '```json\n[{"content":"x"}]\n```'
    assert _parse_questions(raw)[0]["content"] == "x"
    assert _parse_questions('{"content":"y"}')[0]["content"] == "y"
    assert _parse_questions("不是json") == []
    print("  PASSED")


def test_extract_and_store():
    print("=== VLM 提取入库(标签/科目/题图) ===")
    path, qb, store, tm = _make_qb()
    orig = _patch_vision(
        '[{"content":"1+1等于几？","type_name":"填空题","subtype":"填空","difficulty":1,'
        '"answer":"2","subject":"数学","tags":["加法","口算"],"figure_description":"一个苹果图"},'
        '{"content":"选出正确项","type_name":"选择题","subtype":"单选",'
        '"options":["A","B"],"answer":"A","subject":"math","tags":["选择"],'
        '"figure_description":""}]'
    )
    try:
        engine = _FakeEngine(store, tm)
        result = _extract_and_store(engine, "data:image/jpeg;base64,AAAA", "math")
        assert result["questions_found"] == 2, result
        assert result["questions_added"] == 2, result
        assert len(result["added_ids"]) == 2
        assert len(result["added"]) == 2 and result["added"][0]["id"] > 0
        q1 = store.get_question(result["added_ids"][0])
        assert q1["content"] == "1+1等于几？"
        assert q1["source"] == "quick_scan"
        # 科目判定: "数学" → math 的 subject_id
        assert q1["subject_id"] == tm.get_subject_by_code("math")["subject_id"]
        # 标签已入库
        assert q1["tags"] == ["加法", "口算"]
        # 题图描述存到 metadata
        assert q1["metadata"].get("figure_description") == "一个苹果图"
        # 无配图题目 metadata 不含 figure_description
        q2 = store.get_question(result["added_ids"][1])
        assert "figure_description" not in (q2["metadata"] or {})
        assert "数学" in result["subjects"]
    finally:
        mc = sys.modules.get("models.clients")
        if mc is not None:
            mc.VisionModel.ask = orig
        qb.close_connection()
        os.unlink(path)
    print("  PASSED")


def test_build_batch_message():
    print("=== 整批结果汇总消息 ===")
    msg = _build_batch_message(
        [{"questions_found": 2, "questions_added": 2, "subject_code": "math",
          "subjects": ["数学"],
          "added": [{"id": 1, "content": "题目A"}, {"id": 2, "content": "题目B"}]},
         {"questions_found": 1, "questions_added": 0, "subject_code": "math",
          "subjects": ["物理"], "added": []}],
        ["第3张识别失败"],
    )
    assert "共计识别 3 题" in msg
    assert "成功入库 2 题" in msg
    assert "第1张照片" in msg and "第2张照片" in msg
    assert "科目: 数学" in msg and "科目: 物理" in msg
    assert "失败照片: 1 张" in msg
    print("  PASSED")


class _FakeAuth:
    def authenticate(self, request):
        return {"uid": 1, "nickname": "u"}


def test_finish_batch():
    print("=== 批量扫题: 全部入库后一次汇总 ===")
    import api.scan as scan_mod
    from flask import Flask
    from db.chat import ChatDBManager

    path, qb, store, tm = _make_qb()

    class _RecPipeline:
        messages = []

        async def process(self, ctx):
            _RecPipeline.messages.append(ctx.message)
            class _R:
                reply = "共扫了2张，识别3题已全部入库。"
                original_reply = "共扫了2张，识别3题已全部入库。"
                chat_id = ctx.chat_id
                audio_b64 = ""
                tts_error = ""
                filtered = False
                extra = {}
            return _R()

    try:
        cdb = ChatDBManager(db_path=os.path.join(tempfile.mkdtemp(), "chat.db"))
        engine = _FakeEngine(store, tm)
        engine.pipeline = _RecPipeline()
        engine.async_task_store = AsyncTaskStore(db=cdb)
        engine.db = cdb

        orig_extract = scan_mod._extract_and_store
        orig_auth = scan_mod._auth_manager
        scan_mod._batches.clear()

        def fake_extract(engine, image_data, subject_code):
            return {"questions_found": 1, "questions_added": 1,
                    "added": [{"id": 1, "content": f"题目{image_data}"}],
                    "added_ids": [1], "subject_code": "math", "errors": []}

        scan_mod._extract_and_store = fake_extract
        scan_mod._auth_manager = _FakeAuth()

        app = Flask(__name__)
        app.config["ENGINE"] = engine
        app.register_blueprint(scan_mod.scan_bp)
        test = app.test_client()

        r1 = test.post("/api/scan/quick", json={"image_data": "A", "chat_id": 0})
        r2 = test.post("/api/scan/quick", json={"image_data": "B", "chat_id": 0})
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json["batch_id"] == r2.json["batch_id"]

        time.sleep(0.5)
        assert _RecPipeline.messages == [], "未 finish 前不应调用主模型"

        fr = test.post("/api/scan/finish", json={"chat_id": 0})
        assert fr.status_code == 200
        assert fr.json["count"] == 2
        task_id = fr.json["task_id"]

        deadline = time.time() + 15
        rec = None
        while time.time() < deadline:
            rec = engine.async_task_store.lookup(task_id)
            if rec and rec.get("status") == "done":
                break
            time.sleep(0.1)
        assert rec and rec["status"] == "done", rec
        assert "扫了2张" in (rec.get("reply") or "")
        assert len(_RecPipeline.messages) == 1, "整批只调用一次主模型"
        assert "识别 2 题" in _RecPipeline.messages[0]

        # 结束后再拍照片 → 新批次
        scan_mod._batches.clear()
        r3 = test.post("/api/scan/quick", json={"image_data": "C", "chat_id": 0})
        assert r3.status_code == 200
    finally:
        scan_mod._extract_and_store = orig_extract
        scan_mod._auth_manager = orig_auth
        scan_mod._batches.clear()
        qb.close_connection()
        os.unlink(path)
    print("  PASSED")


if __name__ == "__main__":
    test_parse_questions()
    test_extract_and_store()
    test_build_batch_message()
    test_finish_batch()
