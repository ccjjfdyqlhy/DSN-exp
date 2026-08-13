# skills/system/tools/task_tools.py

import json
import locale
import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from apps.dsn.tasks import TaskType

logger = logging.getLogger("skill.system")

_ENCODING = locale.getpreferredencoding(False)


class TaskTools:
    _ctx = {}

    @classmethod
    def set_context(cls, task_manager=None, db=None):
        cls._ctx["task_manager"] = task_manager
        cls._ctx["db"] = db

    def __init__(self):
        pass

    def _mgr(self):
        mgr = self._ctx.get("task_manager")
        if not mgr:
            raise RuntimeError("TaskManager 未注入")
        return mgr

    def _uid(self):
        return self._ctx.get("_uid", 0)

    def _cid(self):
        return self._ctx.get("_cid", 0)

    # ── 排期任务（走 TaskManager 持久化） ──

    def create_reminder(self, text: str, time: str) -> dict:
        mgr = self._mgr()
        scheduled = datetime.fromisoformat(time)
        tid = mgr.create_task(
            task_type=TaskType.REMINDER, user_id=self._uid(), chat_id=self._cid(),
            params={"text": text, "time": time},
            priority=1, scheduled_time=scheduled)
        logger.info("create_reminder: task_id=%s text=%s time=%s uid=%d cid=%d",
                     tid, text[:50], time, self._uid(), self._cid())
        return {"task_id": tid}

    def create_habit(self, text: str, time: str, interval: str) -> dict:
        mgr = self._mgr()
        scheduled = datetime.fromisoformat(time)
        interval_sec = self._parse_interval(interval)
        tid = mgr.create_task(
            task_type=TaskType.HABIT, user_id=self._uid(), chat_id=self._cid(),
            params={"text": text, "time": time, "interval": interval},
            priority=1, scheduled_time=scheduled,
            interval_seconds=interval_sec)
        return {"task_id": tid}

    def create_countdown(self, text: str, target: str) -> dict:
        mgr = self._mgr()
        scheduled = datetime.fromisoformat(target)
        tid = mgr.create_task(
            task_type=TaskType.COUNTDOWN, user_id=self._uid(), chat_id=self._cid(),
            params={"text": text, "target": target},
            priority=1, scheduled_time=scheduled)
        return {"task_id": tid}

    def create_daily_plan(self, trigger_time: str) -> dict:
        mgr = self._mgr()
        hour, minute = map(int, trigger_time.split(":"))
        now = datetime.now()
        scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if scheduled <= now:
            scheduled += timedelta(days=1)
        tid = mgr.create_task(
            task_type=TaskType.DAILY_PLAN, user_id=self._uid(), chat_id=self._cid(),
            params={"trigger_time": trigger_time},
            priority=1, scheduled_time=scheduled)
        return {"task_id": tid}

    def create_periodic(self, cron: str, text: str) -> dict:
        mgr = self._mgr()
        try:
            import croniter
            it = croniter.croniter(cron, datetime.now())
            next_time = it.get_next(datetime)
        except Exception:
            raise ValueError(f"无效 cron 表达式: {cron}")
        tid = mgr.create_task(
            task_type=TaskType.PERIODIC, user_id=self._uid(), chat_id=self._cid(),
            params={"cron": cron, "text": text},
            priority=1, scheduled_time=next_time)
        return {"task_id": tid}

    # ── 正计时（Stopwatch） ──

    def start_stopwatch(self, label: str = "") -> dict:
        """开始（或重置）正计时。每用户只能有一个正计时，若已存在则重置覆盖。"""
        mgr = self._mgr()
        result = mgr.start_stopwatch(self._uid(), label)
        result["message"] = "正计时已开始"
        return result

    def get_stopwatch(self) -> dict:
        """查询当前正计时的读数与状态（运行中/已暂停）。"""
        mgr = self._mgr()
        result = mgr.get_stopwatch(self._uid())
        if result.get("success"):
            state = "运行中" if result["status"] == "running" else "已暂停"
            result["message"] = f"当前正计时：{result['elapsed_text']}（{state}）"
        return result

    def pause_stopwatch(self) -> dict:
        """暂停当前正计时。"""
        mgr = self._mgr()
        result = mgr.pause_stopwatch(self._uid())
        if result.get("success"):
            if result.get("already_paused"):
                result["message"] = f"正计时已处于暂停状态：{result['elapsed_text']}"
            else:
                result["message"] = f"正计时已暂停：{result['elapsed_text']}"
        return result

    def resume_stopwatch(self) -> dict:
        """继续已暂停的正计时。"""
        mgr = self._mgr()
        result = mgr.resume_stopwatch(self._uid())
        if result.get("success"):
            if result.get("already_running"):
                result["message"] = f"正计时正在运行中：{result['elapsed_text']}"
            else:
                result["message"] = f"正计时已继续：{result['elapsed_text']}"
        return result

    def delete_stopwatch(self) -> dict:
        """删除当前正计时。"""
        mgr = self._mgr()
        result = mgr.delete_stopwatch(self._uid())
        if result.get("success"):
            result["message"] = "正计时已删除"
        return result

    # ── 查询提醒 ──

    def list_reminders(self, status: str = "pending") -> dict:
        """查询当前用户的所有提醒/习惯/倒计时任务。"""
        db = self._ctx.get("db")
        uid = self._uid()
        if not db:
            return {"reminders": [], "error": "数据库不可用"}

        from apps.dsn.tasks import TaskType, TaskStatus
        status_filter = status if status else TaskStatus.PENDING.value
        try:
            conn = db._get_connection()
            rows = conn.execute(
                "SELECT task_id, task_type, params, priority, scheduled_time, "
                "interval_seconds, skip_count, status, created_at FROM tasks "
                "WHERE user_id = ? AND task_type IN (?, ?, ?, ?, ?) AND status = ? "
                "ORDER BY scheduled_time ASC",
                (uid, TaskType.REMINDER.value, TaskType.HABIT.value,
                 TaskType.COUNTDOWN.value, TaskType.DAILY_PLAN.value,
                 TaskType.PERIODIC.value, status_filter),
            ).fetchall()
            reminders = []
            for r in rows:
                try:
                    params = json.loads(r["params"]) if r["params"] else {}
                except Exception:
                    params = {}
                reminders.append({
                    "task_id": r["task_id"],
                    "type": r["task_type"],
                    "text": params.get("text", ""),
                    "scheduled_time": r["scheduled_time"] or "",
                    "interval": r["interval_seconds"] or 0,
                    "status": r["status"],
                    "skip_count": r["skip_count"],
                })
            return {"reminders": reminders, "count": len(reminders)}
        except Exception as e:
            logger.error("list_reminders 失败: %s", e)
            return {"reminders": [], "error": str(e)}

    # ── 提醒生命周期：取消/跳过/完成（与 api/reminder.py 语义一致） ──

    def _get_reminder_task(self, task_id: str):
        """取回任务；校验存在性与归属。返回 (mgr, task) 或 (None, None)。"""
        mgr = self._mgr()
        task = mgr.tasks.get(task_id) if task_id else None
        if not task:
            return None, None
        if task.user_id != self._uid():
            return None, None
        return mgr, task

    def cancel_reminder(self, task_id: str) -> dict:
        """取消（删除）一条提醒/习惯/倒计时任务，不再触发。"""
        from apps.dsn.tasks import TaskStatus
        mgr, task = self._get_reminder_task(task_id)
        if not task:
            return {"success": False, "error": f"提醒任务不存在或无权操作: {task_id}"}
        task.status = TaskStatus.CANCELLED
        task.completed_at = datetime.now()
        mgr._save_task(task)
        logger.info("cancel_reminder: task_id=%s text=%s", task_id,
                    (task.params.get("text") or "")[:50])
        return {"success": True, "action": "cancelled", "task_id": task_id,
                "text": task.params.get("text", ""), "task_type": task.task_type.value}

    def skip_reminder(self, task_id: str) -> dict:
        """跳过一条提醒的本次触发（习惯任务会顺延到下一次）。"""
        from apps.dsn.tasks import TaskStatus
        mgr, task = self._get_reminder_task(task_id)
        if not task:
            return {"success": False, "error": f"提醒任务不存在或无权操作: {task_id}"}
        task.status = TaskStatus.SKIPPED
        task.skip_count += 1
        task.completed_at = datetime.now()
        mgr._save_task(task)
        next_time = None
        new_id = None
        if task.task_type == TaskType.HABIT and task.interval_seconds > 0:
            next_time = datetime.now() + timedelta(seconds=task.interval_seconds)
            new_id = mgr.create_task(
                task_type=TaskType.HABIT, user_id=self._uid(), chat_id=task.chat_id,
                params={"text": task.params.get("text", "")},
                priority=task.priority, scheduled_time=next_time,
                interval_seconds=task.interval_seconds)
        return {"success": True, "action": "skipped", "task_id": task_id,
                "text": task.params.get("text", ""), "task_type": task.task_type.value,
                "skip_count": task.skip_count,
                "next_scheduled": next_time.isoformat() if next_time else None,
                "next_task_id": new_id}

    def done_reminder(self, task_id: str) -> dict:
        """标记一条提醒为已完成（习惯任务会顺延到下一次）。"""
        from apps.dsn.tasks import TaskStatus
        mgr, task = self._get_reminder_task(task_id)
        if not task:
            return {"success": False, "error": f"提醒任务不存在或无权操作: {task_id}"}
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now()
        mgr._save_task(task)
        next_time = None
        new_id = None
        if task.task_type == TaskType.HABIT and task.interval_seconds > 0:
            next_time = datetime.now() + timedelta(seconds=task.interval_seconds)
            new_id = mgr.create_task(
                task_type=TaskType.HABIT, user_id=self._uid(), chat_id=task.chat_id,
                params={"text": task.params.get("text", "")},
                priority=task.priority, scheduled_time=next_time,
                interval_seconds=task.interval_seconds)
        return {"success": True, "action": "completed", "task_id": task_id,
                "text": task.params.get("text", ""), "task_type": task.task_type.value,
                "next_scheduled": next_time.isoformat() if next_time else None,
                "next_task_id": new_id}

    # ── 异步推理（走 TaskManager 持久化 + 立即执行） ──

    def create_reasoner(self, question: str, context: str = "") -> dict:
        mgr = self._mgr()
        tid = mgr.create_task(
            task_type=TaskType.REASONER, user_id=self._uid(), chat_id=self._cid(),
            params={"question": question, "context": context},
            priority=1)
        mgr.execute_task(tid)
        return {"task_id": tid}

    # ── 动作执行（直接执行，不走 TaskManager/DB） ──

    def execute_action(self, action_type: str, content: str,
                        file_path: str = "", overwrite: bool = False,
                        pattern: str = "", replacement: str = "") -> dict:
        """同步执行 shell/python/文件操作，阻塞等待结果。"""
        try:
            if action_type == "shell":
                return self._run_shell(content)
            elif action_type == "python":
                return self._run_python(content)
            elif action_type == "write_file":
                return self._do_write_file(file_path, content, overwrite)
            elif action_type == "edit_file":
                return self._do_edit_file(file_path, pattern, replacement)
            else:
                return {"success": False, "error": f"未知操作类型: {action_type}"}
        except Exception as e:
            logger.error("execute_action 失败 (%s): %s", action_type, e)
            return {"success": False, "error": str(e), "action_type": action_type}

    def execute_action_async(self, action_type: str, content: str,
                              file_path: str = "", overwrite: bool = False,
                              pattern: str = "", replacement: str = "",
                              label: str = "") -> dict:
        """异步执行操作，提交到 TaskManager 线程池，立即返回 task_id。
        结果通过心跳通知或后续查询获取。"""
        mgr = self._mgr()
        params = {
            "action_type": action_type,
            "content": content,
            "file_path": file_path,
            "overwrite": overwrite,
            "pattern": pattern,
            "replacement": replacement,
        }
        if label:
            params["label"] = label
        tid = mgr.create_task(
            task_type=TaskType.ACTION,
            user_id=self._uid(), chat_id=self._cid(),
            params=params, priority=1)
        mgr.execute_task(tid)
        logger.info("execute_action_async: task_id=%s type=%s label=%s",
                     tid, action_type, label or content[:40])
        return {"task_id": tid, "action_type": action_type, "async": True,
                "label": label or content[:60]}

    @staticmethod
    def _run_shell(cmd: str) -> dict:
        logger.info("shell: %s", cmd[:120])
        proc = subprocess.run(
            cmd, shell=True, capture_output=True,
            encoding=_ENCODING, errors="replace", timeout=120,
        )
        return {
            "success": proc.returncode == 0,
            "stdout": proc.stdout[:5000],
            "stderr": proc.stderr[:2000],
            "returncode": proc.returncode,
        }

    @staticmethod
    def _run_python(code: str) -> dict:
        logger.info("python: %s", code[:120])
        proc = subprocess.run(
            ["python3", "-c", code],
            capture_output=True,
            encoding=_ENCODING, errors="replace", timeout=30,
        )
        return {
            "success": proc.returncode == 0,
            "stdout": proc.stdout[:5000],
            "stderr": proc.stderr[:2000],
            "returncode": proc.returncode,
        }

    @staticmethod
    def _do_write_file(file_path: str, content: str, overwrite: bool) -> dict:
        if not file_path:
            return {"success": False, "error": "缺少 file_path"}
        path = Path(file_path)
        if path.exists() and not overwrite:
            return {"success": False, "error": f"文件已存在且 overwrite=false: {file_path}"}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        logger.info("write_file: %s (%d chars)", file_path, len(content))
        return {"success": True, "file_path": str(path), "size": len(content)}

    @staticmethod
    def _do_edit_file(file_path: str, pattern: str, replacement: str) -> dict:
        if not file_path or not pattern:
            return {"success": False, "error": "缺少 file_path 或 pattern"}
        path = Path(file_path)
        if not path.exists():
            return {"success": False, "error": f"文件不存在: {file_path}"}
        text = path.read_text(encoding="utf-8")
        new_text = text.replace(pattern, replacement)
        if new_text == text:
            return {"success": False, "error": "未找到匹配模式", "file_path": file_path}
        path.write_text(new_text, encoding="utf-8")
        logger.info("edit_file: %s (%d → %d chars)", file_path, len(text), len(new_text))
        return {"success": True, "file_path": str(file_path), "size": len(new_text)}

    @staticmethod
    def _parse_interval(interval_str: str) -> int:
        import re
        if not interval_str:
            return 0
        m = re.match(r"(\d+)\s*(min|m|h|d|s)", interval_str.strip().lower())
        if not m:
            return 0
        v, u = int(m.group(1)), m.group(2)
        return {"s": v, "min": v * 60, "m": v * 60,
                "h": v * 3600, "d": v * 86400}.get(u, 0)
