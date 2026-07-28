# async_task_store.py
# 异步任务结果存储 — 内存 + SQLite 双后端

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from typing import Optional

logger = logging.getLogger("AsyncTaskStore")


class AsyncTaskStore:
    def __init__(self, db=None):
        self._lock = threading.Lock()
        self._tasks: dict[str, dict] = {}
        self._db = db
        self._init_db()

    def _init_db(self):
        if not self._db:
            return
        conn = self._db._get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS async_tasks (
                task_id      TEXT PRIMARY KEY,
                user_id      INTEGER NOT NULL,
                chat_id      INTEGER DEFAULT 0,
                status       TEXT DEFAULT 'running',
                reply        TEXT DEFAULT '',
                audio_b64    TEXT DEFAULT '',
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                error        TEXT DEFAULT ''
            )
        """)
        conn.commit()

    def create(self, task_id: str, user_id: int, chat_id: int = 0) -> dict:
        record = {
            "task_id": task_id,
            "user_id": user_id,
            "chat_id": chat_id,
            "status": "running",
            "reply": "",
            "audio_b64": "",
            "created_at": datetime.now().isoformat(),
            "completed_at": "",
            "error": "",
            "taskmgr_id": "",
        }
        with self._lock:
            self._tasks[task_id] = record
        if self._db:
            conn = self._db._get_connection()
            conn.execute(
                "INSERT INTO async_tasks (task_id, user_id, chat_id, status) "
                "VALUES (?, ?, ?, 'running')",
                (task_id, user_id, chat_id),
            )
            conn.commit()
        logger.info("异步任务创建: %s user=%d chat=%d", task_id, user_id, chat_id)
        return record

    def link_taskmgr(self, async_task_id: str, taskmgr_id: str) -> bool:
        """将 AsyncTaskStore 任务与 TaskManager 任务关联"""
        with self._lock:
            record = self._tasks.get(async_task_id)
            if not record:
                return False
            record["taskmgr_id"] = taskmgr_id
        logger.info("异步任务联动: async=%s taskmgr=%s", async_task_id, taskmgr_id)
        return True

    def complete_by_taskmgr_id(self, taskmgr_id: str, reply: str) -> bool:
        """通过 TaskManager 任务 ID 完成异步任务"""
        async_task_id = None
        with self._lock:
            for tid, rec in self._tasks.items():
                if rec.get("taskmgr_id") == taskmgr_id:
                    async_task_id = tid
                    break
        if not async_task_id:
            return False
        return self.complete(async_task_id, reply=reply)

    def complete(self, task_id: str, reply: str, audio_b64: str = "",
                  error: str = "") -> bool:
        with self._lock:
            record = self._tasks.get(task_id)
            if not record:
                return False
            record["status"] = "done" if not error else "failed"
            record["reply"] = reply
            record["audio_b64"] = audio_b64
            record["completed_at"] = datetime.now().isoformat()
            record["error"] = error
        if self._db:
            conn = self._db._get_connection()
            conn.execute(
                "UPDATE async_tasks SET status=?, reply=?, audio_b64=?, error=?, "
                "completed_at=CURRENT_TIMESTAMP WHERE task_id=?",
                (record["status"], reply, audio_b64, error, task_id),
            )
            conn.commit()
        logger.info("异步任务完成: %s status=%s reply=%d chars",
                     task_id, record["status"], len(reply))
        return True

    def lookup(self, task_id: str) -> Optional[dict]:
        with self._lock:
            record = self._tasks.get(task_id)
            if not record:
                return None
            return {
                "task_id": record["task_id"],
                "status": record["status"],
                "reply": record.get("reply", ""),
                "audio_b64": record.get("audio_b64", ""),
                "chat_id": record.get("chat_id", 0),
                "error": record.get("error", ""),
            }

    def owner_of(self, task_id: str) -> Optional[int]:
        """返回异步任务的创建者 uid，不存在则 None（用于归属校验）。"""
        with self._lock:
            record = self._tasks.get(task_id)
            if not record:
                return None
            return record.get("user_id", 0)

    def cleanup_stale(self, max_age_hours: int = 24) -> int:
        cutoff = datetime.now()
        removed = 0
        with self._lock:
            stale = []
            for tid, record in list(self._tasks.items()):
                created = record.get("created_at", "")
                if created:
                    try:
                        dt = datetime.fromisoformat(created)
                        if (cutoff - dt).total_seconds() > max_age_hours * 3600:
                            stale.append(tid)
                    except (ValueError, TypeError):
                        pass
            for tid in stale:
                del self._tasks[tid]
                removed += 1
        if self._db:
            conn = self._db._get_connection()
            conn.execute(
                "DELETE FROM async_tasks WHERE created_at < datetime('now', ?)",
                (f"-{max_age_hours} hours",),
            )
            conn.commit()
        if removed:
            logger.info("清理 %d 条过期异步任务", removed)
        return removed
