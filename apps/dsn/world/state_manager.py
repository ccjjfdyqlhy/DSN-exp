# world/state_manager.py
# WorldStateManager — 后台线程持续刷新世界快照

from __future__ import annotations

import copy
import logging
import threading
import time
from typing import Optional

from .engine import WorldEngine

logger = logging.getLogger("WorldStateManager")


class WorldStateManager:
    """
    后台线程管理器。
    按 update_interval 持续调用 engine 刷新世界状态，
    用户交互时通过 get_snapshot() 获取最新快照，无阻塞。
    """

    def __init__(self, engine: WorldEngine, update_interval: float = 60.0):
        self._engine = engine
        self._interval = max(1.0, update_interval)
        self._lock = threading.RLock()
        self._snapshot: Optional[dict] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        # Initial snapshot
        self._snapshot = self._engine.get_full_state()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="world-state-mgr")
        self._thread.start()
        logger.info("WorldStateManager 已启动, 刷新间隔=%.1fs", self._interval)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        logger.info("WorldStateManager 已停止")

    def get_snapshot(self) -> dict:
        with self._lock:
            if self._snapshot is None:
                self._snapshot = self._engine.get_full_state()
            return copy.deepcopy(self._snapshot)

    def _loop(self) -> None:
        while self._running:
            try:
                self._engine.tick()
                self._engine.poll_events()
                with self._lock:
                    self._snapshot = self._engine.get_full_state()
            except Exception:
                logger.exception("WorldStateManager 循环异常")
            time.sleep(self._interval)
