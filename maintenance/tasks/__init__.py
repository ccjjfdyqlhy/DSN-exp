# maintenance/tasks/__init__.py
# 维护任务注册

from .base import MaintenanceTask, TaskProgress
from .memory_compact import MemoryCompactTask
from .personality_optimize import PersonalityOptimizeTask
from .log_cleanup import LogCleanupTask

__all__ = [
    "MaintenanceTask", "TaskProgress",
    "MemoryCompactTask", "PersonalityOptimizeTask", "LogCleanupTask",
]
