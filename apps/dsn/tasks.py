
# DSN-exp/tasks.py
# UPD v3_260620

import os
import json
import logging
import locale
import re as _re
import threading
import time
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any
from concurrent.futures import ThreadPoolExecutor, Future
import schedule

from apps.dsn.config import Config
from apps.dsn.db.chat import ChatDBManager
from apps.dsn.models import OpenAIChat


class TaskType(Enum):
    """任务类型枚举"""
    REMINDER = "reminder"    # 一次性提醒
    HABIT = "habit"          # 周期性提醒 (每N分钟/小时/天)
    COUNTDOWN = "countdown"  # 倒计时到指定时刻
    DAILY_PLAN = "daily_plan"  # 每日计划提醒 (07:30 触发)
    PERIODIC = "periodic"    # 通用 cron 表达式
    REASONER = "reasoner"    # 推理任务
    ANALYSIS = "analysis"    # 分析任务
    ACTION = "action"        # 动作执行任务


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"      # 等待执行
    RUNNING = "running"      # 执行中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"        # 失败
    CANCELLED = "cancelled"  # 已取消
    MISSED = "missed"        # 过期未执行
    SKIPPED = "skipped"      # 用户主动跳过该次触发


class TaskPriority(Enum):
    """任务优先级枚举"""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3


class Task:
    """任务基类"""
    
    def __init__(
        self,
        task_id: str,
        task_type: TaskType,
        user_id: int,
        chat_id: int,
        params: Dict[str, Any],
        priority: TaskPriority = TaskPriority.NORMAL,
        scheduled_time: Optional[datetime] = None,
        interval_seconds: int = 0,
    ):
        self.task_id = task_id
        self.task_type = task_type
        self.user_id = user_id
        self.chat_id = chat_id
        self.params = params
        self.priority = priority
        self.scheduled_time = scheduled_time
        self.interval_seconds = interval_seconds
        self.skip_count = 0
        self.status = TaskStatus.PENDING
        self.created_at = datetime.now()
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.result: Optional[Dict[str, Any]] = None
        self.error: Optional[str] = None
        self.handled_by_pipeline: bool = False
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Task':
        """从字典创建任务对象"""
        # 处理priority字段：可能是整数或枚举值
        priority_value = data.get("priority", 1)
        if isinstance(priority_value, int):
            priority = TaskPriority(priority_value)
        else:
            priority = TaskPriority[priority_value] if isinstance(priority_value, str) else TaskPriority.NORMAL

        task = cls(
            task_id=data["task_id"],
            task_type=TaskType(data["task_type"]),
            user_id=data["user_id"],
            chat_id=data["chat_id"],
            params=data["params"],
            priority=priority,
            scheduled_time=cls._parse_local_dt(data.get("scheduled_time")),
            interval_seconds=data.get("interval_seconds", 0),
        )
        task.status = TaskStatus(data["status"])
        task.created_at = cls._parse_local_dt(data["created_at"]) or datetime.now()
        task.skip_count = data.get("skip_count", 0)
        if data.get("started_at"):
            task.started_at = cls._parse_local_dt(data["started_at"])
        if data.get("completed_at"):
            task.completed_at = cls._parse_local_dt(data["completed_at"])
        task.result = data.get("result")
        task.error = data.get("error")
        return task

    @staticmethod
    def _parse_local_dt(value) -> Optional[datetime]:
        """解析 ISO 时间字符串为本地无时区 datetime（兼容库内混存的带/不带时区数据）。"""
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(str(value))
        except (ValueError, TypeError):
            return None
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt


class TaskManager:
    """任务管理器"""
    
    def __init__(self, db: ChatDBManager, max_workers: int = 5):
        self.db = db
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.scheduler = schedule.Scheduler()
        self.tasks: Dict[str, Task] = {}
        self._user_task_index: dict[int, set[str]] = {}
        self.lock = threading.Lock()
        self.logger = logging.getLogger(__name__)
        self.running = True
        self._retry_depths: dict[str, int] = {}
        self._retry_lock = threading.Lock()
        
        # 初始化数据库表
        self._init_db()
        
        # 加载持久化的任务（先加载，再启动调度器，避免 schedule 非线程安全的并发写入）
        self._load_persistent_tasks()
        
        # 启动调度器线程
        self.scheduler_thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.scheduler_thread.start()
        
        self.logger.info("TaskManager 初始化完成")

    _ACTION_HANDLERS = {
        "shell": "_action_shell",
        "python": "_action_python",
        "write_file": "_action_write_file",
        "edit_file": "_action_edit_file",
    }

    def _init_db(self):
        """初始化任务相关的数据库表"""
        conn = self.db._get_connection()
        try:
            # 创建任务表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    params TEXT NOT NULL,
                    priority INTEGER DEFAULT 1,
                    scheduled_time TEXT,
                    interval_seconds INTEGER DEFAULT 0,
                    skip_count INTEGER DEFAULT 0,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    result TEXT,
                    error TEXT,
                    FOREIGN KEY (chat_id) REFERENCES chats(chat_id) ON DELETE CASCADE
                )
            """)
            
            # 创建任务结果表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS task_results (
                    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
                )
            """)
            
            # 创建任务通知表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS task_notifications (
                    notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    result TEXT,
                    delivered INTEGER DEFAULT 0,
                    dismissed INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE,
                    FOREIGN KEY (chat_id) REFERENCES chats(chat_id) ON DELETE CASCADE
                )
            """)

            # 创建正计时表（每用户最多一个）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS stopwatches (
                    user_id     INTEGER PRIMARY KEY,
                    label       TEXT DEFAULT '',
                    status      TEXT NOT NULL DEFAULT 'running',
                    started_at  REAL,
                    accumulated REAL DEFAULT 0,
                    created_at  TEXT DEFAULT (datetime('now', 'localtime')),
                    updated_at  TEXT DEFAULT (datetime('now', 'localtime'))
                )
            """)

            conn.commit()
            self.logger.info("任务数据库表初始化完成")
        except Exception as e:
            self.logger.error("初始化任务数据库表失败: %s", e)
            conn.rollback()
            raise
    
    def _load_persistent_tasks(self):
        """从数据库加载持久化的任务（重启恢复）"""
        try:
            conn = self.db._get_connection()
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status IN (?, ?)",
                (TaskStatus.PENDING.value, TaskStatus.RUNNING.value)
            ).fetchall()
            
            now = datetime.now()
            for row in rows:
                try:
                    params = json.loads(row["params"])
                    task_data = {
                        "task_id": row["task_id"],
                        "task_type": row["task_type"],
                        "user_id": row["user_id"],
                        "chat_id": row["chat_id"],
                        "params": params,
                        "priority": row["priority"],
                        "scheduled_time": row["scheduled_time"],
                        "interval_seconds": row["interval_seconds"],
                        "status": row["status"],
                        "created_at": row["created_at"],
                        "started_at": row["started_at"],
                        "completed_at": row["completed_at"],
                        "result": json.loads(row["result"]) if row["result"] else None,
                        "error": row["error"]
                    }
                    task = Task.from_dict(task_data)
                    task.skip_count = row["skip_count"]
                    self.tasks[task.task_id] = task
                    self._user_task_index.setdefault(task.user_id, set()).add(task.task_id)

                    task_type = task.task_type

                    # 重启时 RUNNING 无法恢复
                    if task.status == TaskStatus.RUNNING:
                        task.status = TaskStatus.FAILED
                        task.error = "Server restarted during task execution"
                        task.completed_at = now
                        self._save_task(task)
                        continue

                    # PENDING 且 scheduled_time 已过期超 5 分钟 → MISSED
                    if task.status == TaskStatus.PENDING and task.scheduled_time:
                        if task.scheduled_time < now - timedelta(minutes=5):
                            task.status = TaskStatus.MISSED
                            task.completed_at = now
                            self._save_task(task)
                            self.logger.warning("过期任务标记为 MISSED: %s (scheduled: %s)",
                                               task.task_id, task.scheduled_time)
                            continue

                    # 重新调度 PENDING 任务
                    if task.status == TaskStatus.PENDING and task.scheduled_time:
                        if task_type in (TaskType.REMINDER, TaskType.HABIT, TaskType.COUNTDOWN,
                                         TaskType.DAILY_PLAN, TaskType.PERIODIC):
                            self._schedule_reminder_task(task)

                except Exception as e:
                    self.logger.error("加载任务失败 (task_id=%s): %s", row["task_id"], e)

            self.logger.info("从数据库加载了 %d 个任务", len(rows))
        except Exception as e:
            self.logger.error("加载持久化任务失败: %s", e)
    
    def _save_task(self, task: Task):
        """保存任务到数据库"""
        try:
            conn = self.db._get_connection()
            
            # 处理priority字段：确保它是TaskPriority枚举或整数
            if hasattr(task.priority, 'value'):
                priority_value = task.priority.value
            else:
                # 如果priority是整数，直接使用
                priority_value = task.priority if isinstance(task.priority, int) else TaskPriority.NORMAL.value
            
            conn.execute("""
                INSERT OR REPLACE INTO tasks 
                (task_id, task_type, user_id, chat_id, params, priority, scheduled_time,
                 interval_seconds, skip_count,
                 status, created_at, started_at, completed_at, result, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task.task_id,
                task.task_type.value,
                task.user_id,
                task.chat_id,
                json.dumps(task.params, ensure_ascii=False),
                priority_value,
                task.scheduled_time.isoformat() if task.scheduled_time else None,
                task.interval_seconds,
                task.skip_count,
                task.status.value,
                task.created_at.isoformat(),
                task.started_at.isoformat() if task.started_at else None,
                task.completed_at.isoformat() if task.completed_at else None,
                json.dumps(task.result, ensure_ascii=False) if task.result else None,
                task.error
            ))
            conn.commit()
        except Exception as e:
            self.logger.error("保存任务失败 (task_id=%s): %s", task.task_id, e)
            conn.rollback()
    
    def _update_task_status(self, task_id: str, status: TaskStatus, 
                           result: Optional[Dict] = None, error: Optional[str] = None):
        """更新任务状态"""
        with self.lock:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                task.status = status
                
                if status == TaskStatus.RUNNING:
                    task.started_at = datetime.now()
                elif status in (TaskStatus.COMPLETED, TaskStatus.FAILED,
                                TaskStatus.CANCELLED, TaskStatus.MISSED, TaskStatus.SKIPPED):
                    task.completed_at = datetime.now()
                
                if result is not None:
                    task.result = result
                if error is not None:
                    task.error = error
                
                self._save_task(task)
    
    def _schedule_reminder_task(self, task: Task):
        """调度提醒任务 (一次性/周期性/每日计划/cron)"""
        if not task.scheduled_time:
            return

        now = datetime.now()
        delay_seconds = max(0, (task.scheduled_time - now).total_seconds())
        self.logger.info("调度提醒: task=%s type=%s time=%s delay=%.0fs uid=%d cid=%d",
                         task.task_id, task.task_type.value,
                         task.scheduled_time.isoformat(), delay_seconds,
                         task.user_id, task.chat_id)

        def reminder_job():
            self.logger.info("⚠️ 触发提醒任务: %s (类型: %s, 排期时间: %s, 用户: %d)",
                             task.task_id, task.task_type.value,
                             task.scheduled_time.isoformat() if task.scheduled_time else "N/A",
                             task.user_id)
            self.execute_task(task.task_id)

            # DAILY_PLAN 通过 schedule.every().day.at() 调度，属于 daily 重复 job，不需 CancelJob
            if task.task_type == TaskType.DAILY_PLAN:
                return

            # REMINDER / COUNTDOWN / HABIT / PERIODIC：均为 one-shot 调度
            # HABIT / PERIODIC 的重调度统一由 _handle_task_result 处理
            return schedule.CancelJob

        # DAILY_PLAN: schedule.every().day.at("07:30")
        if task.task_type == TaskType.DAILY_PLAN:
            trigger_time = task.params.get("trigger_time", "07:30")
            self.scheduler.every().day.at(trigger_time).do(reminder_job).tag(task.task_id)
            return

        # PERIODIC: croniter 计算下一次
        if task.task_type == TaskType.PERIODIC:
            cron_expr = task.params.get("cron", "")
            if cron_expr:
                try:
                    import croniter
                    cron = croniter.croniter(cron_expr, now)
                    next_time = cron.get_next(datetime)
                    task.scheduled_time = next_time
                    self._save_task(task)
                    delay = max(0, (next_time - now).total_seconds())
                    self.scheduler.every(delay).seconds.do(reminder_job).tag(task.task_id)
                    return
                except Exception as e:
                    self.logger.error("cron 解析失败: %s → %s", cron_expr, e)
                    return

        if delay_seconds > 3600 * 24:
            # > 24h 的延迟不用 schedule.every().seconds (精度问题)
            # 改用 5 分钟轮询检查
            def _long_delay_check():
                if datetime.now() >= task.scheduled_time:
                    self.logger.info("长延迟提醒到期: %s", task.task_id)
                    reminder_job()
                    return schedule.CancelJob
            self.scheduler.every(300).seconds.do(_long_delay_check).tag(task.task_id)
        elif delay_seconds > 0:
            job = self.scheduler.every(delay_seconds).seconds.do(reminder_job)
            job.tag(task.task_id)
        else:
            self.logger.info("提醒任务 %s 时间已过，立即执行", task.task_id)
            self.execute_task(task.task_id)
    
    def _run_scheduler(self):
        """运行调度器线程"""
        _stop = threading.Event()
        while self.running and not _stop.is_set():
            self.scheduler.run_pending()
            _stop.wait(timeout=1)
    
    def create_task(self, task_type: TaskType, user_id: int, chat_id: int, 
                   params: Dict[str, Any], priority: TaskPriority = TaskPriority.NORMAL,
                   scheduled_time: Optional[datetime] = None,
                   interval_seconds: int = 0) -> str:
        """创建新任务"""
        task_id = str(uuid.uuid4())
        
        task = Task(
            task_id=task_id,
            task_type=task_type,
            user_id=user_id,
            chat_id=chat_id,
            params=params,
            priority=priority,
            scheduled_time=scheduled_time,
            interval_seconds=interval_seconds,
        )
        
        with self.lock:
            self.tasks[task_id] = task
            self._user_task_index.setdefault(user_id, set()).add(task_id)
            self._save_task(task)
        
        # 定时任务进行调度
        if task_type in (TaskType.REMINDER, TaskType.HABIT, TaskType.COUNTDOWN,
                         TaskType.DAILY_PLAN, TaskType.PERIODIC) and scheduled_time:
            self._schedule_reminder_task(task)
        
        self.logger.info("创建任务: %s (类型: %s, 用户: %d, 聊天: %d, 排期: %s, 参数: %s)",
                         task_id, task_type.value, user_id, chat_id,
                         scheduled_time.isoformat() if scheduled_time else "立即",
                         json.dumps(params, ensure_ascii=False)[:200])
        return task_id
    
    def execute_task(self, task_id: str) -> Future:
        """执行任务"""
        if task_id not in self.tasks:
            raise ValueError(f"任务不存在: {task_id}")
        
        task = self.tasks[task_id]
        self.logger.info("开始执行任务: %s (类型: %s, 用户: %d, 排期: %s)",
                         task_id, task.task_type.value, task.user_id,
                         task.scheduled_time.isoformat() if task.scheduled_time else "立即")
        
        # 更新状态为运行中
        self._update_task_status(task_id, TaskStatus.RUNNING)
        
        # 提交到线程池执行
        future = self.executor.submit(self._execute_task_internal, task)
        
        # 添加回调处理结果
        future.add_done_callback(lambda f: self._handle_task_result(task_id, f))
        
        return future
    
    def _execute_task_internal(self, task: Task) -> Dict[str, Any]:
        """内部任务执行逻辑"""
        try:
            if task.task_type == TaskType.REASONER:
                return self._execute_reasoner_task(task)
            elif task.task_type in (TaskType.REMINDER, TaskType.HABIT, TaskType.COUNTDOWN,
                                     TaskType.DAILY_PLAN, TaskType.PERIODIC):
                return self._execute_reminder_task(task)
            elif task.task_type == TaskType.ANALYSIS:
                return self._execute_analysis_task(task)
            elif task.task_type == TaskType.ACTION:
                return self._execute_action_task(task)
            else:
                raise ValueError(f"未知的任务类型: {task.task_type}")
        except Exception as e:
            self.logger.error("任务执行失败 (task_id=%s): %s", task.task_id, e)
            raise
    
    def _execute_reasoner_task(self, task: Task) -> Dict[str, Any]:
        """执行推理任务"""
        self.logger.info("开始执行推理任务: %s", task.task_id)

        # 获取任务参数
        question = task.params.get("question", "")
        context = task.params.get("context", "")

        # 根据配置选择推理模型
        from apps.dsn.config import Config
        model_type = task.params.get("model_type", "") or Config.MAIN_MODEL_TYPE
        if model_type == "lmstudio":
            from apps.dsn.models import LMStudioChat
            chat = LMStudioChat(
                base_url=Config.LMSTUDIO_BASE_URL,
                model_name=task.params.get("model_name") or Config.MAIN_MODEL_NAME,
                temperature=0.3,
                max_tokens=Config.LMSTUDIO_MAX_TOKENS,
                timeout=Config.REASONER_TIMEOUT,
            )
        else:
            from apps.dsn.models.api_accounts import load_failover_chat
            fc = load_failover_chat(
                model_override=task.params.get("model_name") or Config.REASONER_MODEL,
                api_key_fallback=Config.OPENAI_API_KEY,
                api_url_fallback=f"{Config.OPENAI_API_BASE}/chat/completions",
            )
            if fc is not None:
                chat = fc
            else:
                chat = OpenAIChat(
                    api_key=Config.OPENAI_API_KEY,
                    model=task.params.get("model_name") or Config.REASONER_MODEL,
                    api_url=f"{Config.OPENAI_API_BASE}/chat/completions"
                )

        # 构建提示词
        system_prompt = """你是一个专业的推理AI，需要深入分析复杂问题，给出详细的思考过程和最终结论。
请按照以下格式输出：
1. 首先分析问题的关键点
2. 然后逐步推理
3. 最后给出结论

问题：{question}
上下文：{context}""".format(question=question, context=context)

        # 执行推理
        chat.messages = [{"role": "system", "content": system_prompt}]
        reasoning_result = chat.send_message("请分析这个问题并给出详细推理过程")

        # 提取思考过程以外的回答（最终结论）
        # 这里简单实现：取最后一段作为结论
        lines = reasoning_result.strip().split('\n')
        conclusion = lines[-1] if lines else reasoning_result

        result = {
            "reasoning": reasoning_result,
            "conclusion": conclusion,
            "model": getattr(chat, 'model', getattr(chat, 'model_name', 'unknown')),
            "timestamp": datetime.now().isoformat()
        }

        # 保存结果到数据库
        self._save_task_result(task.task_id, reasoning_result)

        self.logger.info("推理任务完成: %s", task.task_id)
        return result
    
    def _execute_reminder_task(self, task: Task) -> Dict[str, Any]:
        """执行提醒任务"""
        self.logger.info("执行提醒任务: %s (type=%s)", task.task_id, task.task_type.value)

        reminder_text = task.params.get("text", "提醒时间到了！")

        # COUNTDOWN: 附加剩余时间
        if task.task_type == TaskType.COUNTDOWN and task.scheduled_time:
            remaining = task.scheduled_time - datetime.now()
            if remaining.total_seconds() > 0:
                days = remaining.days
                hours = remaining.seconds // 3600
                mins = (remaining.seconds % 3600) // 60
                parts = []
                if days > 0:
                    parts.append(f"{days} 天")
                if hours > 0:
                    parts.append(f"{hours} 小时")
                if mins > 0:
                    parts.append(f"{mins} 分钟")
                time_str = " ".join(parts) if parts else "不到 1 分钟"
                reminder_text = f"{reminder_text}\n（距离目标还有 {time_str}）"

        # DAILY_PLAN: 触发 PlanEngine 生成今日计划
        if task.task_type == TaskType.DAILY_PLAN:
            try:
                from apps.dsn.db.plan_engine import PlanEngine
                from apps.dsn.db.plan_store import PlanStore
                from datetime import date
                store = PlanStore(self.db)
                engine = PlanEngine(store)
                today = date.today().isoformat()
                tasks = engine.generate_daily_plan(task.user_id, today)
                if tasks:
                    plan_lines = [f"  ☐ {t.title} ({t.duration_min}min)" for t in tasks]
                    reminder_text = f"{reminder_text}\n\n今日计划:\n" + "\n".join(plan_lines)
            except Exception as e:
                self.logger.error("DAILY_PLAN 计划生成失败: %s", e)

        result = {
            "reminder_text": reminder_text,
            "user_id": task.user_id,
            "chat_id": task.chat_id,
            "timestamp": datetime.now().isoformat(),
            "task_type": task.task_type.value,
            "requires_ai_notification": True,
            "skip_memory": True
        }

        self._save_task_result(task.task_id, f"提醒任务已触发: {reminder_text}")

        return result
    
    def _execute_analysis_task(self, task: Task) -> Dict[str, Any]:
        """执行分析任务"""
        self.logger.info("执行分析任务: %s", task.task_id)
        
        # 这里可以扩展其他类型的分析任务
        analysis_text = task.params.get("text", "")
        
        result = {
            "analysis_result": f"分析完成: {analysis_text}",
            "timestamp": datetime.now().isoformat(),
            "task_type": "analysis"
        }
        
        self._save_task_result(task.task_id, result["analysis_result"])
        
        return result
    
    def _execute_action_task(self, task: Task) -> Dict[str, Any]:
        from apps.dsn.models import DETAIL_ACTIONS
        self.logger.info("开始执行动作任务: %s", task.task_id)
        action_type = task.params.get("action_type", "")
        content = task.params.get("content", "")

        # 详细模式：显示 AI 动作的原始输入
        if DETAIL_ACTIONS:
            print("\n" + "=" * 60)
            print("🔧 [动作执行] 原始输入:")
            print("=" * 60)
            print(f"动作类型: {action_type}")
            print(f"任务ID: {task.task_id}")
            print(f"用户ID: {task.user_id}")
            print(f"聊天ID: {task.chat_id}")
            print(f"\n代码内容:")
            print("-" * 40)
            print(content)
            print("-" * 40)
            print("=" * 60)

        result = {
            "action_type": action_type,
            "timestamp": datetime.now().isoformat(),
            "task_type": "action",
            "requires_ai_notification": True,
            "skip_memory": True,
        }

        handler_name = self._ACTION_HANDLERS.get(action_type)
        if not handler_name:
            result.update({"success": False, "error": f"未知的动作类型: {action_type}"})
            return self._finalize_action(task, result)

        handler = getattr(self, handler_name)
        try:
            handler(task, content, result)
        except Exception as e:
            self.logger.error("动作任务执行失败 (task_id=%s): %s", task.task_id, e)
            result.update({"success": False, "error": str(e)})

        # 详细模式：显示系统给予的原始反馈
        if DETAIL_ACTIONS:
            print("\n" + "=" * 60)
            print("📋 [动作执行] 系统反馈:")
            print("=" * 60)
            print(f"成功: {result.get('success', '未知')}")
            if result.get("exit_code") is not None:
                print(f"退出码: {result['exit_code']}")
            if result.get("error"):
                print(f"错误: {result['error']}")
            if result.get("output"):
                print(f"输出:")
                print("-" * 40)
                print(result["output"])
                print("-" * 40)
            print("=" * 60)

        return self._finalize_action(task, result)

    def _finalize_action(self, task, result):
        self._save_task_result(task.task_id, json.dumps(result, ensure_ascii=False))
        return result

    def _action_shell(self, task, content, result):
        import subprocess
        from apps.dsn.utils.workspace import get_workspace_manager
        encoding = locale.getpreferredencoding(False)
        self.logger.info("执行shell命令: %s", content[:100] if len(content) <= 100 else content[:100] + "...")
        cwd = str(get_workspace_manager().user_dir(uid=getattr(task, 'user_id', 0)))
        process = subprocess.run(
            content, shell=True, capture_output=True,
            encoding=encoding, errors='replace', timeout=Config.ACTION_TIMEOUT,
            cwd=cwd,
        )
        output = f"STDOUT:\n{process.stdout}\n\nSTDERR:\n{process.stderr}"
        result.update({
            "success": process.returncode == 0,
            "exit_code": process.returncode,
            "output": output,
            "content_preview": content[:200],
        })

    def _action_python(self, task, content, result):
        import subprocess, tempfile
        from apps.dsn.utils.workspace import get_workspace_manager
        encoding = locale.getpreferredencoding(False)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8-sig') as f:
            f.write(content)
            temp_file = f.name
        try:
            cwd = str(get_workspace_manager().user_dir(uid=getattr(task, 'user_id', 0)))
            process = subprocess.run(
                ["python", temp_file], capture_output=True,
                encoding=encoding, errors='replace', timeout=Config.ACTION_TIMEOUT,
                cwd=cwd,
            )
            output = f"STDOUT:\n{process.stdout}\n\nSTDERR:\n{process.stderr}"
            result.update({
                "success": process.returncode == 0,
                "exit_code": process.returncode,
                "output": output,
                "content_preview": content[:200],
            })
        finally:
            try:
                os.unlink(temp_file)
            except Exception:
                logging.getLogger(__name__).warning("清理临时文件失败: %s", temp_file, exc_info=True)

    def _action_write_file(self, task, content, result):
        from apps.dsn.utils.workspace import get_workspace_manager
        file_path = task.params.get("file_path", "")
        overwrite = task.params.get("overwrite", True)
        if not file_path:
            raise ValueError("文件路径不能为空")
        if not os.path.isabs(file_path):
            wm = get_workspace_manager()
            file_path = str(wm.resolve(file_path, uid=getattr(task, 'user_id', 0)))
        self.logger.info("写入文件: %s (长度: %d 字符)", file_path, len(content))
        if os.path.exists(file_path) and not overwrite:
            raise FileExistsError(f"文件已存在: {file_path}")
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8-sig') as f:
            f.write(content)
        result.update({
            "success": True, "file_path": file_path,
            "file_size": len(content), "content_preview": content[:200],
        })

    def _action_edit_file(self, task, content, result):
        from apps.dsn.utils.workspace import get_workspace_manager
        file_path = task.params.get("file_path", "")
        pattern = task.params.get("pattern", "")
        replacement = task.params.get("replacement", "")
        if not file_path:
            raise ValueError("文件路径不能为空")
        if not os.path.isabs(file_path):
            wm = get_workspace_manager()
            file_path = str(wm.resolve(file_path, uid=getattr(task, 'user_id', 0)))
        self.logger.info("编辑文件: %s", file_path)
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            file_content = f.read()
        if pattern and replacement is not None:
            import re
            new_content = re.sub(pattern, replacement, file_content, flags=re.DOTALL | re.MULTILINE)
        else:
            new_content = content
        with open(file_path, 'w', encoding='utf-8-sig') as f:
            f.write(new_content)
        result.update({
            "success": True, "file_path": file_path,
            "old_size": len(file_content), "new_size": len(new_content),
            "content_preview": new_content[:200],
        })
    
    def _save_task_result(self, task_id: str, content: str):
        """保存任务结果到数据库"""
        try:
            conn = self.db._get_connection()
            conn.execute(
                "INSERT INTO task_results (task_id, content) VALUES (?, ?)",
                (task_id, content)
            )
            conn.commit()
        except Exception as e:
            self.logger.error("保存任务结果失败 (task_id=%s): %s", task_id, e)
            conn.rollback()
    
    def _handle_task_result(self, task_id: str, future: Future):
        """处理任务执行结果"""
        try:
            result = future.result()
            self._update_task_status(task_id, TaskStatus.COMPLETED, result=result)
            self.logger.info("任务完成: %s", task_id)
        except Exception as e:
            self._update_task_status(task_id, TaskStatus.FAILED, error=str(e))
            self.logger.error("任务失败: %s, 错误: %s", task_id, e)
            return

        # --- 以下操作不应影响任务已完成的 COMPLETED 状态 ---

        # HABIT: 根据 interval_seconds 重新创建下一次提醒
        task = self.tasks.get(task_id)
        if task and task.task_type == TaskType.HABIT and task.interval_seconds > 0:
            next_time = datetime.now() + timedelta(seconds=task.interval_seconds)
            task.scheduled_time = next_time
            task.status = TaskStatus.PENDING
            task.result = None
            task.error = None
            self._save_task(task)
            self._schedule_reminder_task(task)
            self.logger.info("HABIT 任务 %s 下一次: %s", task_id, next_time)

        # PERIODIC: 执行后根据 cron 表达式重新计算下一次触发
        if task and task.task_type == TaskType.PERIODIC:
            cron_expr = task.params.get("cron", "")
            if cron_expr:
                try:
                    import croniter
                    cron = croniter.croniter(cron_expr, datetime.now())
                    next_time = cron.get_next(datetime)
                    task.scheduled_time = next_time
                    task.status = TaskStatus.PENDING
                    task.result = None
                    task.error = None
                    self._save_task(task)
                    self._schedule_reminder_task(task)
                    self.logger.info("PERIODIC 任务 %s 下一次: %s", task_id, next_time)
                except Exception as e:
                    self.logger.error("PERIODIC 重排失败: %s", e)

        try:
            self._notify_task_completion(task_id, result)
        except Exception as e:
            self.logger.error("通知任务完成失败: %s, 错误: %s", task_id, e)
    
    def _notify_task_completion(self, task_id: str, result: Dict[str, Any]):
        """通知任务完成（需要外部实现推送逻辑）"""
        # 这里只是一个占位符，实际推送逻辑需要在app.py中实现
        self.logger.info("任务 %s 完成，准备通知用户", task_id)

        # 将任务完成事件放入队列，由主应用处理
        if hasattr(self, 'completion_queue'):
            self.completion_queue.put((task_id, result))

        # 对于提醒类任务，写入 task_notifications 表（delivered=0），
        # 供前端心跳接口 /api/heartbeat 拉取并触发 AI 通知 + TTS。
        task = self.tasks.get(task_id)
        if task and task.task_type in (TaskType.REMINDER, TaskType.HABIT,
                                        TaskType.COUNTDOWN, TaskType.DAILY_PLAN,
                                        TaskType.PERIODIC):
            try:
                self._create_notification(task, result)
            except Exception as e:
                self.logger.error("写入 task_notifications 失败 (task=%s): %s", task_id, e)

    def _create_notification(self, task, result: Dict[str, Any]):
        """将提醒完成事件写入 task_notifications 表，等待前端心跳拉取。"""
        conn = self.db._get_connection()
        conn.execute(
            "INSERT INTO task_notifications (task_id, user_id, chat_id, result, delivered, dismissed) "
            "VALUES (?, ?, ?, ?, 0, 0)",
            (task.task_id, task.user_id, task.chat_id,
             json.dumps(result, ensure_ascii=False, default=str))
        )
        conn.commit()
        self.logger.info("已写入待通知提醒: task=%s uid=%d cid=%d",
                         task.task_id, task.user_id, task.chat_id)

    def fetch_pending_notifications(self, user_id: int, limit: int = 5) -> list:
        """拉取该用户所有未投递（delivered=0, dismissed=0）的通知。
        包括该用户的提醒通知 + 全局（user_id=0）视觉感知通知。
        返回 list[dict]，每项包含 notification_id / task_id / chat_id / result / task_type / params。
        不会修改 delivered 状态（由调用方在生成 AI 回复成功后再标记）。
        """
        conn = self.db._get_connection()
        rows = conn.execute(
            "SELECT n.notification_id, n.task_id, n.user_id, n.chat_id, n.result, "
            "       t.task_type, t.params "
            "FROM task_notifications n "
            "LEFT JOIN tasks t ON t.task_id = n.task_id "
            "WHERE (n.user_id = ? OR n.user_id = 0) AND n.delivered = 0 AND n.dismissed = 0 "
            "ORDER BY n.created_at ASC LIMIT ?",
            (user_id, limit)
        ).fetchall()
        out = []
        for r in rows:
            try:
                result = json.loads(r["result"]) if r["result"] else {}
            except Exception:
                result = {}
            try:
                params = json.loads(r["params"]) if r["params"] else {}
            except Exception:
                params = {}
            out.append({
                "notification_id": r["notification_id"],
                "task_id": r["task_id"],
                "user_id": r["user_id"],
                "chat_id": r["chat_id"],
                "result": result,
                "task_type": r["task_type"],
                "params": params,
            })
        return out

    def mark_notification_delivered(self, notification_id: int):
        """标记某条通知为已投递（前端已收到并展示）。"""
        conn = self.db._get_connection()
        conn.execute(
            "UPDATE task_notifications SET delivered = 1 WHERE notification_id = ?",
            (notification_id,)
        )
        conn.commit()
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务信息"""
        with self.lock:
            return self.tasks.get(task_id)

    # ── 正计时（Stopwatch）：每用户仅允许一个 ──

    def start_stopwatch(self, user_id: int, label: str = "") -> dict:
        """开始（或重置）该用户的正计时。若已存在则覆盖重置，保证每用户只有一个。"""
        now = time.time()
        conn = self.db._get_connection()
        conn.execute(
            "INSERT INTO stopwatches (user_id, label, status, started_at, accumulated, created_at, updated_at) "
            "VALUES (?, ?, 'running', ?, 0, datetime('now','localtime'), datetime('now','localtime')) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "label=excluded.label, status='running', started_at=excluded.started_at, "
            "accumulated=0, updated_at=datetime('now','localtime')",
            (user_id, label, now),
        )
        conn.commit()
        self.logger.info("start_stopwatch: uid=%d label=%s", user_id, label)
        return {"success": True, "status": "running", "label": label,
                "elapsed_seconds": 0, "elapsed_text": self._format_stopwatch_elapsed(0)}

    def get_stopwatch(self, user_id: int) -> dict:
        """查询该用户当前正计时的读数与状态。"""
        conn = self.db._get_connection()
        row = conn.execute(
            "SELECT * FROM stopwatches WHERE user_id = ?", (user_id,)
        ).fetchone()
        if not row:
            return {"success": False, "error": "当前没有进行中的正计时，请先开始"}
        elapsed = self._stopwatch_elapsed(row)
        return {"success": True, "status": row["status"], "label": row["label"] or "",
                "elapsed_seconds": round(elapsed, 1),
                "elapsed_text": self._format_stopwatch_elapsed(elapsed)}

    def pause_stopwatch(self, user_id: int) -> dict:
        """暂停当前正计时；已暂停时仅返回当前读数。"""
        conn = self.db._get_connection()
        row = conn.execute(
            "SELECT * FROM stopwatches WHERE user_id = ?", (user_id,)
        ).fetchone()
        if not row:
            return {"success": False, "error": "当前没有进行中的正计时，请先开始"}
        if row["status"] == "paused":
            elapsed = row["accumulated"] or 0
            return {"success": True, "status": "paused", "label": row["label"] or "",
                    "already_paused": True, "elapsed_seconds": round(elapsed, 1),
                    "elapsed_text": self._format_stopwatch_elapsed(elapsed)}
        elapsed = self._stopwatch_elapsed(row)
        conn.execute(
            "UPDATE stopwatches SET status='paused', started_at=NULL, accumulated=?, "
            "updated_at=datetime('now','localtime') WHERE user_id = ?",
            (elapsed, user_id),
        )
        conn.commit()
        return {"success": True, "status": "paused", "label": row["label"] or "",
                "elapsed_seconds": round(elapsed, 1),
                "elapsed_text": self._format_stopwatch_elapsed(elapsed)}

    def resume_stopwatch(self, user_id: int) -> dict:
        """继续已暂停的正计时；正在运行中则仅返回当前读数。"""
        conn = self.db._get_connection()
        row = conn.execute(
            "SELECT * FROM stopwatches WHERE user_id = ?", (user_id,)
        ).fetchone()
        if not row:
            return {"success": False, "error": "当前没有进行中的正计时，请先开始"}
        if row["status"] == "running":
            elapsed = self._stopwatch_elapsed(row)
            return {"success": True, "status": "running", "label": row["label"] or "",
                    "already_running": True, "elapsed_seconds": round(elapsed, 1),
                    "elapsed_text": self._format_stopwatch_elapsed(elapsed)}
        now = time.time()
        conn.execute(
            "UPDATE stopwatches SET status='running', started_at=?, "
            "updated_at=datetime('now','localtime') WHERE user_id = ?",
            (now, user_id),
        )
        conn.commit()
        elapsed = self._stopwatch_elapsed(
            {"status": "running", "started_at": now, "accumulated": row["accumulated"] or 0})
        return {"success": True, "status": "running", "label": row["label"] or "",
                "elapsed_seconds": round(elapsed, 1),
                "elapsed_text": self._format_stopwatch_elapsed(elapsed)}

    def delete_stopwatch(self, user_id: int) -> dict:
        """删除该用户的正计时。"""
        conn = self.db._get_connection()
        row = conn.execute(
            "SELECT user_id FROM stopwatches WHERE user_id = ?", (user_id,)
        ).fetchone()
        conn.execute("DELETE FROM stopwatches WHERE user_id = ?", (user_id,))
        conn.commit()
        if not row:
            return {"success": False, "error": "当前没有进行中的正计时，无需删除"}
        return {"success": True}

    def _stopwatch_elapsed(self, row) -> float:
        """计算当前累计秒数：暂停时取 accumulated，运行时加上本次运行段。"""
        accumulated = row["accumulated"] or 0
        if row["status"] == "running" and row["started_at"]:
            accumulated += time.time() - row["started_at"]
        return max(0.0, accumulated)

    @staticmethod
    def _format_stopwatch_elapsed(seconds: float) -> str:
        seconds = int(seconds)
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}小时{m:02d}分{s:02d}秒"
        if m:
            return f"{m}分{s:02d}秒"
        return f"{s}秒"

    def shutdown(self):
        """关闭任务管理器"""
        self.running = False
        self.executor.shutdown(wait=True)
        self.logger.info("TaskManager 已关闭")


class ComplexityAnalyzer:
    """问题复杂度分析器"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # 复杂度关键词
        self.complex_keywords = [
            "分析", "思考", "推理", "复杂", "难题", "困难", "挑战",
            "研究", "探讨", "论证", "证明", "计算", "评估", "判断",
            "为什么", "如何", "怎样", "原因", "原理", "机制"
        ]
        
        # 简单问题关键词
        self.simple_keywords = [
            "你好", "谢谢", "再见", "天气", "时间", "日期",
            "简单", "基础", "基本", "介绍", "说明", "解释"
        ]
    
    def analyze_complexity(self, text: str, context_length: int = 0) -> Dict[str, Any]:
        """
        分析问题复杂度
        
        返回:
            {
                "is_complex": bool,
                "score": float (0-1),
                "reasons": List[str],
                "suggestion": str
            }
        """
        score = 0.0
        reasons = []
        
        # 1. 长度分析
        text_length = len(text)
        if text_length > 200:
            score += 0.3
            reasons.append(f"问题较长 ({text_length} 字符)")
        elif text_length > 100:
            score += 0.15
            reasons.append(f"问题中等长度 ({text_length} 字符)")
        
        # 2. 关键词分析 (单次正则扫描替代多次 in 搜索)
        complex_pat = _re.compile("|".join(_re.escape(k) for k in self.complex_keywords))
        complex_matches = complex_pat.findall(text)
        complex_count = len(complex_matches)
        if complex_count > 0:
            keyword_score = min(0.4, complex_count * 0.1)
            score += keyword_score
            reasons.append(f"包含 {complex_count} 个复杂关键词")
        
        # 3. 简单关键词抵消
        simple_pat = _re.compile("|".join(_re.escape(k) for k in self.simple_keywords))
        simple_matches = simple_pat.findall(text)
        simple_count = len(simple_matches)
        if simple_count > 0:
            score = max(0, score - (simple_count * 0.05))
            reasons.append(f"包含 {simple_count} 个简单关键词")
        
        # 4. 上下文复杂度
        if context_length > 10:
            score += 0.1
            reasons.append(f"上下文较复杂 ({context_length} 轮对话)")
        
        # 5. 问题类型判断
        question_pat = _re.compile(r"[?？]|什么|如何|为什么|怎样")
        question_count = len(question_pat.findall(text))
        if question_count > 1:
            score += 0.1
            reasons.append("包含多个疑问点")
        
        # 确保分数在0-1之间
        score = max(0, min(1, score))
        
        # 判断是否复杂
        is_complex = score >= Config.TASK_COMPLEXITY_THRESHOLD
        
        suggestion = "使用reasoner模型进行深入分析" if is_complex else "使用chat模型直接回复"
        
        return {
            "is_complex": is_complex,
            "score": round(score, 2),
            "reasons": reasons,
            "suggestion": suggestion
        }

