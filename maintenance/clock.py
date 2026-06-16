# maintenance/clock.py
# 内部时钟 — 每分钟 tick 一次，触发调度检查

from __future__ import annotations

import logging
import threading
import time
import maintenance.config as config

logger = logging.getLogger("maintenance.clock")


class MaintenanceClock:
    """
    守护线程时钟。
    每秒 tick，触发回调（如检查预定维护、检查空闲）。
    """

    def __init__(self, tick_callback):
        """
        :param tick_callback: 每次 tick 时调用的无参数函数
        """
        self._tick_cb = tick_callback
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._interval = config.SCHEDULE_CHECK_INTERVAL

    def start(self) -> None:
        if self._thread is not None:
            logger.warning("时钟已在运行")
            return
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="maint-clock")
        self._thread.start()
        logger.info("维护时钟已启动 (interval=%ds)", self._interval)

    def stop(self) -> None:
        self._stop.set()
        logger.info("维护时钟已停止")

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._tick_cb()
            except Exception:
                logger.exception("时钟 tick 回调异常")
