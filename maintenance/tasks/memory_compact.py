# maintenance/tasks/memory_compact.py
# 记忆整理任务 — 合并碎片记忆、清理过期条目

from __future__ import annotations

import logging

from .base import MaintenanceTask, TaskProgress

logger = logging.getLogger("maintenance.tasks.memory")


class MemoryCompactTask(MaintenanceTask):
    name = "记忆整理"
    priority = 10
    requires_db = True

    def __init__(self, db=None):
        super().__init__()
        self._db = db

    def run(self, reporter) -> dict:
        if self._db is None:
            return {"success": False, "error": "数据库不可用"}

        try:
            conn = self._db._get_connection()
            # 1. 清理孤立记忆（关联聊天已被删除的）
            reporter(TaskProgress(current=1, total=3, message="清理孤立记忆条目..."))
            cursor = conn.execute("""
                DELETE FROM memories WHERE chat_id NOT IN
                (SELECT chat_id FROM chats)
            """)
            deleted_orphan = cursor.rowcount

            # 2. 压缩旧记忆（仅保留每条记忆的前 200 字摘要）
            reporter(TaskProgress(current=2, total=3, message="压缩过长的旧记忆摘要..."))
            rows = conn.execute(
                "SELECT memory_id, summary FROM memories WHERE LENGTH(summary) > 500"
            ).fetchall()
            compressed = 0
            for row in rows:
                short = row["summary"][:200]
                conn.execute(
                    "UPDATE memories SET summary = ? WHERE memory_id = ?",
                    (short, row["memory_id"]),
                )
                compressed += 1
            conn.commit()

            # 3. 更新统计
            reporter(TaskProgress(current=3, total=3, message="更新记忆统计..."))
            total_memories = conn.execute(
                "SELECT COUNT(*) AS cnt FROM memories"
            ).fetchone()["cnt"]

            return {
                "success": True,
                "stats": {
                    "deleted_orphans": deleted_orphan,
                    "compressed": compressed,
                    "total_memories": total_memories,
                },
            }
        except Exception as e:
            logger.error("记忆整理失败: %s", e)
            return {"success": False, "error": str(e)}
