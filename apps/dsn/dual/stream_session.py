# dual/stream_session.py
# SSE 流会话 — 协调 Instant 与主模型之间的队列通信

from __future__ import annotations

import logging
import queue
import threading
import uuid
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("StreamSession")


@dataclass
class StreamSession:
    """一条 SSE 流的会话状态。"""
    stream_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    user_id: int = 0
    chat_id: int = 0
    active: bool = True

    # 用户插话队列 (interject endpoint → SSE 生成器)
    interject_queue: "queue.Queue[Optional[str]]" = field(default_factory=queue.Queue)
    # 主模型事件队列 (主模型线程 → SSE 生成器)
    progress_queue: "queue.Queue[Optional[dict]]" = field(default_factory=queue.Queue)

    # 取消控制
    cancel_events: dict[str, threading.Event] = field(default_factory=dict)
    # 主模型线程的 asyncio loop 引用 (用于取消)
    main_loops: dict[str, object] = field(default_factory=dict)

    def get_active_tasks(self) -> list[str]:
        """返回当前活跃的 task_id 列表"""
        return [tid for tid, ev in self.cancel_events.items() if not ev.is_set()]

    def set_cancel(self, task_id: str) -> None:
        """标记取消某个任务"""
        ev = self.cancel_events.get(task_id)
        if ev:
            ev.set()
        loop = self.main_loops.get(task_id)
        if loop and hasattr(loop, "is_running") and loop.is_running():
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                logger.warning("取消 loop 失败", exc_info=True)

    def close(self) -> None:
        self.active = False
        # 取消所有活跃任务
        for tid in list(self.cancel_events):
            self.set_cancel(tid)


class StreamRegistry:
    """管理活跃 SSE 流的单例。"""

    _instance: Optional["StreamRegistry"] = None

    @classmethod
    def get_instance(cls) -> "StreamRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._sessions: dict[str, StreamSession] = {}
        self._by_user_chat: dict[tuple[int, int], str] = {}
        self._lock = threading.Lock()

    def create(self, user_id: int, chat_id: int) -> StreamSession:
        """创建新流会话，如果同一 user+chat 已有活跃流则先关闭旧的。"""
        key = (user_id, chat_id)
        with self._lock:
            old_id = self._by_user_chat.get(key)
            if old_id:
                old = self._sessions.get(old_id)
                if old:
                    old.close()
                self._sessions.pop(old_id, None)
                self._by_user_chat.pop(key, None)

            session = StreamSession(user_id=user_id, chat_id=chat_id)
            self._sessions[session.stream_id] = session
            self._by_user_chat[key] = session.stream_id
        logger.info("StreamRegistry: 创建流 %s (user=%d, chat=%d)",
                    session.stream_id, user_id, chat_id)
        return session

    def get(self, stream_id: str) -> Optional[StreamSession]:
        with self._lock:
            return self._sessions.get(stream_id)

    def get_by_user_chat(self, user_id: int, chat_id: int) -> Optional[StreamSession]:
        with self._lock:
            sid = self._by_user_chat.get((user_id, chat_id))
            if not sid:
                return None
            session = self._sessions.get(sid)
            if session and not session.active:
                return None
            return session

    def close(self, stream_id: str) -> None:
        with self._lock:
            session = self._sessions.pop(stream_id, None)
            if session:
                session.close()
                key = (session.user_id, session.chat_id)
                if self._by_user_chat.get(key) == stream_id:
                    self._by_user_chat.pop(key, None)
