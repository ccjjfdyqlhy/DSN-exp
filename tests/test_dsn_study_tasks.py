# tests/test_dsn_study_tasks.py
# dsn_study 任务管理器（apps/dsn_study/tasks.py）+ 提醒/闹钟/心跳 API 移植验收。
# 阶段 1（FEATURE_GAP.md）——不依赖真实 LLM。

import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from apps.dsn_study.db.question_bank import QuestionBankDBManager
from apps.dsn_study.tasks import TaskManager, TaskType, ComplexityAnalyzer
from apps.dsn_study.api import alarm as alarm_api


@pytest.fixture(scope="module")
def db():
    return QuestionBankDBManager(
        db_path=tempfile.mkdtemp(prefix="dsn_study_tasks_") + "/qb.db")


@pytest.fixture(scope="module")
def tm(db):
    manager = TaskManager(db, llm=None, max_workers=2)
    yield manager
    manager.shutdown()


def _wait_task(tm, task_id, timeout=5.0):
    """轮询等待任务离开 RUNNING/PENDING（线程池异步完成）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = tm.get_task(task_id)
        if task and task.status.value not in ("pending", "running"):
            return task
        time.sleep(0.05)
    return tm.get_task(task_id)


# ── TaskManager 基础 ──

def test_create_and_persist(tm, db):
    tid = tm.create_task(
        TaskType.REMINDER, user_id=1, chat_id=0,
        params={"text": "测试提醒"}, scheduled_time=datetime.now() + timedelta(hours=1))
    task = tm.get_task(tid)
    assert task is not None and task.status.value == "pending"
    row = db._get_connection().execute(
        "SELECT * FROM tasks WHERE task_id = ?", (tid,)).fetchone()
    assert row is not None
    assert json.loads(row["params"])["text"] == "测试提醒"


def test_past_reminder_executes_and_notifies(tm, db):
    """过期提醒立即执行 → COMPLETED + task_notifications 待投递记录。"""
    tid = tm.create_task(
        TaskType.REMINDER, user_id=1, chat_id=0,
        params={"text": "马上提醒"},
        scheduled_time=datetime.now() - timedelta(seconds=1))
    task = _wait_task(tm, tid)
    assert task.status.value == "completed", task.error

    notes = tm.fetch_pending_notifications(1)
    assert any(n["task_id"] == tid for n in notes)
    nid = notes[0]["notification_id"]
    tm.mark_notification_delivered(nid)
    assert all(n["notification_id"] != nid for n in tm.fetch_pending_notifications(1))


def test_habit_reschedules(tm):
    """HABIT 完成后自动排下一次（PENDING + 未来 scheduled_time）。"""
    tid = tm.create_task(
        TaskType.HABIT, user_id=1, chat_id=0,
        params={"text": "喝水"},
        scheduled_time=datetime.now() - timedelta(seconds=1),
        interval_seconds=3600)
    task = _wait_task(tm, tid)
    assert task.status.value == "pending"
    assert task.scheduled_time > datetime.now()


def test_reasoner_requires_llm(tm):
    tid = tm.create_task(
        TaskType.REASONER, user_id=1, chat_id=0,
        params={"question": "1+1"})
    tm.execute_task(tid)   # REASONER/ACTION 类不自动调度，与 dsn 原语义一致
    task = _wait_task(tm, tid)
    assert task.status.value == "failed"


def test_reasoner_with_fake_llm(db):
    class FakeLLM:
        def send_message(self, prompt):
            return "推理过程...\n结论：2"

    manager = TaskManager(db, llm=FakeLLM(), max_workers=1)
    try:
        tid = manager.create_task(
            TaskType.REASONER, user_id=1, chat_id=0, params={"question": "1+1"})
        manager.execute_task(tid)
        task = _wait_task(manager, tid)
        assert task.status.value == "completed"
        assert task.result["conclusion"] == "结论：2"
    finally:
        manager.shutdown()


def test_stopwatch_lifecycle(tm):
    uid = 42
    r = tm.start_stopwatch(uid, label="刷题")
    assert r["success"] and r["status"] == "running"
    time.sleep(0.1)
    r = tm.pause_stopwatch(uid)
    assert r["success"] and r["status"] == "paused"
    paused_elapsed = r["elapsed_seconds"]
    r = tm.resume_stopwatch(uid)
    assert r["success"] and r["status"] == "running"
    r = tm.delete_stopwatch(uid)
    assert r["success"]
    assert not tm.get_stopwatch(uid)["success"]


def test_complexity_analyzer():
    c = ComplexityAnalyzer().analyze_complexity("请分析并证明这个复杂定理，为什么成立？")
    assert c["is_complex"] and c["score"] > 0.4
    c2 = ComplexityAnalyzer().analyze_complexity("你好")
    assert not c2["is_complex"]


# ── 闹钟 ──

def test_alarm_check_and_trigger(db):
    alarm_api.fired_log.clear()
    alarm_api.dismissed_log.clear()
    alarm_api.init_alarm_api(db, auth_manager=None)
    now = datetime.now()
    conn = db._get_connection()
    weekday = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][now.weekday()]
    conn.execute(
        "INSERT INTO alarms (id, user_id, time, days, message, enabled, created_at) "
        "VALUES (?, ?, ?, ?, ?, 1, ?)",
        ("t0001", 1, now.strftime("%H:%M"), json.dumps([weekday]), "测试闹钟",
         now.isoformat()))
    conn.commit()
    triggered = alarm_api.check_and_trigger(1)
    assert len(triggered) == 1 and triggered[0]["message"] == "测试闹钟"
    # 同一分钟内不重复触发
    assert alarm_api.check_and_trigger(1) == []


# ── 技能工具（TaskTools） ──

def test_task_tools_skill(tm, db):
    import importlib.util
    skill_file = (Path(__file__).resolve().parents[1]
                  / "apps/dsn_study/skills/builtin/study_tasks/tools/task_tools.py")
    spec = importlib.util.spec_from_file_location("study_task_tools", str(skill_file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    tools = mod.TaskTools()
    tools.task_manager = tm   # 对齐 inject_dependencies 的实例属性注入
    tools.db = db

    out = tools.create_reminder(text="技能创建的提醒",
                                time=(datetime.now() + timedelta(minutes=30)).isoformat())
    assert "task_id" in out
    listing = tools.list_reminders()
    assert any(r["text"] == "技能创建的提醒" for r in listing["reminders"])
    # 单用户默认归属 uid=1
    assert tm.get_task(out["task_id"]).user_id == 1


# ── boot 装配冒烟（TaskManager/路由挂载） ──

@pytest.fixture(scope="module")
def study_app():
    os.environ["QUESTION_BANK_DB_PATH"] = (
        tempfile.mkdtemp(prefix="dsn_study_tasks_boot_") + "/qb.db")
    from apps.dsn_study.boot import create_application
    return create_application()


def test_boot_mounts_task_apis(study_app):
    client = study_app.test_client()
    rv = client.get("/api/reminder/list")
    assert rv.status_code == 200
    assert "reminders" in rv.get_json()
    rv = client.get("/api/alarms")
    assert rv.status_code == 200
    assert "alarms" in rv.get_json()
    rv = client.post("/api/heartbeat")
    assert rv.status_code == 200
    assert "has_notification" in rv.get_json()
    # TaskManager 已装配并注册
    assert study_app.config.get("TASK_MANAGER") is not None
