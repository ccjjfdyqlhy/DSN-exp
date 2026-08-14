# harness/tasks/base.py
# 通用任务抽象。
#
# DSN 超集：TaskStatus 已含 dsn 的 MISSED/SKIPPED；TaskPriority 为通用优先级；
# TaskManagerPort 是"对话路径任务服务"的 canonical 契约（dsn TaskManager 实现并
# 经 harness Runtime 注册，见 apps/dsn/tasks.py 与 boot.py）。

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Protocol, runtime_checkable


class TaskStatus(Enum):
    """任务状态（含 DSN 扩展：MISSED / SKIPPED）。"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    MISSED = "missed"              # 过期未执行（DSN 兼容）
    SKIPPED = "skipped"            # 用户主动跳过该次触发（DSN 兼容）


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
    """对话路径使用的任务服务契约（由 harness 全局引擎定义）。

    DSN 的 TaskManager 即实现此契约并经 harness Runtime 注册，
    对话路径（TaskPlugin / api / engine）经 harness 解析该服务。
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
