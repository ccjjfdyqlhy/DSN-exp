# tests/test_maintenance.py
# 服务器维护模块 — 单元测试

from __future__ import annotations

import time
import threading
import pickle
import tempfile
from pathlib import Path
from datetime import datetime

# ── 状态机 ──
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from maintenance.state import ServerState, ServerStateMachine


def test_initial_state():
    """新创建的状态机应为 READY"""
    sm = ServerStateMachine()
    assert sm.state == ServerState.READY


def test_ready_to_maint():
    """READY → MAINTENANCE 允许"""
    sm = ServerStateMachine()
    assert sm.transition(ServerState.MAINTENANCE)
    assert sm.state == ServerState.MAINTENANCE


def test_ready_to_standby():
    """READY → STANDBY 允许"""
    sm = ServerStateMachine()
    assert sm.transition(ServerState.STANDBY)
    assert sm.state == ServerState.STANDBY


def test_maint_to_ready():
    """MAINTENANCE → READY 允许"""
    sm = ServerStateMachine()
    sm.transition(ServerState.MAINTENANCE)
    assert sm.transition(ServerState.READY)
    assert sm.state == ServerState.READY


def test_maint_to_standby():
    """MAINTENANCE → STANDBY 非法"""
    sm = ServerStateMachine()
    sm.transition(ServerState.MAINTENANCE)
    assert not sm.transition(ServerState.STANDBY)
    assert sm.state == ServerState.MAINTENANCE


def test_standby_to_ready():
    """STANDBY → READY 允许"""
    sm = ServerStateMachine()
    sm.transition(ServerState.STANDBY)
    assert sm.transition(ServerState.READY)


def test_standby_to_maint():
    """STANDBY → MAINTENANCE 允许（待机时定时检修仍可进行）"""
    sm = ServerStateMachine()
    sm.transition(ServerState.STANDBY)
    assert sm.transition(ServerState.MAINTENANCE)
    assert sm.state == ServerState.MAINTENANCE


def test_on_transition_callback():
    """注册转换回调，验证调用"""
    calls = []
    sm = ServerStateMachine()
    sm.on_transition(lambda old, new: calls.append((old.value, new.value)))
    sm.transition(ServerState.MAINTENANCE)
    assert len(calls) == 1
    assert calls[0] == ("ready", "maint")


# ── 时钟 ──

from maintenance.clock import MaintenanceClock


def test_clock_tick():
    """时钟每秒 tick，触发回调"""
    ticks = []
    lock = threading.Lock()

    clock = MaintenanceClock(tick_callback=lambda: ticks.append(1))
    clock._interval = 0.05
    clock.start()
    time.sleep(0.12)
    clock.stop()
    assert len(ticks) >= 1


# ── 追踪器 ──

from maintenance.tracker import ActivityTracker


def test_tracker_record():
    """记录请求后，计数递增"""
    t = ActivityTracker(db=None)
    assert t.request_count() == 0
    t.record_request()
    assert t.request_count() == 1


def test_tracker_idle_probability():
    """没有历史数据的时段返回高空闲概率"""
    t = ActivityTracker(db=None)
    prob = t.idle_probability(3, 0)  # 凌晨 3:00
    assert prob > 0.9  # 默认返回接近 1


def test_tracker_save_load():
    """保存与加载追踪数据（DB 持久化）"""
    class MockDB:
        def __init__(self): self._store = {}
        def save_kv(self, k, v): self._store[k] = v; return True
        def load_kv(self, k): return self._store.get(k, "")
    db = MockDB()
    t1 = ActivityTracker(db=db)
    t1.record_request()
    t1.record_request()
    t1.save()
    assert len(db._store) == 1
    t2 = ActivityTracker(db=db)
    assert t2.load()
    assert t2.request_count() == 2


# ── 任务系统 ──

from maintenance.tasks import (
    MaintenanceTask, TaskProgress, PersonalityOptimizeTask, LogCleanupTask,
    AccountCheckTask,
)
from maintenance.system import TaskExecutor


class _SuccessTask(MaintenanceTask):
    name = "成功任务"
    priority = 10

    def run(self, reporter) -> dict:
        reporter(TaskProgress(current=1, total=1, message="工作中"))
        return {"success": True, "data": "ok"}


class _FailTask(MaintenanceTask):
    name = "失败任务"
    priority = 20

    def run(self, reporter) -> dict:
        reporter(TaskProgress(current=0, total=1, message="要失败了"))
        raise RuntimeError("故意的失败")


class _SlowTask(MaintenanceTask):
    name = "慢任务"
    priority = 30

    def run(self, reporter) -> dict:
        reporter(TaskProgress(current=0, total=1, message="慢速执行"))
        time.sleep(0.1)
        return {"success": True}


def test_task_executor_order():
    """任务按 priority 升序执行"""
    exec = TaskExecutor()
    results = []
    exec.register(_SlowTask())
    exec.register(_SuccessTask())
    exec.register(_FailTask())
    out = exec.run_all(lambda t, p: None)
    assert len(out) == 3
    assert out[0]["task"] == "成功任务"   # priority 10
    assert out[1]["task"] == "失败任务"   # priority 20
    assert out[2]["task"] == "慢任务"     # priority 30


def test_task_executor_fail_continues():
    """一个任务失败不应阻断后续"""
    exec = TaskExecutor()
    exec.register(_FailTask())     # priority 20
    exec.register(_SuccessTask())  # priority 10
    out = exec.run_all(lambda t, p: None)
    assert len(out) == 2
    # 按优先级升序: 成功任务(10) 先执行成功, 失败任务(20) 后执行失败
    assert out[0]["success"] is True
    assert out[1]["success"] is False


def test_task_executor_unregister():
    """unregister 应移除指定任务"""
    exec = TaskExecutor()
    exec.register(_SuccessTask())
    exec.register(_FailTask())
    assert exec.has("成功任务")
    assert exec.unregister("成功任务") is True
    assert not exec.has("成功任务")
    assert exec.unregister("不存在") is False
    assert len(exec.list()) == 1


def test_task_executor_set_priority():
    """set_priority 应重新排序"""
    exec = TaskExecutor()
    exec.register(_FailTask())     # 20
    exec.register(_SuccessTask())  # 10
    assert [t.name for t in exec.list()] == ["成功任务", "失败任务"]
    assert exec.set_priority("成功任务", 99) is True
    assert [t.name for t in exec.list()] == ["失败任务", "成功任务"]
    assert exec.set_priority("不存在", 5) is False


# ── 核心系统 ──

from maintenance.system import MaintenanceSystem


def test_system_starts_as_ready():
    """系统初始状态为 READY"""
    ms = MaintenanceSystem()
    assert ms.state.state == ServerState.READY


def test_system_trigger_maintenance():
    """trigger_maintenance 将状态切换为 MAINTENANCE"""
    ms = MaintenanceSystem()
    assert ms.trigger_maintenance()
    assert ms.state.state == ServerState.MAINTENANCE


def test_system_trigger_standby():
    """trigger_standby 将状态切换为 STANDBY"""
    ms = MaintenanceSystem()
    assert ms.trigger_standby()
    assert ms.state.state == ServerState.STANDBY


def test_system_record_request_wakes():
    """待机时 record_request 应唤醒"""
    ms = MaintenanceSystem()
    ms.trigger_standby()
    assert ms.state.state == ServerState.STANDBY
    ms.record_user_request()
    assert ms.state.state == ServerState.READY


def test_system_standby_no_double_transition():
    """已在 STANDBY 时重复触发应拒绝"""
    ms = MaintenanceSystem()
    assert ms.trigger_standby()
    assert not ms.trigger_standby()  # 已在 standby


def test_system_add_remove_task():
    """add_task/remove_task 应增删任务"""
    ms = MaintenanceSystem()
    names = [t["name"] for t in ms.list_tasks()]
    assert "系统备份" in names and "日志清理" in names and "人格蒸馏" in names

    ok, msg = ms.remove_task("日志清理")
    assert ok, msg
    names = [t["name"] for t in ms.list_tasks()]
    assert "日志清理" not in names

    ok, msg = ms.remove_task("日志清理")
    assert not ok  # 已移除

    ok, msg = ms.add_task("日志清理", priority=40)
    assert ok, msg
    task = [t for t in ms.list_tasks() if t["name"] == "日志清理"][0]
    assert task["priority"] == 40

    ok, msg = ms.add_task("日志清理")
    assert not ok  # 已存在

    ok, msg = ms.add_task("不存在的任务")
    assert not ok
    assert "未知任务" in msg


def test_system_task_persistence(tmp_path):
    """任务安排应持久化并可恢复"""
    import maintenance.system as msys
    orig = msys._TASK_CONFIG_FILE
    msys._TASK_CONFIG_FILE = str(tmp_path / "tasks.json")
    try:
        ms = MaintenanceSystem()
        ok, _ = ms.remove_task("日志清理")
        assert ok
        # 新实例应加载持久化配置，日志清理任务仍被移除
        ms2 = MaintenanceSystem()
        names = [t["name"] for t in ms2.list_tasks()]
        assert "日志清理" not in names
        assert "系统备份" in names
    finally:
        msys._TASK_CONFIG_FILE = orig


def test_system_add_account_check_task(tmp_path):
    """account_check 任务需要 account_id，且可持久化恢复"""
    import maintenance.system as msys
    orig = msys._TASK_CONFIG_FILE
    msys._TASK_CONFIG_FILE = str(tmp_path / "tasks.json")
    try:
        ms = MaintenanceSystem()
        # 不带 account_id 时应失败
        ok, msg = ms.add_task("account_check")
        assert not ok
        assert "已存在" not in msg  # 应为其他错误信息（无法创建）

        ok, msg = ms.add_task("account_check", account_id="backup", priority=30)
        assert ok, msg
        assert "账号检查:backup" in msg

        tasks = ms.list_tasks()
        check = [t for t in tasks if t["name"] == "账号检查:backup"]
        assert check and check[0]["account_id"] == "backup"
        assert check[0]["priority"] == 30

        # 持久化恢复
        ms2 = MaintenanceSystem()
        tasks2 = ms2.list_tasks()
        check2 = [t for t in tasks2 if t["name"] == "账号检查:backup"]
        assert check2 and check2[0]["account_id"] == "backup"
    finally:
        msys._TASK_CONFIG_FILE = orig


def test_account_check_task_requires_account_id():
    """AccountCheckTask 无 account_id 时应失败，有则调用测试"""
    task = AccountCheckTask()
    result = task.run(lambda p: None)
    assert result["success"] is False
    assert "account_id" in result["error"]

    task2 = AccountCheckTask(account_id="some_account")
    assert task2.name == "账号检查:some_account"
    # 账号不存在时返回失败而非抛异常
    result2 = task2.run(lambda p: None)
    assert result2["success"] is False


def test_system_available_tasks():
    """available_tasks 应列出所有内置任务"""
    ms = MaintenanceSystem()
    avail = ms.available_tasks()
    names = [t["name"] for t in avail]
    assert "账号检查" in names
    assert "系统备份" in names
    check = [t for t in avail if t["name"] == "账号检查"][0]
    assert check["requires"] == "account_id"


def test_system_maint_interval():
    """设置/清除维护重复周期"""
    from datetime import timedelta
    ms = MaintenanceSystem()
    assert ms.get_maint_interval() is None

    ok, msg = ms.set_maint_interval(3600)
    assert ok, msg
    assert ms.get_maint_interval() == 3600
    assert ms._next_maint_at is not None

    # 周期触发后应推进到下一个周期点，而非清空
    ms._next_maint_at = ms._next_maint_at - timedelta(seconds=7200)
    assert ms._should_start_maintenance() is True
    assert ms._next_maint_at is not None
    # 自动策略在手动周期下应被抑制
    assert ms._should_start_maintenance() is False  # 已推进到未来，且手动周期抑制自动策略

    ok, msg = ms.clear_maint_interval()
    assert ok, msg
    assert ms.get_maint_interval() is None
    assert ms._next_maint_at is None


def test_system_maint_interval_start_now():
    """start_now=True 时下次触发点应为当前时刻"""
    from datetime import datetime, timedelta
    ms = MaintenanceSystem()
    before = datetime.now()
    ok, _ = ms.set_maint_interval(300, start_now=True)
    assert ok
    assert ms.get_maint_interval() == 300
    assert ms._next_maint_at <= before + timedelta(seconds=1)


def test_system_maint_interval_persistence(tmp_path):
    """维护重复周期应持久化并恢复"""
    import maintenance.system as msys
    orig = msys._TASK_CONFIG_FILE
    msys._TASK_CONFIG_FILE = str(tmp_path / "tasks.json")
    try:
        ms = MaintenanceSystem()
        ok, _ = ms.set_maint_interval(7200)
        assert ok
        ms2 = MaintenanceSystem()
        assert ms2.get_maint_interval() == 7200
        assert ms2._next_maint_at is not None
    finally:
        msys._TASK_CONFIG_FILE = orig


def test_interval_prevents_auto_standby(tmp_path):
    """配置手动重复周期时，空闲也不进入自动待机（周期性检修不能停）"""
    from datetime import timedelta
    from unittest import mock
    import maintenance.system as msys
    orig = msys._TASK_CONFIG_FILE
    msys._TASK_CONFIG_FILE = str(tmp_path / "tasks.json")
    try:
        ms = MaintenanceSystem()
        ms.set_maint_interval(300)
        # 维护未到期
        ms._next_maint_at = datetime.now() + timedelta(seconds=9999)
        with mock.patch.object(ms.tracker, 'minutes_since_last_request',
                               return_value=999):
            ms._on_tick()
        assert ms.state.state == ServerState.READY, "设置了手动周期不应进入自动待机"
    finally:
        msys._TASK_CONFIG_FILE = orig


def test_standby_runs_scheduled_maintenance(tmp_path):
    """待机状态下，定时检修到点仍会进入维护（修复空闲后检修停止）"""
    import maintenance.system as msys
    orig = msys._TASK_CONFIG_FILE
    msys._TASK_CONFIG_FILE = str(tmp_path / "tasks.json")
    try:
        ms = MaintenanceSystem()
        assert ms.trigger_standby()
        assert ms.state.state == ServerState.STANDBY
        # 手动周期到点（start_now → _next_maint_at = now）
        ok, _ = ms.set_maint_interval(300, start_now=True)
        assert ok
        ms._on_tick()
        assert ms.state.state == ServerState.MAINTENANCE, \
            f"待机时定时检修应触发维护，实际 {ms.state.state.value}"
    finally:
        msys._TASK_CONFIG_FILE = orig


# ── 预置任务 ──


def test_log_cleanup_task_empty_dir(tmp_path):
    """空日志目录应返回成功"""
    task = LogCleanupTask(log_dir=str(tmp_path))
    result = task.run(lambda p: None)
    assert result.get("success") is True


def test_log_cleanup_deletes_old(tmp_path):
    """过期的日志文件应被删除"""
    old = tmp_path / "old.log"
    old.write_text("old data")
    # 设置 mtime 为 60 天前
    old_mtime = time.time() - 60 * 86400
    os.utime(str(old), (old_mtime, old_mtime))
    task = LogCleanupTask(log_dir=str(tmp_path), max_age_days=30)
    result = task.run(lambda p: None)
    assert result.get("success") is True
    assert result["stats"]["deleted"] >= 1


# ── SSE 桥 ──

from maintenance.frontend_bridge import broadcast, subscribe, unsubscribe


def test_sse_broadcast_receive():
    """广播事件后订阅者应收到"""
    q = subscribe()
    broadcast("test", {"msg": "hello"})
    data = q.get(timeout=1)
    assert "hello" in data
    unsubscribe(q)


def test_sse_unsubscribe():
    """取消订阅后不应再收到"""
    q = subscribe()
    unsubscribe(q)
    broadcast("test", {"msg": "x"})
    assert q.empty()


# ── 基于文件的追踪器测试 ──


def test_tracker_best_idle_window():
    """best_idle_window 应返回合理的时段"""
    t = ActivityTracker(db=None)
    window = t.best_idle_window(min_free_hours=2, max_hour=8)
    assert window is not None
    start, end = window
    assert 0 <= start < end <= 8
