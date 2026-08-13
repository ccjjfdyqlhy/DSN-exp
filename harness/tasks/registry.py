# harness/tasks/registry.py
# TaskExecutorRegistry — 任务执行器注册与同步/异步执行。

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from .base import Task, TaskStatus, TaskExecutor

logger = logging.getLogger("harness.tasks")


class TaskExecutorRegistry:
    """按 task.type 分发到对应执行器。支持同步执行与线程池异步提交。"""

    def __init__(self, *, max_workers: int = 5):
        self._executors: dict[str, TaskExecutor] = {}
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        self._callbacks: dict[str, list[Callable[[Task], None]]] = {}

    def register(self, executor: TaskExecutor, *, replace: bool = False) -> TaskExecutor:
        if executor.type in self._executors and not replace:
            raise KeyError(f"任务执行器已注册: {executor.type}")
        self._executors[executor.type] = executor
        return executor

    def register_type(self, task_type: str, fn: Callable[..., Any],
                      *, replace: bool = False) -> TaskExecutor:
        return self.register(_FnExecutor(task_type, fn), replace=replace)

    def get(self, task_type: str) -> Optional[TaskExecutor]:
        return self._executors.get(task_type)

    def types(self) -> list[str]:
        return list(self._executors.keys())

    def on_complete(self, task_type: str, cb: Callable[[Task], None]) -> None:
        self._callbacks.setdefault(task_type, []).append(cb)

    def execute(self, task: Task) -> Task:
        """同步执行任务并更新状态。"""
        executor = self._executors.get(task.type)
        if executor is None:
            task.status = TaskStatus.FAILED
            task.error = f"未注册的任务执行器: {task.type}"
            return task
        task.status = TaskStatus.RUNNING
        try:
            task.result = executor.execute(task)
            task.status = TaskStatus.COMPLETED
        except Exception as e:  # noqa: BLE001
            task.status = TaskStatus.FAILED
            task.error = str(e)
            logger.exception("任务 %s(%s) 执行失败", task.id, task.type)
        finally:
            import time
            task.finished_at = time.time()
            executor.on_complete(task)
            self._notify(task)
        return task

    def submit(self, task: Task, *, callback: Optional[Callable[[Task], None]] = None) -> Task:
        """异步提交任务，返回 pending 任务。完成后回调。"""
        task.status = TaskStatus.PENDING

        def _run() -> None:
            self.execute(task)
            if callback is not None:
                callback(task)

        self._pool.submit(_run)
        return task

    def _notify(self, task: Task) -> None:
        for cb in self._callbacks.get(task.type, []):
            try:
                cb(task)
            except Exception:
                logger.exception("任务完成回调异常")

    def shutdown(self, *, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait)


class _FnExecutor(TaskExecutor):
    """把普通函数包装为执行器。fn(**task.params) -> result。"""

    def __init__(self, task_type: str, fn: Callable[..., Any]):
        self.type = task_type
        self._fn = fn

    def execute(self, task: Task) -> Any:
        return self._fn(**task.params)
