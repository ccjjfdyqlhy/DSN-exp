# tests/test_harness_scheduler.py
# 持久化任务调度器（harness/tasks/scheduler.py）单元测试。

from __future__ import annotations

import time

import pytest

from harness.tasks import TaskScheduler


def test_schedule_one_shot_executes():
    calls = []
    sched = TaskScheduler(":memory:", executors={
        "echo": lambda p: calls.append(p.get("msg")),
    })
    tid = sched.schedule("任务A", "echo", {"msg": "hi"}, when=time.time() + 0.05)
    assert tid >= 1
    # 未到期不执行
    assert sched.run_once() == 0
    time.sleep(0.08)
    assert sched.run_once() == 1
    assert calls == ["hi"]
    # 一次性任务完成，不再执行
    time.sleep(0.02)
    assert sched.run_once() == 0
    assert sched.stats().get("done") == 1


def test_schedule_interval_repeats():
    calls = []
    sched = TaskScheduler(":memory:", executors={
        "tick": lambda p: calls.append(1),
    })
    sched.schedule("周期", "tick", when=time.time(), interval=0.05)
    time.sleep(0.02)
    assert sched.run_once() == 1
    assert len(calls) == 1
    time.sleep(0.06)
    assert sched.run_once() == 1
    assert len(calls) == 2


def test_schedule_failure_retries_then_error():
    attempts = {"n": 0}

    def flaky(p):
        attempts["n"] += 1
        raise RuntimeError("boom")

    sched = TaskScheduler(":memory:", executors={"flaky": flaky},
                          max_retries=2, tick=0.01)
    sched.schedule("失败任务", "flaky", when=time.time(), retry_delay=0.01)
    # 3 次尝试（1 次 + 2 次重试）后置 error
    for _ in range(3):
        time.sleep(0.015)
        sched.run_once()
    assert attempts["n"] == 3
    assert sched.stats().get("error") == 1


def test_cancel():
    sched = TaskScheduler(":memory:", executors={"e": lambda p: None})
    tid = sched.schedule("待取消", "e", when=time.time())
    assert sched.cancel(tid)
    assert sched.run_once() == 0
    assert sched.stats().get("cancelled") == 1


def test_persistence_across_restart(tmp_path):
    db = str(tmp_path / "tasks.db")
    calls = []
    s1 = TaskScheduler(db, executors={"e": lambda p: calls.append(p.get("x"))})
    s1.schedule("持久任务", "e", {"x": 1}, when=time.time() + 0.05)
    s1.close()
    # 重启：任务仍在，到期可执行
    s2 = TaskScheduler(db, executors={"e": lambda p: calls.append(p.get("x"))})
    time.sleep(0.08)
    assert s2.run_once() == 1
    assert calls == [1]
    s2.close()


def test_unknown_executor_marks_error():
    sched = TaskScheduler(":memory:")
    sched.schedule("无执行器", "nope", when=time.time(), retry_delay=0.01)
    for _ in range(4):
        time.sleep(0.012)
        sched.run_once()
    assert sched.stats().get("error") == 1


def test_background_loop(tmp_path):
    calls = []
    sched = TaskScheduler(str(tmp_path / "bg.db"), executors={
        "inc": lambda p: calls.append(1),
    })
    sched.schedule("后台", "inc", when=time.time())
    sched.start()
    deadline = time.time() + 3.0
    while not calls and time.time() < deadline:
        time.sleep(0.05)
    sched.stop()
    assert calls, "后台线程应执行到期任务"
