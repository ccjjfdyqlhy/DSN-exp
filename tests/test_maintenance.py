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
    """STANDBY → MAINTENANCE 非法"""
    sm = ServerStateMachine()
    sm.transition(ServerState.STANDBY)
    assert not sm.transition(ServerState.MAINTENANCE)


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
    t = ActivityTracker()
    assert t.request_count() == 0
    t.record_request()
    assert t.request_count() == 1


def test_tracker_idle_probability():
    """没有历史数据的时段返回高空闲概率"""
    t = ActivityTracker()
    prob = t.idle_probability(3, 0)  # 凌晨 3:00
    assert prob > 0.9  # 默认返回接近 1


def test_tracker_save_load(tmp_path):
    """保存与加载追踪数据"""
    path = str(tmp_path / "tracker.dat")
    t1 = ActivityTracker(data_path=path)
    t1.record_request()
    t1.record_request()
    t1.save()

    t2 = ActivityTracker(data_path=path)
    assert t2.load()
    assert t2.request_count() == 2


# ── 任务系统 ──

from maintenance.tasks import MaintenanceTask, TaskProgress, MemoryCompactTask, PersonalityOptimizeTask, LogCleanupTask
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
    exec.register(_FailTask())
    exec.register(_SuccessTask())
    out = exec.run_all(lambda t, p: None)
    assert len(out) == 2
    assert out[0]["success"] is False
    assert out[1]["success"] is True


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


# ── 预置任务 ──

def test_memory_compact_task_no_db():
    """无 DB 时返回错误"""
    task = MemoryCompactTask(db=None)
    result = task.run(lambda p: None)
    assert result.get("success") is False
    assert "数据库不可用" in result.get("error", "")


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
    t = ActivityTracker()
    window = t.best_idle_window(min_free_hours=2, max_hour=8)
    assert window is not None
    start, end = window
    assert 0 <= start < end <= 8
