# skills/system/tools/task_tools.py

import json
import locale
import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from tasks import TaskType

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

    # ── 查询提醒 ──

    def list_reminders(self, status: str = "pending") -> dict:
        """查询当前用户的所有提醒/习惯/倒计时任务。"""
        db = self._ctx.get("db")
        uid = self._uid()
        if not db:
            return {"reminders": [], "error": "数据库不可用"}

        from tasks import TaskType, TaskStatus
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
