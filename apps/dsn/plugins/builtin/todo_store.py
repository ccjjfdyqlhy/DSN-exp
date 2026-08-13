# plugins/builtin/todo_store.py
# Todo 状态仓库 — 计划状态管理 + SSE 发布/订阅

from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

TODOS_PREFIX = "todo-"


@dataclass
class TodoItem:
    id: str
    title: str
    description: str = ""
    status: str = "pending"       # pending | in_progress | completed | failed
    sub_agent_id: str = ""        # 子代理 task_id (如果并行执行)
    sub_agent_model: str = ""     # 子代理使用的模型
    sub_agent_prompt: str = ""    # 主模型(assigner)书写的子代理 system prompt
    needs_sub_agent: Optional[bool] = None   # 主模型(assigner)决定是否派子代理
    result: str = ""
    error: str = ""
    priority: int = 0
    dependencies: list[str] = field(default_factory=list)


@dataclass
class TodoPlan:
    todo_id: str
    chat_id: int
    user_id: int
    items: list[TodoItem] = field(default_factory=list)
    status: str = "planning"      # planning | executing | completed | failed
    current_item: str = ""        # 当前正在执行的 item id
    overall_progress: float = 0.0
    created_at: float = 0.0
    summary: str = ""             # AI 总结的最终结果


class TodoStore:
    """
    Todo 状态仓库 — 线程安全的内存存储 + SSE 订阅/发布。

    每个 todo 会话有一个 event queue，SSE 端点 subscribe 后从中读取事件。
    TodoPlugin 在状态变更时 push 事件。
    """

    _instance: Optional[TodoStore] = None
    _instance_lock = threading.Lock()

    def __init__(self):
        self._plans: dict[str, TodoPlan] = {}
        self._subscribers: dict[str, list[queue.Queue]] = {}
        self._lock = threading.Lock()
        self._max_subscriber_queue = 200  # 每个订阅者队列最大事件数

    # ── 单例 ──

    @classmethod
    def get_instance(cls) -> TodoStore:
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── 计划 CRUD ──

    def create_plan(self, chat_id: int, user_id: int) -> TodoPlan:
        todo_id = f"{TODOS_PREFIX}{uuid.uuid4().hex[:12]}"
        plan = TodoPlan(
            todo_id=todo_id,
            chat_id=chat_id,
            user_id=user_id,
            created_at=time.time(),
        )
        with self._lock:
            self._plans[todo_id] = plan
        self._push_event(todo_id, {"type": "plan_created", "todo_id": todo_id})
        return plan

    def set_items(self, todo_id: str, items: list[dict]) -> None:
        with self._lock:
            plan = self._plans.get(todo_id)
            if not plan:
                return
            plan.items = [
                TodoItem(
                    id=f"item-{i:02d}",
                    title=item.get("title", ""),
                    description=item.get("description", ""),
                    priority=item.get("priority", 0),
                    dependencies=item.get("dependencies", []),
                    sub_agent_model=item.get("sub_agent_model", ""),
                    sub_agent_prompt=item.get("sub_agent_prompt", ""),
                    needs_sub_agent=item.get("needs_sub_agent"),
                )
                for i, item in enumerate(items)
            ]
            plan.status = "executing"
        self._push_event(todo_id, {
            "type": "plan_started",
            "todo_id": todo_id,
            "total_items": len(items),
            "items": [{"id": it.id, "title": it.title, "status": it.status}
                       for it in self._plans[todo_id].items],
        })

    def update_item(self, todo_id: str, item_id: str,
                    status: str | None = None,
                    sub_agent_id: str | None = None,
                    result: str | None = None,
                    error: str | None = None) -> None:
        with self._lock:
            plan = self._plans.get(todo_id)
            if not plan:
                return
            for item in plan.items:
                if item.id == item_id:
                    if status is not None:
                        item.status = status
                    if sub_agent_id is not None:
                        item.sub_agent_id = sub_agent_id
                    if result is not None:
                        item.result = result
                    if error is not None:
                        item.error = error
                    plan.current_item = item_id
                    break

            # 更新整体进度
            total = len(plan.items)
            if total > 0:
                done = sum(1 for it in plan.items
                           if it.status in ("completed", "failed"))
                plan.overall_progress = done / total
                if done >= total:
                    plan.status = "completed"

        self._push_event(todo_id, {
            "type": "item_updated",
            "todo_id": todo_id,
            "item_id": item_id,
            "status": status,
            "progress": self._plans[todo_id].overall_progress if todo_id in self._plans else 0.0,
        })

    def set_completed(self, todo_id: str, summary: str = "") -> None:
        with self._lock:
            plan = self._plans.get(todo_id)
            if plan:
                plan.status = "completed"
                plan.overall_progress = 1.0
                plan.summary = summary
        self._push_event(todo_id, {
            "type": "plan_completed",
            "todo_id": todo_id,
            "summary": summary,
        })

    def set_failed(self, todo_id: str, error: str = "") -> None:
        with self._lock:
            plan = self._plans.get(todo_id)
            if plan:
                plan.status = "failed"
                plan.summary = error
        self._push_event(todo_id, {
            "type": "plan_failed",
            "todo_id": todo_id,
            "error": error,
        })

    def get_plan(self, todo_id: str) -> Optional[TodoPlan]:
        with self._lock:
            return self._plans.get(todo_id)

    def get_plan_dict(self, todo_id: str) -> dict | None:
        plan = self.get_plan(todo_id)
        if not plan:
            return None
        return {
            "todo_id": plan.todo_id,
            "chat_id": plan.chat_id,
            "user_id": plan.user_id,
            "status": plan.status,
            "overall_progress": plan.overall_progress,
            "items": [
                {
                    "id": it.id,
                    "title": it.title,
                    "description": it.description,
                    "status": it.status,
                    "sub_agent_id": it.sub_agent_id,
                    "sub_agent_model": it.sub_agent_model,
                    "sub_agent_prompt": it.sub_agent_prompt,
                    "needs_sub_agent": it.needs_sub_agent,
                    "result": it.result,
                    "error": it.error,
                    "priority": it.priority,
                    "dependencies": it.dependencies,
                }
                for it in plan.items
            ],
            "summary": plan.summary,
            "created_at": plan.created_at,
        }

    # ── SSE 订阅 ──

    def subscribe(self, todo_id: str) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=self._max_subscriber_queue)
        with self._lock:
            self._subscribers.setdefault(todo_id, []).append(q)
        # 如果计划已存在，先推送当前状态 (SSE 格式)
        plan = self.get_plan(todo_id)
        if plan:
            snapshot = self.get_plan_dict(todo_id)
            if snapshot:
                payload = f"data: {json.dumps({'type': 'snapshot', 'plan': snapshot}, ensure_ascii=False)}\n\n"
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    pass
        return q

    def unsubscribe(self, todo_id: str, q: queue.Queue) -> None:
        with self._lock:
            subs = self._subscribers.get(todo_id, [])
            if q in subs:
                subs.remove(q)

    def _push_event(self, todo_id: str, event: dict) -> None:
        event["timestamp"] = time.time()
        payload = f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        with self._lock:
            for q in self._subscribers.get(todo_id, []):
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    pass  # 丢弃超出缓存的事件

    # ── 查询 ──

    def list_plans(self, user_id: int = None, chat_id: int = None) -> list[dict]:
        with self._lock:
            result = []
            for plan in self._plans.values():
                if user_id is not None and plan.user_id != user_id:
                    continue
                if chat_id is not None and plan.chat_id != chat_id:
                    continue
                result.append({
                    "todo_id": plan.todo_id,
                    "chat_id": plan.chat_id,
                    "user_id": plan.user_id,
                    "status": plan.status,
                    "overall_progress": plan.overall_progress,
                    "item_count": len(plan.items),
                    "created_at": plan.created_at,
                })
            return result

    def cleanup_old(self, max_age_seconds: float = 3600) -> int:
        """清理超过 max_age_seconds 的已完成计划"""
        cutoff = time.time() - max_age_seconds
        removed = 0
        with self._lock:
            for todo_id in list(self._plans):
                plan = self._plans[todo_id]
                if plan.status in ("completed", "failed") and plan.created_at < cutoff:
                    del self._plans[todo_id]
                    removed += 1
        return removed


# 模块级便捷入口
def get_todo_store() -> TodoStore:
    return TodoStore.get_instance()
