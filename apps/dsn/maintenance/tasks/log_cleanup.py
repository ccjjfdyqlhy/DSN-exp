# maintenance/tasks/log_cleanup.py
# 日志清理任务 — 清理 30 天前旧的日志轮转文件

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from .base import MaintenanceTask, TaskProgress

logger = logging.getLogger("maintenance.tasks.log")


class LogCleanupTask(MaintenanceTask):
    name = "日志清理"
    priority = 30
    requires_db = False

    def __init__(self, log_dir: str = "", max_age_days: int = 30):
        super().__init__()
        self._log_dir = Path(log_dir) if log_dir else Path("logs")
        self._max_age = max_age_days * 86400

    def run(self, reporter) -> dict:
        try:
            log_dir = self._log_dir
            if not log_dir.exists():
                return {"success": True, "stats": {"deleted": 0, "freed_bytes": 0}}

            files = sorted(log_dir.iterdir())
            now = time.time()
            deleted = 0
            freed_bytes = 0

            reporter(TaskProgress(current=0, total=len(files),
                                   message=f"扫描 {len(files)} 个日志文件..."))

            for i, f in enumerate(files, 1):
                if not f.is_file():
                    continue
                age = now - f.stat().st_mtime
                if age > self._max_age:
                    freed_bytes += f.stat().st_size
                    f.unlink()
                    deleted += 1
                reporter(TaskProgress(current=i, total=len(files),
                                       message=f"已清理 {deleted} 个旧文件"))

            action = "已清理 %d 个文件, 释放 %.1f KB" % (
                deleted, freed_bytes / 1024,
            )
            logger.info("日志清理: %s", action)
            return {
                "success": True,
                "stats": {
                    "deleted": deleted,
                    "freed_bytes": freed_bytes,
                    "action": action,
                },
            }
        except Exception as e:
            logger.error("日志清理失败: %s", e)
            return {"success": False, "error": str(e)}
