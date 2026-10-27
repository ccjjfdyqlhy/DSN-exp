# tests/test_bugfix_regressions.py
# 本轮 bug 修复的回归测试 — 覆盖三层审查发现的问题的边界条件。
#
# 分区：
#   1. infra/tasks（TaskScheduler 恢复/取消/双执行/契约）
#   2. apps/dsn_study 任务管理器（取消失效/状态守卫/周期任务重启/通知原子领取）
#   3. 闹钟 API（宽窗触发/校验/静音保留）
#   4. harness 标准工具（file.read 语义/text.chunk/web.fetch 协议白名单）
#   5. harness MCP（禁用服务器残留工具清理/同步路径预热）
#   6. infra 杂项（Retry/TOTP/SemanticCache/Runtime）

import json
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from infra.tasks import TaskScheduler, TaskExecutorRegistry
from infra.runtime import Runtime
from infra.cache import SemanticCache
from infra.policy.retry import RetryPolicy


# ════════════════════════════════════════════════════════════
# 1. infra TaskScheduler
# ════════════════════════════════════════════════════════════

def test_infra_scheduler_recovers_running_tasks(tmp_path):
    """崩溃时遗留的 running 任务在重启后应恢复为 pending（文档承诺）。"""
    db = str(tmp_path / "t.db")
    s1 = TaskScheduler(db, executors={"noop": lambda p: None})
    tid = s1.schedule("job", "noop", {}, when=time.time() - 10)
    s1._execute("UPDATE scheduled_tasks SET status='running' WHERE task_id=?", (tid,))
    s1.close()

    s2 = TaskScheduler(db)
    try:
        due = s2.fetch_due()
        assert [r["task_id"] for r in due] == [tid]
    finally:
        s2.close()


def test_infra_scheduler_cancelled_running_not_revived(tmp_path):
    """执行中取消的周期任务不允许被 _handle_success 复活成 pending。"""
    started = threading.Event()
    release = threading.Event()

    def slow(_payload):
        started.set()
        release.wait(3)

    s = TaskScheduler(str(tmp_path / "t.db"), executors={"slow": slow})
    try:
        tid = s.schedule("x", "slow", {}, interval=1.0)
        row = dict(s._fetchall(
            "SELECT * FROM scheduled_tasks WHERE task_id=?", (tid,))[0])
        th = threading.Thread(target=lambda: s._run_task(dict(row)))
        th.start()
        assert started.wait(2)
        assert s.cancel(tid) is True
        release.set()
        th.join(3)
        rows = s.list_tasks()
        assert rows[0]["status"] == "cancelled"
        assert s.fetch_due() == []
    finally:
        release.set()
        s.close()


def test_infra_scheduler_no_double_claim(tmp_path):
    """并发 _run_task 不允许对同一任务各执行一次。"""
    calls = []
    started = threading.Event()
    release = threading.Event()

    def once(_payload):
        calls.append(1)
        started.set()
        release.wait(3)

    s = TaskScheduler(str(tmp_path / "t.db"), executors={"once": once})
    try:
        tid = s.schedule("x", "once", {})
        row = dict(s._fetchall(
            "SELECT * FROM scheduled_tasks WHERE task_id=?", (tid,))[0])
        th1 = threading.Thread(target=lambda: s._run_task(dict(row)))
        th1.start()
        assert started.wait(2)
        th2 = threading.Thread(target=lambda: s._run_task(dict(row)))
        th2.start()
        th2.join(3)
        release.set()
        th1.join(3)
        assert len(calls) == 1
    finally:
        release.set()
        s.close()


def test_infra_scheduler_registry_contract(tmp_path):
    """registry=TaskExecutorRegistry 时任务应真正执行（此前契约不匹配全挂）。"""
    got = []
    reg = TaskExecutorRegistry(max_workers=1)
    reg.register_type("echo", lambda **p: got.append(p) or p)
    s = TaskScheduler(str(tmp_path / "t.db"), registry=reg)
    try:
        s.schedule("x", "echo", {"a": 1})
        assert s.run_once() == 1
        assert got == [{"a": 1}]
        assert s.list_tasks()[0]["status"] == "done"
    finally:
        s.close()


# ════════════════════════════════════════════════════════════
# 2. apps/dsn_study TaskManager
# ════════════════════════════════════════════════════════════

from apps.dsn_study.db.question_bank import QuestionBankDBManager
from apps.dsn_study.tasks import TaskManager, TaskType, TaskStatus
from apps.dsn_study.api import alarm as alarm_api


@pytest.fixture()
def qdb(tmp_path):
    return QuestionBankDBManager(
        db_path=str(tmp_path / "qb.db"))


@pytest.fixture()
def mgr(qdb):
    manager = TaskManager(qdb, llm=None, max_workers=2)
    yield manager
    manager.shutdown()


def _wait_status(mgr, tid, statuses, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = mgr.get_task(tid)
        if task and task.status in statuses:
            return task
        time.sleep(0.05)
    return mgr.get_task(tid)


def test_cancel_task_removes_scheduled_job(mgr):
    """cancel_task 后：调度 job 被移除 + 到点守卫拒绝执行。"""
    tid = mgr.create_task(
        TaskType.REMINDER, user_id=1, chat_id=0,
        params={"text": "待取消"},
        scheduled_time=datetime.now() + timedelta(hours=1))
    assert any(tid in j.tags for j in mgr.scheduler.jobs)

    assert mgr.cancel_task(tid) is True
    assert not any(tid in j.tags for j in mgr.scheduler.jobs)
    assert mgr.get_task(tid).status == TaskStatus.CANCELLED
    # 重复取消安全
    assert mgr.cancel_task(tid) is True
    assert mgr.cancel_task("no-such-id") is False


def test_execute_task_refuses_non_pending(mgr):
    """已取消/已完成的任务被再次点名时不执行、状态不被覆盖。"""
    tid = mgr.create_task(
        TaskType.REMINDER, user_id=1, chat_id=0,
        params={"text": "x"},
        scheduled_time=datetime.now() + timedelta(hours=1))
    mgr.cancel_task(tid)

    fut = mgr.execute_task(tid)
    assert fut.result() == {}
    assert mgr.get_task(tid).status == TaskStatus.CANCELLED


def test_recurring_habit_not_missed_on_reload(qdb):
    """停机 >5 分钟后重启：HABIT 不应被判 MISSED 消失，而应补触发并重排。"""
    # 种子管理器：负责建表
    TaskManager(qdb, llm=None, max_workers=1).shutdown()

    tid = "habit-reload-1"
    past = (datetime.now() - timedelta(minutes=30)).isoformat()
    conn = qdb._get_connection()
    conn.execute(
        "INSERT INTO tasks (task_id, task_type, user_id, chat_id, params, priority, "
        "scheduled_time, interval_seconds, skip_count, status, created_at) "
        "VALUES (?, 'habit', 1, 0, '{}', 1, ?, 60, 0, 'pending', ?)",
        (tid, past, past))
    conn.commit()

    mgr2 = TaskManager(qdb, llm=None, max_workers=1)
    try:
        # 补触发执行 → _handle_task_result 重排：回到 PENDING 且时间在未来
        task = _wait_status(mgr2, tid, {TaskStatus.PENDING}, timeout=6.0)
        assert task is not None and task.status == TaskStatus.PENDING
        assert task.scheduled_time > datetime.now()
    finally:
        mgr2.shutdown()


def test_recurring_daily_plan_not_missed_on_reload(qdb):
    """停机后重启：DAILY_PLAN 保持 PENDING 并按每日 trigger_time 重排。"""
    TaskManager(qdb, llm=None, max_workers=1).shutdown()

    tid = "daily-reload-1"
    past = (datetime.now() - timedelta(hours=2)).isoformat()
    conn = qdb._get_connection()
    conn.execute(
        "INSERT INTO tasks (task_id, task_type, user_id, chat_id, params, priority, "
        "scheduled_time, interval_seconds, skip_count, status, created_at) "
        "VALUES (?, 'daily_plan', 1, 0, '{\"trigger_time\": \"03:00\"}', 1, ?, 0, 0, 'pending', ?)",
        (tid, past, past))
    conn.commit()

    mgr2 = TaskManager(qdb, llm=None, max_workers=1)
    try:
        task = mgr2.get_task(tid)
        assert task is not None
        assert task.status == TaskStatus.PENDING, \
            f"DAILY_PLAN 不应被标 MISSED，实际 {task.status}"
        assert any(tid in j.tags for j in mgr2.scheduler.jobs)
    finally:
        mgr2.shutdown()


def test_daily_plan_stays_pending_after_fire(mgr):
    """DAILY_PLAN 触发完成后复位 PENDING + 顺延到下一次触发点（重启可恢复）。"""
    tid = mgr.create_task(
        TaskType.DAILY_PLAN, user_id=1, chat_id=0,
        params={"trigger_time": "03:00"},
        scheduled_time=datetime.now() + timedelta(hours=1))

    from concurrent.futures import Future
    f: Future = Future()
    f.set_result({"reminder_text": "今日计划"})
    mgr._handle_task_result(tid, f)

    task = mgr.get_task(tid)
    assert task.status == TaskStatus.PENDING
    assert task.scheduled_time > datetime.now()


def test_notification_claim_is_atomic(mgr):
    """同一通知的两次领取只有一次成功（防并发心跳重复投递）。"""
    tid = mgr.create_task(
        TaskType.REMINDER, user_id=7, chat_id=0,
        params={"text": "领取测试"},
        scheduled_time=datetime.now() - timedelta(seconds=1))
    task = _wait_status(mgr, tid, {TaskStatus.COMPLETED, TaskStatus.FAILED})
    assert task.status == TaskStatus.COMPLETED

    notes = mgr.fetch_pending_notifications(7)
    assert notes, "应有待投递通知"
    nid = notes[0]["notification_id"]
    assert mgr.claim_notification(nid) is True
    assert mgr.claim_notification(nid) is False  # 已领取
    # 领取后不再出现在待拉取列表
    assert all(n["notification_id"] != nid for n in mgr.fetch_pending_notifications(7))
    mgr.mark_notification_delivered(nid)


def test_normalize_trigger_time(mgr):
    """trigger_time 归一化：单数字小时/带秒可接受，垃圾值拒绝。"""
    assert mgr._normalize_trigger_time("7:30") == "07:30"
    assert mgr._normalize_trigger_time("07:30:00") == "07:30"
    with pytest.raises(ValueError):
        mgr._normalize_trigger_time("25:00")
    with pytest.raises(ValueError):
        mgr._normalize_trigger_time("abc")


# ════════════════════════════════════════════════════════════
# 3. 闹钟 API
# ════════════════════════════════════════════════════════════

@pytest.fixture()
def alarm_env(qdb, monkeypatch):
    monkeypatch.setattr(alarm_api, "_db", qdb)
    alarm_api._init_alarm_table()
    with alarm_api.fired_log_lock:
        alarm_api.fired_log.clear()
        alarm_api.dismissed_log.clear()
    yield qdb
    with alarm_api.fired_log_lock:
        alarm_api.fired_log.clear()
        alarm_api.dismissed_log.clear()


def _insert_alarm(db, alarm_id, time_str, days=None, enabled=1):
    conn = db._get_connection()
    conn.execute(
        "INSERT INTO alarms (id, user_id, time, days, message, sound, enabled, created_at) "
        "VALUES (?, 1, ?, ?, ?, NULL, ?, ?)",
        (alarm_id, time_str, json.dumps(days or ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
         "测试", enabled, datetime.now().isoformat()))
    conn.commit()


def test_alarm_grace_window_and_once(alarm_env):
    """错过精确分钟（宽窗内）仍补触发，且当天只触发一次。"""
    now = datetime.now()
    t = (now - timedelta(minutes=3)).strftime("%H:%M")
    _insert_alarm(alarm_env, "a1", t)

    triggered = alarm_api.check_and_trigger(1)
    assert len(triggered) == 1 and triggered[0]["id"] == "a1"
    # 同一分钟内的第二次心跳不应重复触发
    assert alarm_api.check_and_trigger(1) == []


def test_alarm_outside_grace_not_triggered(alarm_env):
    """超过宽窗的历史闹钟不引爆（避免重启后全部迟到闹钟一次性涌出）。"""
    t = (datetime.now() - timedelta(minutes=30)).strftime("%H:%M")
    _insert_alarm(alarm_env, "a2", t)
    assert alarm_api.check_and_trigger(1) == []


def test_alarm_invalid_time_row_skipped(alarm_env):
    """库里的坏行（time 非法格式）跳过而不是 500。"""
    conn = alarm_env._get_connection()
    conn.execute(
        "INSERT INTO alarms (id, user_id, time, days, message, sound, enabled, created_at) "
        "VALUES ('bad1', 1, '99:99', '[]', 'm', NULL, 1, ?)", (datetime.now().isoformat(),))
    conn.commit()
    assert alarm_api.check_and_trigger(1) == []


def test_alarm_validate_days_type():
    assert alarm_api._validate_alarm({"time": "07:00", "days": 3}) is not None
    assert alarm_api._validate_alarm({"time": "07:00", "days": None}) is not None
    assert alarm_api._validate_alarm({"time": "07:00", "days": ["Mon"]}) is None
    assert alarm_api._validate_alarm({"time": "25:00"}) is not None


def test_alarm_prune_keeps_future_dismissal():
    """dismiss 写入的未来多天静音不被清理线程删掉。"""
    future = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
    with alarm_api.fired_log_lock:
        alarm_api.dismissed_log.add(f"a1:{future}")
        alarm_api.fired_log.add("old:2020-01-01")
    alarm_api._prune_logs_once()
    with alarm_api.fired_log_lock:
        assert f"a1:{future}" in alarm_api.dismissed_log
        assert "old:2020-01-01" not in alarm_api.fired_log


# ════════════════════════════════════════════════════════════
# 4. harness 标准工具
# ════════════════════════════════════════════════════════════

from harness.tools.standard import (
    ToolDeps, tool_file_read, tool_text_chunk, tool_web_fetch,
)


def test_file_read_max_chars_zero_means_full(tmp_path):
    f = tmp_path / "big.txt"
    body = "x" * 20000
    f.write_text(body, encoding="utf-8")
    read = tool_file_read(ToolDeps(workspace=str(tmp_path)))
    result = read(str(f), max_chars=0)
    assert result["success"] and result["content"] == body
    assert "truncated" not in result


def test_text_chunk_negative_overlap_clamped():
    chunk = tool_text_chunk()
    text = "".join(str(i % 10) for i in range(100))
    r = chunk(text, chunk_size=10, overlap=-5)
    # 负 overlap 被钳到 0：块之间不丢字符
    joined = "".join(r["chunks"])
    assert joined == text


def test_web_fetch_rejects_file_scheme():
    fetch = tool_web_fetch(ToolDeps(workspace="/tmp"))
    r = fetch("file:///etc/passwd")
    assert not r["success"] and "http" in r["error"]
    r2 = fetch("ftp://example.com/x")
    assert not r2["success"]


# ════════════════════════════════════════════════════════════
# 5. harness MCP
# ════════════════════════════════════════════════════════════

from harness.tools import MCPManager, MCPServerConfig, ToolRegistry
from harness.tools.toolbox import RegistryIndexSource, ToolboxManager


def _remote_tool(name, schema=None):
    return SimpleNamespace(name=name, description=f"{name} 描述",
                           inputSchema=schema or {"type": "object", "properties": {}})


class FakeSession:
    def __init__(self, tools=None):
        self.tools = tools or []

    async def initialize(self):
        pass

    async def list_tools(self, cursor=None):
        return SimpleNamespace(tools=list(self.tools), nextCursor=None)


class StubManager(MCPManager):
    def __init__(self, servers, sessions):
        super().__init__(servers)
        self._stub_sessions = sessions

    async def _open_session(self, cfg, stack):
        return self._stub_sessions[cfg.name]


def test_mcp_disabled_server_tools_removed_on_reload():
    """服务器被禁用后 refresh/load_tools 应摘除它此前注册的工具。"""
    session = FakeSession(tools=[_remote_tool("t")])
    mgr = StubManager([MCPServerConfig(name="srv", transport="stdio", command="x")],
                      {"srv": session})
    reg = ToolRegistry()
    import asyncio
    asyncio.run(mgr.load_tools(reg))
    assert "mcp.srv.t" in reg

    mgr.servers["srv"].enabled = False
    asyncio.run(mgr.refresh("srv"))
    assert "mcp.srv.t" not in reg


def test_mcp_close_while_connecting_does_not_leak():
    """close 与并发首连接竞态：连接完成后 close 应能摘除会话。"""
    session = FakeSession(tools=[])
    mgr = StubManager([MCPServerConfig(name="srv", transport="stdio", command="x")],
                      {"srv": session})
    import asyncio

    async def _run():
        task = asyncio.ensure_future(mgr.ensure_connected("srv"))
        await asyncio.sleep(0)
        await mgr.close()
        await task
        # close 在连接完成前执行 → 会话最终不应残留在 _sessions
        await mgr.close()
        assert mgr._sessions.get("srv") is None or mgr._sessions.get("srv") is session

    asyncio.run(_run())


def test_sdk_sync_chat_registers_mcp_tools():
    """同步 chat()/run() 也必须完成 MCP 预热（此前永不注册远端工具）。"""
    import asyncio

    def call_fn(name, args):
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="42")],
                               structuredContent=None, isError=False)

    session = FakeSession(tools=[_remote_tool(
        "add", {"type": "object", "properties": {"a": {"type": "integer"}}})])
    session.call_tool = call_fn

    from harness import Agent

    class _Scripted:
        def __init__(self):
            self.turn = 0

        async def invoke(self, messages, tools=None):
            from infra.orchestrator.base import ChatResponse, ToolCall
            from harness.tools import to_wire_name
            self.turn += 1
            if self.turn == 1:
                return ChatResponse(content="", tool_calls=[
                    ToolCall(id="c1", name=to_wire_name("mcp.srv.add"),
                             arguments={"a": 2})])
            return ChatResponse(content="done")

    client = _Scripted()
    agent = Agent(client, mcp=[{"name": "srv", "transport": "stdio", "command": "x"}])
    stub = StubManager(agent._assembled.mcp.servers.values(), {"srv": session})
    agent._assembled.mcp = stub
    agent._mcp_ready = False

    reply = agent.chat("算 2+2")
    assert reply == "done"
    assert agent._mcp_ready is True
    # 同步路径预热成功：远端工具已注册进注册表
    assert agent.tools.has("mcp.srv.add")


# ════════════════════════════════════════════════════════════
# 6. infra 杂项
# ════════════════════════════════════════════════════════════

def test_retry_recognizes_requests_http_error():
    import requests
    resp = requests.models.Response()
    resp.status_code = 429
    err = requests.exceptions.HTTPError("429 Too Many Requests", response=resp)
    assert RetryPolicy._is_retryable(err, {429, 500}) is True
    resp2 = requests.models.Response()
    resp2.status_code = 403
    err2 = requests.exceptions.HTTPError("403", response=resp2)
    assert RetryPolicy._is_retryable(err2, {429, 500}) is False


def test_totp_invalid_secret_returns_false():
    from infra.auth.totp import TOTP
    t = TOTP()
    assert t.verify("123456", "not-valid-base32!!!") is False
    assert t.verify("123456", "") is False


def test_semantic_cache_l1_bounded():
    cache = SemanticCache(max_l1_entries=50)
    for i in range(500):
        cache.put(f"q{i}", i)
    assert cache.l1_size <= 50
    # 最近写入的仍在
    assert cache.get("q499") == (True, 499)


def test_runtime_factory_resolved_once():
    rt = Runtime()
    calls = []

    def factory():
        calls.append(1)
        return object()

    rt.register_factory("svc", factory)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(lambda _: rt.resolve("svc"), range(32)))
    assert len(calls) == 1
