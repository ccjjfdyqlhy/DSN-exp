# harness/tasks/scheduler.py
# TaskScheduler — 持久化任务调度器（场景无关）。
#
# 实现 harness TaskManagerPort 契约中的定时语义
# （scheduled_time / interval_seconds）：一次性与周期任务，SQLite 持久化，
# 重启后未完成任务自动恢复。
#
# 能力:
#   - schedule(name, executor, payload, when=None, interval=None)  定时/周期任务
#   - cancel(task_id) / list_tasks() / stats()
#   - run_once() 手动执行一轮到期任务（测试/嵌入用）
#   - start()/stop() 后台轮询线程
#   - 执行器: TaskExecutorRegistry 名 / callable / async callable
#   - 失败重试: 执行抛错记 last_error，一次性任务转 pending 并按 retry_delay 顺延
#
# 用法:
#     sched = TaskScheduler("tasks.db", executors={"notify": send_notify})
#     sched.schedule("提醒", "notify", {"msg": "hi"}, when=time.time()+60)
#     sched.start()

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger("harness.tasks.scheduler")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    task_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    executor         TEXT NOT NULL,
    payload          TEXT NOT NULL DEFAULT '{}',
    scheduled_at     REAL NOT NULL,
    interval_seconds REAL,
    status           TEXT NOT NULL DEFAULT 'pending',
    run_count        INTEGER NOT NULL DEFAULT 0,
    last_run_at      REAL,
    last_error       TEXT,
    retry_delay      REAL NOT NULL DEFAULT 5.0,
    created_at       REAL NOT NULL,
    updated_at       REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scheduled_due
    ON scheduled_tasks (status, scheduled_at);
"""


class TaskScheduler:
    """持久化任务调度器。"""

    def __init__(
        self,
        db_path: str = ":memory:",
        *,
        executors: Optional[dict[str, Callable]] = None,
        registry: Any = None,
        tick: float = 0.5,
        max_retries: int = 3,
    ):
        self.db_path = str(db_path)
        self.executors: dict[str, Callable] = dict(executors or {})
        self.registry = registry               # TaskExecutorRegistry（可选）
        self.tick = tick
        self.max_retries = max_retries
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ── 内部 ──

    def _execute(self, sql: str, params: tuple = ()):
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def _fetchone(self, sql: str, params: tuple = ()):
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def _fetchall(self, sql: str, params: tuple = ()):
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    # ── 任务注册 ──

    def register_executor(self, name: str, fn: Callable) -> "TaskScheduler":
        self.executors[name] = fn
        return self

    def schedule(
        self,
        name: str,
        executor: str,
        payload: Optional[dict] = None,
        *,
        when: Optional[float] = None,
        interval: Optional[float] = None,
        retry_delay: float = 5.0,
    ) -> int:
        """登记任务，返回 task_id。

        when      首次执行时间（epoch 秒）；None = 立即到期
        interval  周期（秒）；None = 一次性任务
        """
        now = time.time()
        cur = self._execute(
            "INSERT INTO scheduled_tasks "
            "(name, executor, payload, scheduled_at, interval_seconds, "
            " created_at, updated_at, retry_delay) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, executor, json.dumps(payload or {}, ensure_ascii=False),
             when if when is not None else now,
             interval, now, now, retry_delay),
        )
        return int(cur.lastrowid)

    def cancel(self, task_id: int) -> bool:
        cur = self._execute(
            "UPDATE scheduled_tasks SET status = 'cancelled', updated_at = ? "
            "WHERE task_id = ? AND status IN ('pending', 'running')",
            (time.time(), task_id),
        )
        return cur.rowcount > 0

    def list_tasks(self, status: Optional[str] = None) -> list[dict]:
        if status:
            rows = self._fetchall(
                "SELECT * FROM scheduled_tasks WHERE status = ? "
                "ORDER BY scheduled_at", (status,))
        else:
            rows = self._fetchall(
                "SELECT * FROM scheduled_tasks ORDER BY scheduled_at")
        return [dict(r) for r in rows]

    # ── 到期与执行 ──

    def fetch_due(self, limit: int = 20) -> list[dict]:
        """取回到期（pending 且 scheduled_at <= now）的任务。"""
        rows = self._fetchall(
            "SELECT * FROM scheduled_tasks WHERE status = 'pending' "
            "AND scheduled_at <= ? ORDER BY scheduled_at LIMIT ?",
            (time.time(), limit),
        )
        return [dict(r) for r in rows]

    def _run_task(self, row: dict) -> bool:
        """执行单个任务。返回是否成功。"""
        task_id = row["task_id"]
        self._execute(
            "UPDATE scheduled_tasks SET status = 'running', updated_at = ? "
            "WHERE task_id = ?", (time.time(), task_id))
        payload = {}
        try:
            payload = json.loads(row["payload"] or "{}")
        except ValueError:
            pass
        try:
            self._invoke_executor(row["executor"], payload)
        except Exception as e:
            logger.warning("任务 %d (%s) 执行失败: %s", task_id, row["name"], e)
            self._handle_failure(row, str(e))
            return False
        self._handle_success(row)
        return True

    def _invoke_executor(self, executor: str, payload: dict) -> Any:
        fn = self.executors.get(executor)
        if fn is None and self.registry is not None:
            # TaskExecutorRegistry 契约: execute(executor_name, payload)
            result = self.registry.execute(executor, payload)
            if hasattr(result, "__await__"):
                import asyncio
                return asyncio.run(result)
            return result
        if fn is None:
            raise KeyError(f"执行器不存在: {executor}")
        result = fn(payload)
        if hasattr(result, "__await__"):
            import asyncio
            return asyncio.run(result)
        return result

    def _handle_success(self, row: dict) -> None:
        if row["interval_seconds"]:
            # 周期任务：顺延下一周期
            self._execute(
                "UPDATE scheduled_tasks SET status = 'pending', run_count = run_count + 1, "
                "last_run_at = ?, scheduled_at = ?, updated_at = ? WHERE task_id = ?",
                (time.time(), time.time() + row["interval_seconds"],
                 time.time(), row["task_id"]))
        else:
            self._execute(
                "UPDATE scheduled_tasks SET status = 'done', run_count = run_count + 1, "
                "last_run_at = ?, updated_at = ? WHERE task_id = ?",
                (time.time(), time.time(), row["task_id"]))

    def _handle_failure(self, row: dict, error: str) -> None:
        retries = row.get("run_count", 0)
        if row["interval_seconds"]:
            # 周期任务失败：顺延一个 tick 重试
            self._execute(
                "UPDATE scheduled_tasks SET status = 'pending', "
                "last_error = ?, scheduled_at = ?, updated_at = ? WHERE task_id = ?",
                (error, time.time() + self.tick, time.time(), row["task_id"]))
        elif retries < self.max_retries:
            # 一次性任务失败：按 retry_delay 顺延重试
            self._execute(
                "UPDATE scheduled_tasks SET status = 'pending', run_count = run_count + 1, "
                "last_error = ?, scheduled_at = ?, updated_at = ? WHERE task_id = ?",
                (error, time.time() + row["retry_delay"], time.time(), row["task_id"]))
        else:
            self._execute(
                "UPDATE scheduled_tasks SET status = 'error', run_count = run_count + 1, "
                "last_error = ?, updated_at = ? WHERE task_id = ?",
                (error, time.time(), row["task_id"]))

    # ── 运行 ──

    def run_once(self, limit: int = 20) -> int:
        """执行一轮到期任务，返回执行数。"""
        due = self.fetch_due(limit)
        done = 0
        for row in due:
            self._run_task(dict(row))
            done += 1
        return done

    def start(self) -> "TaskScheduler":
        """启动后台轮询线程。"""
        if self._thread is not None and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="harness-scheduler")
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.tick * 2 + 0.5)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                logger.exception("调度循环异常")
            self._stop.wait(self.tick)

    # ── 统计 ──

    def stats(self) -> dict:
        rows = self._fetchall(
            "SELECT status, COUNT(*) AS n FROM scheduled_tasks GROUP BY status")
        return {r["status"]: r["n"] for r in rows}

    def close(self) -> None:
        self.stop()
        with self._lock:
            self._conn.close()

    def __repr__(self) -> str:
        s = self.stats()
        return f"<TaskScheduler db={self.db_path} tasks={sum(s.values())} stats={s}>"
