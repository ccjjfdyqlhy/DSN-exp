# plugins/builtin/todo_store.py
# Todo 计划（DSN 侧适配层）— 状态模型已下沉到 harness.todo
#
# 计划/条目、进度计算、变更事件现在都在 harness/todo.py；这里只保留 DSN
# 需要的东西：按 chat/user 归属、SSE 文本格式的订阅队列，以及历史字段名
# （todo_id / sub_agent_id / overall_progress）的兼容映射。

from __future__ import annotations

import json
import queue
import threading
import time
from typing import Any, Optional

from harness.todo import (      # noqa: F401 - re-exported for the plugin
    TodoItem,
    TodoPlan,
    TodoStore as HarnessTodoStore,
)

TODOS_PREFIX = "todo-"

# SDK 事件类型 -> DSN 对外事件名
_EVENT_NAMES = {
    "plan_created": "plan_created",
    "items_set": "plan_started",
    "item_added": "item_added",
    "item_updated": "item_updated",
    "item_removed": "item_removed",
    "plan_completed": "plan_completed",
    "plan_failed": "plan_failed",
    "plan_dropped": "plan_dropped",
}


def _item_dict(item: TodoItem) -> dict[str, Any]:
    """An item in the field names this app's clients already use."""
    return {
        "id": item.id,
        "title": item.title,
        "description": item.description,
        "status": item.status,
        "sub_agent_id": item.agent,
        "sub_agent_model": item.model,
        "sub_agent_prompt": item.prompt,
        "needs_sub_agent": item.needs_sub_agent,
        "result": item.result,
        "error": item.error,
        "priority": item.priority,
        "dependencies": list(item.dependencies),
    }


class TodoStore:
    """DSN 的 todo 门面：单例 + SSE 订阅。

    真正的状态在 ``harness.todo.TodoStore`` 里；这一层负责把 chat/user 归属
    放进 ``plan.meta``，并把变更事件翻成 SSE 文本。
    """

    _instance: Optional["TodoStore"] = None
    _instance_lock = threading.Lock()

    def __init__(self, store: Optional[HarnessTodoStore] = None) -> None:
        self._store = store or HarnessTodoStore()
        self._subscribers: dict[str, list[queue.Queue]] = {}
        self._lock = threading.Lock()
        self._max_subscriber_queue = 200
        self._store.add_listener(self._publish)

    # ── 单例 ──

    @classmethod
    def get_instance(cls) -> "TodoStore":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── 计划 CRUD ──

    def create_plan(self, chat_id: int, user_id: int) -> TodoPlan:
        return self._store.create_plan(meta={"chat_id": chat_id,
                                             "user_id": user_id})

    def set_items(self, todo_id: str, items: list[dict]) -> None:
        self._store.set_items(todo_id, items)

    def update_item(self, todo_id: str, item_id: str,
                    status: str | None = None,
                    sub_agent_id: str | None = None,
                    result: str | None = None,
                    error: str | None = None) -> None:
        self._store.update_item(todo_id, item_id, status=status,
                                agent=sub_agent_id, result=result, error=error)

    def set_completed(self, todo_id: str, summary: str = "") -> None:
        self._store.set_completed(todo_id, summary)

    def set_failed(self, todo_id: str, error: str = "") -> None:
        self._store.set_failed(todo_id, error)

    def get_plan(self, todo_id: str) -> Optional[TodoPlan]:
        return self._store.get_plan(todo_id)

    def get_plan_dict(self, todo_id: str) -> dict | None:
        plan = self._store.get_plan(todo_id)
        if plan is None:
            return None
        return {
            "todo_id": plan.plan_id,
            "chat_id": plan.meta.get("chat_id", 0),
            "user_id": plan.meta.get("user_id", 0),
            "status": plan.status,
            "overall_progress": plan.progress,
            "current_item": plan.current_item,
            "items": [_item_dict(item) for item in plan.items],
            "summary": plan.summary,
            "created_at": plan.created_at,
        }

    def list_plans(self, user_id: int = None, chat_id: int = None) -> list[dict]:
        rows = self._store.list_plans()
        for row in rows:
            meta = row.get("meta") or {}
            row["todo_id"] = row["plan_id"]
            row["overall_progress"] = row["progress"]
            row["chat_id"] = meta.get("chat_id", 0)
            row["user_id"] = meta.get("user_id", 0)
        if user_id is not None:
            rows = [row for row in rows if row["user_id"] == user_id]
        if chat_id is not None:
            rows = [row for row in rows if row["chat_id"] == chat_id]
        return rows

    def cleanup_old(self, max_age_seconds: float = 3600) -> int:
        return self._store.cleanup_old(max_age_seconds)

    # ── SSE 订阅 ──

    def subscribe(self, todo_id: str) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=self._max_subscriber_queue)
        with self._lock:
            self._subscribers.setdefault(todo_id, []).append(q)
        snapshot = self.get_plan_dict(todo_id)
        if snapshot is not None:
            try:
                q.put_nowait(_sse({"type": "snapshot", "plan": snapshot}))
            except queue.Full:
                pass
        return q

    def unsubscribe(self, todo_id: str, q: queue.Queue) -> None:
        with self._lock:
            subs = self._subscribers.get(todo_id, [])
            if q in subs:
                subs.remove(q)

    def _publish(self, event: dict[str, Any]) -> None:
        plan_id = str(event.get("plan_id") or "")
        payload = dict(event)
        payload["type"] = _EVENT_NAMES.get(payload.get("type", ""),
                                          payload.get("type", ""))
        payload["todo_id"] = plan_id
        item = payload.pop("item", None)
        if isinstance(item, dict):
            item = TodoItem.from_dict(item)
            payload["item"] = _item_dict(item)
        plan = payload.pop("plan", None)
        if isinstance(plan, dict):
            payload["progress"] = plan.get("progress", 0.0)
        if payload.get("type") == "plan_started" and isinstance(plan, dict):
            payload["total_items"] = len(plan.get("items") or [])
            payload["items"] = [
                {"id": entry.get("id"), "title": entry.get("title"),
                 "status": entry.get("status")}
                for entry in plan.get("items") or []
            ]
        if payload.get("type") == "item_updated" and isinstance(plan, dict):
            payload.setdefault("status", None)
        payload["timestamp"] = time.time()
        with self._lock:
            queues = list(self._subscribers.get(plan_id, []))
        for q in queues:
            try:
                q.put_nowait(_sse(payload))
            except queue.Full:
                pass


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def get_todo_store() -> TodoStore:
    return TodoStore.get_instance()
