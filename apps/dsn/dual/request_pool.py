# dual/request_pool.py
# 共享请求池 — 跟踪所有活跃的主模型 agent loop 任务

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("RequestPool")


@dataclass
class RequestEntry:
    task_id: str
    user_id: int
    chat_id: int
    message: str
    status: str = "running"          # running | completed | failed | cancelled
    current_step: int = 0
    max_steps: int = 5
    progress_text: str = ""
    intermediate_replies: list[str] = field(default_factory=list)
    final_reply: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def short_id(self) -> str:
        return self.task_id[:8]


class RequestPool:
    """进程内单例，线程安全。Instant 和主模型共享。"""

    _instance: Optional["RequestPool"] = None

    @classmethod
    def get_instance(cls) -> "RequestPool":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._entries: dict[str, RequestEntry] = {}
        self._lock = threading.Lock()

    def add(self, user_id: int, chat_id: int, message: str,
            max_steps: int = 5) -> str:
        task_id = f"dual_{uuid.uuid4().hex[:16]}"
        entry = RequestEntry(
            task_id=task_id, user_id=user_id, chat_id=chat_id,
            message=message, max_steps=max_steps,
        )
        with self._lock:
            self._entries[task_id] = entry
        logger.info("RequestPool: 添加任务 %s (user=%d, msg=%s)",
                    entry.short_id, user_id, message[:50])
        return task_id

    def update(self, task_id: str, **fields) -> None:
        with self._lock:
            entry = self._entries.get(task_id)
            if not entry:
                return
            for k, v in fields.items():
                if hasattr(entry, k):
                    setattr(entry, k, v)
            entry.updated_at = time.time()

    def complete(self, task_id: str, final_reply: str,
                 status: str = "completed") -> None:
        with self._lock:
            entry = self._entries.get(task_id)
            if not entry:
                return
            entry.status = status
            entry.final_reply = final_reply
            entry.updated_at = time.time()
        # 清理：5分钟后移除已完成的任务
        threading.Timer(300.0, self._remove, args=(task_id,)).start()

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            entry = self._entries.get(task_id)
            if not entry:
                return False
            entry.status = "cancelled"
            entry.updated_at = time.time()
        logger.info("RequestPool: 任务 %s 已取消", entry.short_id)
        return True

    def _remove(self, task_id: str) -> None:
        with self._lock:
            self._entries.pop(task_id, None)

    def get(self, task_id: str) -> Optional[RequestEntry]:
        with self._lock:
            return self._entries.get(task_id)

    def get_active(self, user_id: int) -> list[RequestEntry]:
        """返回该用户所有未完成的任务"""
        with self._lock:
            return [
                e for e in self._entries.values()
                if e.user_id == user_id and e.status == "running"
            ]

    def get_all(self, user_id: int) -> list[RequestEntry]:
        """返回该用户所有任务（含已完成，短期内）"""
        with self._lock:
            return [
                e for e in self._entries.values()
                if e.user_id == user_id
            ]

    def summarize_for_prompt(self, user_id: int) -> str:
        """生成请求池状态文本，供 Instant 模型 system prompt 注入。
        不暴露任务ID，只描述内容和状态。"""
        entries = self.get_all(user_id)
        if not entries:
            return "当前没有正在进行的任务。"

        lines = []
        for i, e in enumerate(entries, 1):
            status_label = {
                "running": "运行中",
                "completed": "已完成",
                "failed": "失败",
                "cancelled": "已取消",
            }.get(e.status, e.status)
            parts = [f"{i}. [{status_label}] \"{e.message[:60]}\""]
            if e.status == "running":
                parts.append(f" (进行中)")
            elif e.status == "completed" and e.final_reply:
                parts.append(f" → {e.final_reply[:80]}")
            lines.append("".join(parts))
        return "当前任务状态：\n" + "\n".join(lines)
