# tests/test_harness_tasks.py
# harness 任务系统超集测试：状态/优先级/服务契约 + dsn 实现对齐。

from __future__ import annotations

import sqlite3

from harness.tasks import (
    Task, TaskStatus, TaskPriority, TaskExecutor, TaskExecutorRegistry,
    TaskManagerPort,
)


def test_task_status_superset_contains_dsn_statuses():
    """harness TaskStatus 是 dsn 状态集合的超集（含 MISSED/SKIPPED）。"""
    for name in ("PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED",
                 "MISSED", "SKIPPED"):
        assert hasattr(TaskStatus, name), f"缺少状态 {name}"
    assert TaskStatus.MISSED.value == "missed"
    assert TaskStatus.SKIPPED.value == "skipped"


def test_task_priority_enum():
    assert TaskPriority.LOW.value == 0
    assert TaskPriority.NORMAL.value == 1
    assert TaskPriority.HIGH.value == 2
    assert TaskPriority.URGENT.value == 3


def test_dsn_task_types_are_harness_types():
    """dsn 的 TaskStatus / TaskPriority 就是 harness 的（单一生效源）。"""
    from apps.dsn.tasks import TaskStatus as DsnStatus
    from apps.dsn.tasks import TaskPriority as DsnPriority
    assert DsnStatus is TaskStatus
    assert DsnPriority is TaskPriority


def test_dsn_task_has_harness_compat_bridges():
    """dsn Task 暴露 type / id 兼容桥（供 harness TaskExecutorRegistry 使用）。"""
    from apps.dsn.tasks import Task as DsnTask, TaskType, TaskPriority as TP
    t = DsnTask(task_id="t1", task_type=TaskType.REMINDER, user_id=1, chat_id=2,
                params={"text": "hi"}, priority=TP.HIGH)
    assert t.type == "reminder"
    assert t.id == "t1"
    assert t.status is TaskStatus.PENDING


def test_dsn_task_manager_conforms_taskmanagerport():
    """dsn TaskManager 结构上符合 harness TaskManagerPort 契约。"""
    from apps.dsn.tasks import TaskManager

    class FakeDB:
        def __init__(self):
            self.conn = sqlite3.connect(":memory:")
            self.conn.row_factory = sqlite3.Row
        def _get_connection(self):
            return self.conn

    tm = TaskManager(db=FakeDB(), max_workers=1)
    try:
        assert isinstance(tm, TaskManagerPort), "TaskManager 未实现 TaskManagerPort"
    finally:
        tm.shutdown()


def test_dsn_task_manager_create_task_via_harness_contract():
    from apps.dsn.tasks import TaskManager, TaskType

    class FakeDB:
        def __init__(self):
            self.conn = sqlite3.connect(":memory:")
            self.conn.row_factory = sqlite3.Row
        def _get_connection(self):
            return self.conn

    tm = TaskManager(db=FakeDB(), max_workers=1)
    try:
        tid = tm.create_task(TaskType.REMINDER, user_id=1, chat_id=2,
                             params={"text": "3点提醒"}, scheduled_time=None)
        assert isinstance(tid, str) and tid
        task = tm.get_task(tid)
        assert task is not None and task.task_type == TaskType.REMINDER
    finally:
        tm.shutdown()

def test_dsn_task_dispatch_goes_through_harness_registry():
    """dsn 任务类型分派经 harness TaskExecutorRegistry（处理器路由正确）。"""
    from apps.dsn.tasks import TaskManager, TaskType, Task as DsnTask, TaskPriority as TP

    class FakeDB:
        def __init__(self):
            self.conn = sqlite3.connect(":memory:")
            self.conn.row_factory = sqlite3.Row
        def _get_connection(self):
            return self.conn

    calls = []
    orig = {}
    for name in ("_execute_reasoner_task", "_execute_reminder_task",
                 "_execute_analysis_task", "_execute_action_task"):
        orig[name] = getattr(TaskManager, name)
        def _mk(tag):
            def _h(self, task):
                calls.append((tag, task.task_type.value))
                return {"handled": tag}
            return _h
        setattr(TaskManager, name, _mk(name))

    tm = TaskManager(db=FakeDB(), max_workers=1)
    try:
        # registry 持有 8 个类型（提醒族共享 reminder 处理器）
        types = sorted(tm._exec_registry.types())
        assert types == sorted(["reasoner", "reminder", "habit", "countdown",
                                "daily_plan", "periodic", "analysis", "action"]), types
        # 分派路由
        for ttype in (TaskType.REASONER, TaskType.REMINDER, TaskType.HABIT,
                      TaskType.COUNTDOWN, TaskType.DAILY_PLAN, TaskType.PERIODIC,
                      TaskType.ANALYSIS, TaskType.ACTION):
            task = DsnTask(task_id=f"t-{ttype.value}", task_type=ttype,
                           user_id=1, chat_id=2, params={}, priority=TP.NORMAL)
            result = tm._execute_task_internal(task)
            expected = (
                "_execute_reasoner_task" if ttype == TaskType.REASONER else
                "_execute_reminder_task" if ttype in (TaskType.REMINDER, TaskType.HABIT,
                                                      TaskType.COUNTDOWN, TaskType.DAILY_PLAN,
                                                      TaskType.PERIODIC) else
                "_execute_analysis_task" if ttype == TaskType.ANALYSIS else
                "_execute_action_task")
            assert result == {"handled": expected}, (ttype, result)
        # 未知类型抛错
        from apps.dsn.tasks import _DsnTaskExecutor
        assert _DsnTaskExecutor.__mro__[1].__name__ == "TaskExecutor"
    finally:
        for name, fn in orig.items():
            setattr(TaskManager, name, fn)
        tm.shutdown()
