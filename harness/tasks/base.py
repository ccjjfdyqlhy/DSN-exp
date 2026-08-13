# harness/tasks/base.py
# 通用任务抽象。

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    """一个通用任务。type 决定由哪个执行器处理。"""
    type: str
    params: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str = ""
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    meta: dict = field(default_factory=dict)

    @property
    def done(self) -> bool:
        return self.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)

    @property
    def ok(self) -> bool:
        return self.status == TaskStatus.COMPLETED


class TaskExecutor(ABC):
    """任务执行器。子类声明 type，实现 execute。"""

    type: str = ""

    @abstractmethod
    def execute(self, task: Task) -> Any:
        """执行任务，返回结果；抛出异常则记为失败。"""

    def on_complete(self, task: Task) -> None:
        """任务完成后回调（可覆写）。"""

    def __repr__(self) -> str:
        return f"<TaskExecutor {self.type}>"
