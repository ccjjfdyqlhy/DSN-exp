# dual/instant_registry.py
# Instant 上下文注册表 — 管理 (user_id, chat_id) → InstantContext 映射，LRU 回收

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from .instant_context import InstantContext

logger = logging.getLogger("InstantRegistry")


class InstantContextRegistry:
    """全局单例。管理持久 Instant 上下文，带 LRU 超时回收。"""

    _instance: Optional["InstantContextRegistry"] = None

    @classmethod
    def get_instance(cls) -> "InstantContextRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, idle_timeout: int = 1800):
        """idle_timeout: 无活动后回收时间(秒)，默认30分钟"""
        self._contexts: dict[tuple[int, int], InstantContext] = {}
        self._idle_timeout = idle_timeout
        self._lock = threading.Lock()
        # 后台清理线程
        self._stop = threading.Event()
        self._cleaner = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleaner.start()

    def get_or_create(self, user_id: int, chat_id: int,
                      model_name: str = "", base_url: str = "",
                      summary_model=None) -> InstantContext:
        key = (user_id, chat_id)
        with self._lock:
            ctx = self._contexts.get(key)
            if ctx is None:
                ctx = InstantContext(
                    user_id=user_id, chat_id=chat_id,
                    model_name=model_name, base_url=base_url,
                    summary_model=summary_model,
                )
                self._contexts[key] = ctx
                logger.info("InstantRegistry: 创建上下文 user=%d chat=%d", user_id, chat_id)
            ctx._last_access = time.time()
            return ctx

    def get(self, user_id: int, chat_id: int) -> Optional[InstantContext]:
        key = (user_id, chat_id)
        with self._lock:
            ctx = self._contexts.get(key)
            if ctx:
                ctx._last_access = time.time()
            return ctx

    def remove(self, user_id: int, chat_id: int) -> None:
        key = (user_id, chat_id)
        with self._lock:
            self._contexts.pop(key, None)

    def _cleanup_loop(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(60)
            now = time.time()
            with self._lock:
                stale = [
                    k for k, ctx in self._contexts.items()
                    if now - ctx._last_access > self._idle_timeout
                ]
                for k in stale:
                    logger.info("InstantRegistry: LRU 回收 user=%d chat=%d", k[0], k[1])
                    self._contexts.pop(k, None)

    def shutdown(self) -> None:
        self._stop.set()
