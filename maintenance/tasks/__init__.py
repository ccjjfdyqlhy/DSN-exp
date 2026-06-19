# maintenance/tasks/__init__.py
# 维护任务注册

from .base import MaintenanceTask, TaskProgress
from .backup import BackupTask
from .personality_optimize import PersonalityOptimizeTask
from .log_cleanup import LogCleanupTask

__all__ = [
    "MaintenanceTask", "TaskProgress",
    "BackupTask", "PersonalityOptimizeTask", "LogCleanupTask",
]
