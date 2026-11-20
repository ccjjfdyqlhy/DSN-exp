# infra/tasks/base.py
# 通用任务抽象。
#
# TaskStatus includes MISSED and SKIPPED from the earlier engine. TaskPriority is
# generic. TaskManagerPort is the canonical contract for the conversation task
# service; an application implements it and registers it through Runtime.

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Protocol, runtime_checkable


class TaskStatus(Enum):
    """Task status, including the MISSED and SKIPPED extensions."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    MISSED = "missed"              # the scheduled time passed without a run
    SKIPPED = "skipped"            # the user skipped this occurrence


class TaskPriority(Enum):
    """任务优先级。"""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3


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
        return self.status in (TaskStatus.COMPLETED, TaskStatus.FAILED,
                               TaskStatus.CANCELLED, TaskStatus.MISSED,
                               TaskStatus.SKIPPED)

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


@runtime_checkable
class TaskManagerPort(Protocol):
    """Contract for the task service used by the conversation path.

    An application implements it and registers it through Runtime. The task
    plugin, api and engine resolve the service from there.
    """

    def create_task(
        self,
        task_type: Any,
        user_id: int,
        chat_id: int,
        params: dict,
        priority: Any = ...,
        scheduled_time: Any = None,
        interval_seconds: int = 0,
    ) -> str: ...

    def execute_task(self, task_id: str) -> Any: ...

    def get_task(self, task_id: str) -> Optional[Task]: ...

    def fetch_pending_notifications(self, user_id: int, limit: int = 5) -> list: ...

    def mark_notification_delivered(self, notification_id: int) -> None: ...

    def shutdown(self) -> None: ...
