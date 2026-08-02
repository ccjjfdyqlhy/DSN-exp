# maintenance/system.py
# 服务器维护核心系统 — 三态状态机 + 调度器 + 任务执行器

from __future__ import annotations

import bisect
import json
import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

import maintenance.config as config
from maintenance.state import ServerState, ServerStateMachine
from maintenance.clock import MaintenanceClock
from maintenance.tracker import ActivityTracker
from maintenance.tasks import (
    MaintenanceTask, TaskProgress,
    BackupTask, PersonalityOptimizeTask, LogCleanupTask, AccountCheckTask,
)

logger = logging.getLogger("maintenance.system")

_TASK_CONFIG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".dsn", "maintenance_tasks.json",
)


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
        self._maint_interval_seconds: Optional[int] = None

        self._task_executor = TaskExecutor()
        self._on_maintenance_start: list[Callable] = []
        self._on_maintenance_done: list[Callable] = []
        self._on_maintenance_progress: list[Callable] = []
        self._shutdown_flag = threading.Event()

        self._engine = engine
        self._register_builtin_tasks(db, v3, engine, card_id)
        self.clock = MaintenanceClock(self._on_tick)

    def _register_builtin_tasks(self, db, v3, engine, card_id):
        self._v3 = v3
        self._card_id = card_id
        self._task_executor.register(BackupTask())
        self._task_executor.register(PersonalityOptimizeTask(v3=v3, card_id=card_id))
        self._task_executor.register(LogCleanupTask())
        self._load_task_config()
        self._load_schedule_config()

    def _builtin_task(self, key: str, account_id: str = "") -> Optional[MaintenanceTask]:
        """按名称/别名创建内置任务实例；未知名称返回 None。"""
        key = key.strip()
        if key in ("backup", "系统备份"):
            return BackupTask()
        if key in ("personality", "人格蒸馏", "personality_optimize"):
            return PersonalityOptimizeTask(v3=self._v3, card_id=self._card_id)
        if key in ("logcleanup", "日志清理", "log_cleanup"):
            return LogCleanupTask()
        if key in ("account_check", "账号检查"):
            if not account_id:
                return None
            return AccountCheckTask(account_id=account_id)
        # 兼容持久化后的任务名 "账号检查:<账号>"
        if key.startswith("账号检查:"):
            return AccountCheckTask(account_id=key.split(":", 1)[1])
        return None

    def available_tasks(self) -> list[dict]:
        """列出可用的内置任务类型。"""
        return [
            {"name": "系统备份", "aliases": "backup", "requires": "",
             "description": "备份关键文件到 ~/.dsn_backups/"},
            {"name": "人格蒸馏", "aliases": "personality", "requires": "",
             "description": "导入素材并触发 V3 人格蒸馏"},
            {"name": "日志清理", "aliases": "logcleanup", "requires": "",
             "description": "清理 30 天前的旧日志"},
            {"name": "账号检查", "aliases": "account_check", "requires": "account_id",
             "description": "测试指定 API 账号连通性 (需 --account <账号名>)"},
        ]

    # ── 任务安排管理 ──

    def list_tasks(self) -> list[dict]:
        result = []
        for t in self._task_executor.list():
            item = {"name": t.name, "priority": t.priority}
            if isinstance(t, AccountCheckTask):
                item["account_id"] = t.account_id
            result.append(item)
        return result

    def add_task(self, name: str, priority: int | None = None,
                 account_id: str = "") -> tuple[bool, str]:
        task = self._builtin_task(name, account_id=account_id)
        if task is None:
            return False, (f"未知任务: {name} "
                           f"(可用: backup/系统备份, personality/人格蒸馏, "
                           f"logcleanup/日志清理, account_check/账号检查)")
        if self._task_executor.has(task.name):
            return False, f"任务 '{task.name}' 已存在"
        if priority is not None:
            task.priority = int(priority)
        self._task_executor.register(task)
        self._save_task_config()
        logger.info("维护任务已添加: %s (priority=%d)", task.name, task.priority)
        return True, f"任务 '{task.name}' 已添加 (priority={task.priority})"

    def remove_task(self, name: str) -> tuple[bool, str]:
        removed = self._task_executor.unregister(name)
        if not removed:
            return False, f"任务 '{name}' 不存在"
        self._save_task_config()
        logger.info("维护任务已移除: %s", name)
        return True, f"任务 '{name}' 已移除"

    def _save_task_config(self) -> None:
        try:
            tasks = []
            for t in self._task_executor.list():
                item = {"name": t.name, "enabled": True, "priority": t.priority}
                if isinstance(t, AccountCheckTask):
                    item["account_id"] = t.account_id
                tasks.append(item)
            p = Path(_TASK_CONFIG_FILE)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"tasks": tasks}, ensure_ascii=False, indent=2),
                         encoding="utf-8")
        except Exception as e:
            logger.error("保存维护任务配置失败: %s", e)

    def _load_task_config(self) -> None:
        try:
            p = Path(_TASK_CONFIG_FILE)
            if not p.exists():
                self._save_task_config()
                return
            data = json.loads(p.read_text(encoding="utf-8"))
            desired: dict[str, dict] = {}
            for item in data.get("tasks", []):
                name = item.get("name", "")
                if not name:
                    continue
                desired[name] = {
                    "enabled": bool(item.get("enabled", True)),
                    "priority": item.get("priority"),
                    "account_id": item.get("account_id", ""),
                }
            # 对账：当前注册的任务不在配置中 → 移除
            for t in self._task_executor.list():
                if t.name not in desired:
                    self._task_executor.unregister(t.name)
            # 按配置增补或调整
            for name, spec in desired.items():
                task = self._builtin_task(name, account_id=spec.get("account_id", ""))
                if task is None:
                    continue
                if spec["enabled"]:
                    if self._task_executor.has(task.name):
                        if spec["priority"] is not None:
                            self._task_executor.set_priority(task.name, spec["priority"])
                    else:
                        if spec["priority"] is not None:
                            task.priority = int(spec["priority"])
                        self._task_executor.register(task)
                else:
                    self._task_executor.unregister(task.name)
        except Exception as e:
            logger.error("加载维护任务配置失败: %s", e)

    # ── 手动重复周期管理 ──

    def get_maint_interval(self) -> Optional[int]:
        return self._maint_interval_seconds

    def set_maint_interval(self, seconds: int, start_now: bool = False) -> tuple[bool, str]:
        """设置手动维护重复周期。start_now=True 时立刻触发一次，否则从下一个周期点开始。"""
        if seconds is None or seconds <= 0:
            return False, "周期必须是正整数秒数"
        self._maint_interval_seconds = int(seconds)
        self._next_maint_at = datetime.now() if start_now else datetime.now() + timedelta(seconds=int(seconds))
        self._save_schedule_config()
        logger.info("设置维护重复周期: 每 %d 秒", int(seconds))
        return True, f"已设置维护重复周期: 每 {int(seconds)} 秒"

    def clear_maint_interval(self) -> tuple[bool, str]:
        """清除手动维护重复周期，恢复自动策略。"""
        self._maint_interval_seconds = None
        self._next_maint_at = None
        self._save_schedule_config()
        logger.info("已清除维护重复周期")
        return True, "已清除维护重复周期，恢复自动调度策略"

    def _save_schedule_config(self) -> None:
        """将手动重复周期写入任务配置文件，重启后恢复。"""
        try:
            p = Path(_TASK_CONFIG_FILE)
            if not p.exists():
                return
            data = json.loads(p.read_text(encoding="utf-8"))
            data["maint_interval_seconds"] = self._maint_interval_seconds
            p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error("保存维护周期配置失败: %s", e)

    def _load_schedule_config(self) -> None:
        """从任务配置文件恢复手动重复周期。"""
        try:
            p = Path(_TASK_CONFIG_FILE)
            if not p.exists():
                return
            data = json.loads(p.read_text(encoding="utf-8"))
            val = data.get("maint_interval_seconds")
            if val:
                self._maint_interval_seconds = int(val)
                # 从启动时刻开始计算下一个周期点
                self._next_maint_at = datetime.now() + timedelta(seconds=int(val))
                logger.info("恢复维护重复周期: 每 %d 秒", int(val))
        except Exception as e:
            logger.error("加载维护周期配置失败: %s", e)

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
                self._drain_hibernate()
                self._begin_maintenance()
                return
            if self._should_drain_hibernate():
                self._drain_hibernate()
            idle_min = self.tracker.minutes_since_last_request()
            if config.IDLE_TIMEOUT_MINUTES > 0 and idle_min >= config.IDLE_TIMEOUT_MINUTES:
                self._enter_standby()
        elif self.state.state == ServerState.STANDBY:
            self._drain_hibernate()

    # ── 调度决策 ──

    def _should_start_maintenance(self) -> bool:
        now = datetime.now()

        # 手动设定时间优先
        if self._next_maint_at is not None and now >= self._next_maint_at:
            if self._maint_interval_seconds:
                # 重复周期：推进到下一个周期点（可能错过多个周期）
                while self._next_maint_at <= now:
                    self._next_maint_at += timedelta(seconds=self._maint_interval_seconds)
            else:
                self._next_maint_at = None
            return True

        hour, minute = now.hour, now.minute

        # 设置了手动重复周期时，由周期调度控制，抑制自动策略
        if self._maint_interval_seconds:
            return False

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

    def _should_drain_hibernate(self) -> bool:
        """判断当前是否应该排空休眠队列（仅限预测的低负载窗口）。"""
        hour = datetime.now().hour
        # 非 READY 状态（STANDBY/MAINTENANCE）时全部排空
        if self.state.state != ServerState.READY:
            return True
        # predictive 策略：结合历史预测
        if config.SCHEDULE_STRATEGY == "predictive":
            total = self.tracker.total_requests()
            if total >= config.PREDICTIVE_MIN_DATA_SAMPLES:
                window = self.tracker.best_idle_window(
                    min_free_hours=config.PREDICTIVE_MIN_FREE_HOURS,
                    max_hour=config.PREDICTIVE_MAX_HOUR,
                )
                in_window = window is not None and window[0] <= hour < window[1]
                prob = self.tracker.idle_probability(hour, 0)
                if in_window or prob > 0.85:
                    return True
        # 默认窗口：0:00 ~ FIXED_HOUR（凌晨 4:00）
        return hour < config.FIXED_HOUR

    def _drain_hibernate(self) -> int:
        """排空休眠队列中的挂起任务。"""
        if self._engine is None:
            return 0
        hibernate = getattr(self._engine, "_hibernate", None)
        if hibernate is None or hibernate.size() == 0:
            return 0
        n = hibernate.drain(max_count=10)
        if n:
            logger.info("休眠队列排空 %d 个任务（空闲窗口）", n)
        return n

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
        self._lock = threading.Lock()

    def register(self, task: MaintenanceTask) -> None:
        with self._lock:
            bisect.insort(self._tasks, task, key=lambda t: t.priority)
        logger.debug("注册维护任务: %s (priority=%d)", task.name, task.priority)

    def unregister(self, name: str) -> bool:
        with self._lock:
            new = [t for t in self._tasks if t.name != name]
            removed = len(new) != len(self._tasks)
            self._tasks = new
        if removed:
            logger.debug("移除维护任务: %s", name)
        return removed

    def has(self, name: str) -> bool:
        with self._lock:
            return any(t.name == name for t in self._tasks)

    def list(self) -> list[MaintenanceTask]:
        with self._lock:
            return list(self._tasks)

    def set_priority(self, name: str, priority: int) -> bool:
        with self._lock:
            for t in self._tasks:
                if t.name == name:
                    t.priority = int(priority)
                    break
            else:
                return False
            self._tasks.sort(key=lambda t: t.priority)
        return True

    def run_all(self, progress_sink: Callable) -> list[dict]:
        results = []
        for task in self.list():
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
