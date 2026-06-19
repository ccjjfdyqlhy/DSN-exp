# maintenance/system.py
# 服务器维护核心系统 — 三态状态机 + 调度器 + 任务执行器

from __future__ import annotations

import bisect
import logging
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Callable, Optional

import maintenance.config as config
from maintenance.state import ServerState, ServerStateMachine
from maintenance.clock import MaintenanceClock
from maintenance.tracker import ActivityTracker
from maintenance.tasks import (
    MaintenanceTask, TaskProgress,
    BackupTask, PersonalityOptimizeTask, LogCleanupTask,
)

logger = logging.getLogger("maintenance.system")


class MaintenanceSystem:
    """
    服务器维护核心系统。

    管理服务器三态（ready/maint/standby），
    调度后台维护任务（记忆整理、人格蒸馏等），
    追踪用户活跃度以预测空闲窗口。

    用法:
        ms = MaintenanceSystem(db=db, v3=personality_v3)
        ms.start()
    """

    def __init__(self, db=None, v3=None, engine=None, card_id: str = "exa"):
        self.state = ServerStateMachine()
        self.tracker = ActivityTracker(db=db)
        self._next_maint_at = None

        self._task_executor = TaskExecutor()
        self._on_maintenance_start: list[Callable] = []
        self._on_maintenance_done: list[Callable] = []
        self._on_maintenance_progress: list[Callable] = []
        self._shutdown_flag = threading.Event()

        self._register_builtin_tasks(db, v3, engine, card_id)
        self.clock = MaintenanceClock(self._on_tick)

    def _register_builtin_tasks(self, db, v3, engine, card_id):
        self._task_executor.register(BackupTask())
        self._task_executor.register(PersonalityOptimizeTask(v3=v3, card_id=card_id))
        self._task_executor.register(LogCleanupTask())

    # ── 生命周期 ──

    def start(self) -> None:
        self.tracker.load()
        self.clock.start()
        logger.info("维护系统已启动 (strategy=%s)", config.SCHEDULE_STRATEGY)

    def stop(self) -> None:
        self._backup_on_shutdown()
        self.clock.stop()
        self.tracker.save()
        logger.info("维护系统已停止")

    def shutdown(self) -> None:
        self.stop()
        self._shutdown_flag.set()

    # ── 活跃度记录 ──

    def record_user_request(self) -> None:
        self.tracker.record_request()
        if self.state.state == ServerState.STANDBY:
            self._wake_from_standby()

    # ── 时钟 tick ──

    def _on_tick(self) -> None:
        if self.state.state == ServerState.READY:
            if self._should_start_maintenance():
                self._begin_maintenance()
                return
            idle_min = self.tracker.minutes_since_last_request()
            if config.IDLE_TIMEOUT_MINUTES > 0 and idle_min >= config.IDLE_TIMEOUT_MINUTES:
                self._enter_standby()

    # ── 调度决策 ──

    def _should_start_maintenance(self) -> bool:
        now = datetime.now()

        # 手动设定时间优先
        if self._next_maint_at is not None and now >= self._next_maint_at:
            self._next_maint_at = None
            return True

        hour, minute = now.hour, now.minute

        if config.SCHEDULE_STRATEGY == "fixed":
            return hour == config.FIXED_HOUR and minute == 0

        if config.SCHEDULE_STRATEGY == "predictive":
            idle_min = self.tracker.minutes_since_last_request()
            user_idle = idle_min >= config.PREDICTIVE_IDLE_TRIGGER_MINUTES
            if not user_idle:
                return False

            total = self.tracker.total_requests()
            if total < config.PREDICTIVE_MIN_DATA_SAMPLES:
                return False

            window = self.tracker.best_idle_window(
                min_free_hours=config.PREDICTIVE_MIN_FREE_HOURS,
                max_hour=config.PREDICTIVE_MAX_HOUR,
            )
            in_window = window is not None and window[0] <= hour < window[1] if window else False

            prob = self.tracker.idle_probability(hour, minute)
            return in_window or prob > 0.85

        return False

    # ── 状态转换 ──

    def _begin_maintenance(self) -> None:
        if not self.state.transition(ServerState.MAINTENANCE):
            return
        logger.info("开始维护流程...")
        for cb in self._on_maintenance_start:
            try:
                cb()
            except Exception:
                logger.exception("maintenance_start 回调异常")

        def _run():
            try:
                results = self._task_executor.run_all(self._progress_sink)
                self._finish_maintenance(results)
            except Exception as e:
                logger.exception("维护流程异常")
                self._finish_maintenance([{"success": False, "error": str(e), "task": "system"}])

        t = threading.Thread(target=_run, daemon=True, name="maint-worker")
        t.start()

    def _progress_sink(self, task: MaintenanceTask, progress: TaskProgress) -> None:
        for cb in self._on_maintenance_progress:
            try:
                cb(task, progress)
            except Exception:
                logger.exception("maintenance_progress 回调异常")

    def _finish_maintenance(self, results: list[dict]) -> None:
        success_count = sum(1 for r in results if r.get("success"))
        logger.info("维护完成: %d/%d 成功", success_count, len(results))
        self.tracker.save()
        self.state.transition(ServerState.READY)
        for cb in self._on_maintenance_done:
            try:
                cb(results)
            except Exception:
                logger.exception("maintenance_done 回调异常")

    def _enter_standby(self) -> None:
        if not self.state.transition(ServerState.STANDBY):
            return
        logger.info("服务器进入待机模式（无请求 ≥ %d 分钟）", config.IDLE_TIMEOUT_MINUTES)
        self._backup_on_standby()

    def _wake_from_standby(self) -> None:
        self.state.transition(ServerState.READY)
        logger.info("服务器从待机模式恢复")

    def _backup_on_standby(self) -> None:
        """待机时异步备份关键文件"""
        task = BackupTask()
        def _run():
            try:
                result = task.run(lambda _: None)
                logger.info("待机备份完成: %s", result.get("stats", {}).get("dir", ""))
            except Exception as e:
                logger.error("待机备份失败: %s", e)
        t = threading.Thread(target=_run, daemon=True, name="standby-backup")
        t.start()

    def _backup_on_shutdown(self) -> None:
        """关闭时同步备份关键文件"""
        try:
            task = BackupTask()
            result = task.run(lambda _: None)
            logger.info("关闭备份完成: %s", result.get("stats", {}).get("dir", ""))
        except Exception as e:
            logger.error("关闭备份失败: %s", e)

    # ── 回调注册（供 frontend_bridge/api 使用） ──

    def on_maintenance_start(self, cb: Callable) -> None:
        self._on_maintenance_start.append(cb)

    def on_maintenance_progress(self, cb: Callable) -> None:
        self._on_maintenance_progress.append(cb)

    def on_maintenance_done(self, cb: Callable) -> None:
        self._on_maintenance_done.append(cb)

    # ── 主动触发 ──

    def trigger_maintenance(self) -> bool:
        if self.state.state != ServerState.READY:
            return False
        self._begin_maintenance()
        return True

    def trigger_standby(self) -> bool:
        if self.state.state != ServerState.READY:
            return False
        self._enter_standby()
        return True


class TaskExecutor:
    """
    按优先级顺序执行所有注册的维护任务。
    每个任务在独立线程中运行，通过 reporter 回调更新进度。
    任何任务失败不阻断后续任务。
    """

    def __init__(self):
        self._tasks: list[MaintenanceTask] = []

    def register(self, task: MaintenanceTask) -> None:
        bisect.insort(self._tasks, task, key=lambda t: t.priority)
        logger.debug("注册维护任务: %s (priority=%d)", task.name, task.priority)

    def run_all(self, progress_sink: Callable) -> list[dict]:
        results = []
        for task in self._tasks:
            def _reporter(p: TaskProgress):
                progress_sink(task, p)
            try:
                logger.info("开始任务: %s", task.name)
                result = task.run(_reporter)
                if not isinstance(result, dict):
                    result = {"result": result}
                result["task"] = task.name
                result.setdefault("success", True)
                results.append(result)
                logger.info("任务完成: %s (success=%s)", task.name, result.get("success"))
            except Exception as e:
                logger.error("任务异常: %s: %s", task.name, e)
                results.append({"task": task.name, "success": False, "error": str(e)})
        return results
