# skills/system/tools/task_tools.py

from datetime import datetime, timedelta
from tasks import TaskType


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

    def create_reminder(self, text: str, time: str) -> dict:
        mgr = self._mgr()
        scheduled = datetime.fromisoformat(time)
        tid = mgr.create_task(
            task_type=TaskType.REMINDER, user_id=0, chat_id=0,
            params={"text": text, "time": time},
            priority=1, scheduled_time=scheduled)
        return {"task_id": tid}

    def create_habit(self, text: str, time: str, interval: str) -> dict:
        mgr = self._mgr()
        scheduled = datetime.fromisoformat(time)
        interval_sec = self._parse_interval(interval)
        tid = mgr.create_task(
            task_type=TaskType.HABIT, user_id=0, chat_id=0,
            params={"text": text, "time": time, "interval": interval},
            priority=1, scheduled_time=scheduled,
            interval_seconds=interval_sec)
        return {"task_id": tid}

    def create_countdown(self, text: str, target: str) -> dict:
        mgr = self._mgr()
        scheduled = datetime.fromisoformat(target)
        tid = mgr.create_task(
            task_type=TaskType.COUNTDOWN, user_id=0, chat_id=0,
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
            task_type=TaskType.DAILY_PLAN, user_id=0, chat_id=0,
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
            task_type=TaskType.PERIODIC, user_id=0, chat_id=0,
            params={"cron": cron, "text": text},
            priority=1, scheduled_time=next_time)
        return {"task_id": tid}

    def create_reasoner(self, question: str, context: str = "") -> dict:
        mgr = self._mgr()
        tid = mgr.create_task(
            task_type=TaskType.REASONER, user_id=0, chat_id=0,
            params={"question": question, "context": context},
            priority=1)
        mgr.execute_task(tid)
        return {"task_id": tid}

    def execute_action(self, action_type: str, content: str,
                        file_path: str = "", overwrite: bool = False,
                        pattern: str = "", replacement: str = "") -> dict:
        mgr = self._mgr()
        params = {"action_type": action_type, "content": content}
        if file_path:
            params["file_path"] = file_path
        if overwrite:
            params["overwrite"] = overwrite
        if pattern:
            params["pattern"] = pattern
        if replacement:
            params["replacement"] = replacement
        tid = mgr.create_task(
            task_type=TaskType.ACTION, user_id=0, chat_id=0,
            params=params, priority=1)
        mgr.execute_task(tid)
        return {"task_id": tid}

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
