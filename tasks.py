
# DSN-exp/tasks.py
# UPD v3_260328

import os
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any, Callable
from concurrent.futures import ThreadPoolExecutor, Future
import schedule

from config import Config
from chatdbmgr import ChatDBManager
from models import DeepSeekChat


class TaskType(Enum):
    """任务类型枚举"""
    REMINDER = "reminder"  # 提醒任务
    REASONER = "reasoner"  # 推理任务
    ANALYSIS = "analysis"  # 分析任务


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"      # 等待执行
    RUNNING = "running"      # 执行中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"        # 失败
    CANCELLED = "cancelled"  # 已取消


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
        scheduled_time: Optional[datetime] = None
    ):
        self.task_id = task_id
        self.task_type = task_type
        self.user_id = user_id
        self.chat_id = chat_id
        self.params = params
        self.priority = priority
        self.scheduled_time = scheduled_time
        self.status = TaskStatus.PENDING
        self.created_at = datetime.now()
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.result: Optional[Dict[str, Any]] = None
        self.error: Optional[str] = None
        
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type.value,
            "user_id": self.user_id,
            "chat_id": self.chat_id,
            "params": self.params,
            "priority": self.priority.value,
            "scheduled_time": self.scheduled_time.isoformat() if self.scheduled_time else None,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result": self.result,
            "error": self.error
        }
    
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
            scheduled_time=datetime.fromisoformat(data["scheduled_time"]) if data.get("scheduled_time") else None
        )
        task.status = TaskStatus(data["status"])
        task.created_at = datetime.fromisoformat(data["created_at"])
        if data.get("started_at"):
            task.started_at = datetime.fromisoformat(data["started_at"])
        if data.get("completed_at"):
            task.completed_at = datetime.fromisoformat(data["completed_at"])
        task.result = data.get("result")
        task.error = data.get("error")
        return task


class TaskManager:
    """任务管理器"""
    
    def __init__(self, db: ChatDBManager, max_workers: int = 5):
        self.db = db
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.scheduler = schedule.Scheduler()
        self.tasks: Dict[str, Task] = {}
        self.lock = threading.Lock()
        self.logger = logging.getLogger(__name__)
        self.running = True
        
        # 初始化数据库表
        self._init_db()
        
        # 启动调度器线程
        self.scheduler_thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.scheduler_thread.start()
        
        # 加载持久化的任务
        self._load_persistent_tasks()
        
        self.logger.info("TaskManager 初始化完成")
    
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE,
                    FOREIGN KEY (chat_id) REFERENCES chats(chat_id) ON DELETE CASCADE
                )
            """)
            
            conn.commit()
            self.logger.info("任务数据库表初始化完成")
        except Exception as e:
            self.logger.error("初始化任务数据库表失败: %s", e)
            conn.rollback()
            raise
    
    def _load_persistent_tasks(self):
        """从数据库加载持久化的任务"""
        try:
            conn = self.db._get_connection()
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status IN (?, ?)",
                (TaskStatus.PENDING.value, TaskStatus.RUNNING.value)
            ).fetchall()
            
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
                        "status": row["status"],
                        "created_at": row["created_at"],
                        "started_at": row["started_at"],
                        "completed_at": row["completed_at"],
                        "result": json.loads(row["result"]) if row["result"] else None,
                        "error": row["error"]
                    }
                    task = Task.from_dict(task_data)
                    self.tasks[task.task_id] = task
                    
                    # 如果是定时任务且状态为PENDING，重新调度
                    if task.task_type == TaskType.REMINDER and task.status == TaskStatus.PENDING and task.scheduled_time:
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
                 status, created_at, started_at, completed_at, result, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task.task_id,
                task.task_type.value,
                task.user_id,
                task.chat_id,
                json.dumps(task.params, ensure_ascii=False),
                priority_value,
                task.scheduled_time.isoformat() if task.scheduled_time else None,
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
                elif status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
                    task.completed_at = datetime.now()
                
                if result is not None:
                    task.result = result
                if error is not None:
                    task.error = error
                
                self._save_task(task)
    
    def _schedule_reminder_task(self, task: Task):
        """调度提醒任务"""
        if not task.scheduled_time:
            return
        
        # 计算延迟时间（秒）
        now = datetime.now()
        delay_seconds = max(0, (task.scheduled_time - now).total_seconds())
        
        if delay_seconds > 0:
            # 使用schedule库调度一次性任务
            def reminder_job():
                self.logger.info("执行提醒任务: %s", task.task_id)
                self.execute_task(task.task_id)
                # 任务执行后从调度器中移除
                return schedule.CancelJob
            
            # 使用schedule.every()创建一次性任务
            job = self.scheduler.every(delay_seconds).seconds.do(reminder_job)
            job.tag(task.task_id)  # 给任务添加标签以便后续管理
            
            self.logger.info("已调度提醒任务 %s 在 %s 执行 (延迟: %d秒)", 
                           task.task_id, task.scheduled_time, delay_seconds)
        else:
            # 如果时间已过，立即执行
            self.logger.info("提醒任务 %s 时间已过，立即执行", task.task_id)
            self.execute_task(task.task_id)
    
    def _run_scheduler(self):
        """运行调度器线程"""
        while self.running:
            self.scheduler.run_pending()
            time.sleep(1)
    
    def create_task(self, task_type: TaskType, user_id: int, chat_id: int, 
                   params: Dict[str, Any], priority: TaskPriority = TaskPriority.NORMAL,
                   scheduled_time: Optional[datetime] = None) -> str:
        """创建新任务"""
        task_id = str(uuid.uuid4())
        
        task = Task(
            task_id=task_id,
            task_type=task_type,
            user_id=user_id,
            chat_id=chat_id,
            params=params,
            priority=priority,
            scheduled_time=scheduled_time
        )
        
        with self.lock:
            self.tasks[task_id] = task
            self._save_task(task)
        
        # 如果是提醒任务，进行调度
        if task_type == TaskType.REMINDER and scheduled_time:
            self._schedule_reminder_task(task)
        
        self.logger.info("创建任务: %s (类型: %s, 用户: %d)", task_id, task_type.value, user_id)
        return task_id
    
    def execute_task(self, task_id: str) -> Future:
        """执行任务"""
        if task_id not in self.tasks:
            raise ValueError(f"任务不存在: {task_id}")
        
        task = self.tasks[task_id]
        
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
            elif task.task_type == TaskType.REMINDER:
                return self._execute_reminder_task(task)
            elif task.task_type == TaskType.ANALYSIS:
                return self._execute_analysis_task(task)
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
        
        # 创建DeepSeek Reasoner客户端
        from config import Config
        chat = DeepSeekChat(api_key=Config.DEEPSEEK_API_KEY)
        chat.set_model("deepseek-reasoner")  # 切换到reasoner模型
        
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
            "model": "deepseek-reasoner",
            "timestamp": datetime.now().isoformat()
        }
        
        # 保存结果到数据库
        self._save_task_result(task.task_id, reasoning_result)
        
        self.logger.info("推理任务完成: %s", task.task_id)
        return result
    
    def _execute_reminder_task(self, task: Task) -> Dict[str, Any]:
        """执行提醒任务"""
        self.logger.info("执行提醒任务: %s", task.task_id)
        
        # 获取提醒内容
        reminder_text = task.params.get("text", "提醒时间到了！")
        
        # 不再生成AI提醒消息，改为发送原始提醒内容给AI处理
        # AI将在app.py中生成自然的提醒消息
        
        result = {
            "reminder_text": reminder_text,
            "user_id": task.user_id,
            "chat_id": task.chat_id,
            "timestamp": datetime.now().isoformat(),
            "task_type": "reminder",
            "requires_ai_notification": True,  # 标记需要AI通知
            "skip_memory": True  # 标记跳过记忆化
        }
        
        # 不再保存AI提醒消息到任务结果
        # 只保存基本信息供后续处理
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
            
            # 触发任务完成通知
            self._notify_task_completion(task_id, result)
            
        except Exception as e:
            self._update_task_status(task_id, TaskStatus.FAILED, error=str(e))
            self.logger.error("任务失败: %s, 错误: %s", task_id, e)
    
    def _notify_task_completion(self, task_id: str, result: Dict[str, Any]):
        """通知任务完成（需要外部实现推送逻辑）"""
        # 这里只是一个占位符，实际推送逻辑需要在app.py中实现
        self.logger.info("任务 %s 完成，准备通知用户", task_id)
        
        # 将任务完成事件放入队列，由主应用处理
        if hasattr(self, 'completion_queue'):
            self.completion_queue.put((task_id, result))
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务信息"""
        return self.tasks.get(task_id)
    
    def get_user_tasks(self, user_id: int, status: Optional[TaskStatus] = None) -> List[Task]:
        """获取用户的任务列表"""
        with self.lock:
            tasks = [task for task in self.tasks.values() if task.user_id == user_id]
            
            if status:
                tasks = [task for task in tasks if task.status == status]
            
            return sorted(tasks, key=lambda t: t.created_at, reverse=True)
    
    def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        with self.lock:
            if task_id not in self.tasks:
                return False
            
            task = self.tasks[task_id]
            if task.status not in [TaskStatus.PENDING, TaskStatus.RUNNING]:
                return False
            
            task.status = TaskStatus.CANCELLED
            task.completed_at = datetime.now()
            self._save_task(task)
            
            # 如果是定时任务，从调度器中移除
            if task.task_type == TaskType.REMINDER:
                # schedule库没有直接取消任务的方法，我们标记任务状态即可
                pass
            
            self.logger.info("任务已取消: %s", task_id)
            return True
    
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
        
        # 2. 关键词分析
        complex_count = 0
        for keyword in self.complex_keywords:
            if keyword in text:
                complex_count += 1
        
        if complex_count > 0:
            keyword_score = min(0.4, complex_count * 0.1)
            score += keyword_score
            reasons.append(f"包含 {complex_count} 个复杂关键词")
        
        # 3. 简单关键词抵消
        simple_count = 0
        for keyword in self.simple_keywords:
            if keyword in text:
                simple_count += 1
        
        if simple_count > 0:
            score = max(0, score - (simple_count * 0.05))
            reasons.append(f"包含 {simple_count} 个简单关键词")
        
        # 4. 上下文复杂度
        if context_length > 10:
            score += 0.1
            reasons.append(f"上下文较复杂 ({context_length} 轮对话)")
        
        # 5. 问题类型判断
        question_types = ["?", "？", "什么", "如何", "为什么", "怎样"]
        question_count = sum(1 for q in question_types if q in text)
        if question_count > 1:
            score += 0.1
            reasons.append("包含多个疑问点")
        
        # 确保分数在0-1之间
        score = max(0, min(1, score))
        
        # 判断是否复杂
        is_complex = score >= 0.4  # 阈值可配置
        
        suggestion = "使用reasoner模型进行深入分析" if is_complex else "使用chat模型直接回复"
        
        return {
            "is_complex": is_complex,
            "score": round(score, 2),
            "reasons": reasons,
            "suggestion": suggestion
        }


# 全局任务管理器实例
_task_manager: Optional[TaskManager] = None

def get_task_manager(db: Optional[ChatDBManager] = None) -> TaskManager:
    """获取全局任务管理器实例"""
    global _task_manager
    if _task_manager is None and db is not None:
        _task_manager = TaskManager(db)
    return _task_manager

def set_task_manager(manager: TaskManager):
    """设置全局任务管理器实例"""
    global _task_manager
    _task_manager = manager
