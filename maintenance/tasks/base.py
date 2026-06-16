# maintenance/tasks/base.py
# 维护任务基类

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger("maintenance.tasks")


@dataclass
class TaskProgress:
    current: int = 0
    total: int = 1
    message: str = ""


ProgressReporter = Callable[[TaskProgress], None]


class MaintenanceTask(ABC):
    """所有维护任务的基类"""

    name: str = ""
    priority: int = 50
    requires_db: bool = False
    requires_llm: bool = False

    def __init__(self):
        pass

    @abstractmethod
    def run(self, reporter: ProgressReporter) -> dict:
        """
        执行维护任务。

        :param reporter: 进度报告回调，任务内定时调用
        :return: 任务结果 dict（包含 success, stats 等）
        """
        ...
