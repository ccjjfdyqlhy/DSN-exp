# infra/tasks/async_store.py
# AsyncTaskStore — 后台异步任务的进程内状态存储。
#
# 用于"长任务后台执行、前端轮询结果"的模式。
# 线程安全；可与 TaskExecutorRegistry.submit 配合，也可独立使用。

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class AsyncTaskRecord:
    id: str
    kind: str = ""
    status: str = "pending"          # pending | running | completed | error
    result: Any = None
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    meta: dict = field(default_factory=dict)

    @property
    def done(self) -> bool:
        return self.status in ("completed", "error")


class AsyncTaskStore:
    """线程安全的异步任务状态存储。"""

    def __init__(self, *, ttl: Optional[float] = None):
        """ttl: 记录保留秒数。None 表示永不过期。

        修复说明（2026-10）：ttl 参数此前只是被保存到 self._ttl 就再也没被读取过
        ——「声明了但完全不生效」。现在在 get/list 时按 TTL 惰性清理，
        并在超限时整体清理一次，避免长跑进程里记录无限增长。
        """
        self._records: dict[str, AsyncTaskRecord] = {}
        self._lock = threading.RLock()
        self._ttl = ttl

    def _prune_locked(self) -> None:
        """清理超过 TTL 的记录（调用方必须持有 self._lock）。"""
        if not self._ttl:
            return
        cutoff = time.time() - float(self._ttl)
        expired = [
            tid for tid, rec in self._records.items()
            if float(getattr(rec, "created_at", 0) or 0) < cutoff
        ]
        for tid in expired:
            self._records.pop(tid, None)

    def create(self, kind: str = "", **meta) -> AsyncTaskRecord:
        rec = AsyncTaskRecord(id=uuid.uuid4().hex, kind=kind, meta=meta)
        with self._lock:
            self._records[rec.id] = rec
        return rec

    def get(self, task_id: str) -> Optional[AsyncTaskRecord]:
        with self._lock:
            self._prune_locked()
            return self._records.get(task_id)

    def update(self, task_id: str, *, status: Optional[str] = None,
               result: Any = None, error: Optional[str] = None) -> Optional[AsyncTaskRecord]:
        with self._lock:
            rec = self._records.get(task_id)
            if rec is None:
                return None
            if status is not None:
                rec.status = status
            if result is not None:
                rec.result = result
            if error is not None:
                rec.error = error
            rec.updated_at = time.time()
            return rec

    def complete(self, task_id: str, *, result: Any = None,
                 error: Optional[str] = None) -> Optional[AsyncTaskRecord]:
        status = "error" if error else "completed"
        return self.update(task_id, status=status, result=result, error=error)

    def pending(self) -> list[AsyncTaskRecord]:
        with self._lock:
            return [r for r in self._records.values() if not r.done]

    def snapshot(self) -> list[AsyncTaskRecord]:
        with self._lock:
            return list(self._records.values())

    def count(self) -> int:
        with self._lock:
            return len(self._records)
