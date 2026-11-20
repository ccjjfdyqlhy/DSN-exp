# harness/todo.py
# Todo plans: the state behind "what is this agent working through".
#
# Moved here from an application plugin and its store. The plan/item model,
# progress bookkeeping and change notifications were app-level, so every product
# that wanted a visible task list rebuilt them. Nothing here knows about chat
# rooms, transports or sub-agents: an app puts its own keys in
# ``TodoPlan.meta`` and follows changes with ``add_listener`` (or the
# ``revision`` counter, for a UI that polls once a frame).
#
# The store is thread-safe, optionally file-backed (one JSON document, written
# atomically), and reports every mutation as an event dict.

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

logger = logging.getLogger("aicf.harness.todo")

PLAN_PREFIX = "todo-"

ITEM_STATUSES = ("pending", "in_progress", "completed", "failed", "skipped")
PLAN_STATUSES = ("planning", "executing", "completed", "failed")
# an item in one of these is done as far as the progress bar is concerned
SETTLED_ITEM_STATUSES = ("completed", "failed", "skipped")
SETTLED_PLAN_STATUSES = ("completed", "failed")

# fields ``update_item`` may patch on an item
_ITEM_FIELDS = ("title", "description", "status", "agent", "model", "prompt",
                "needs_sub_agent", "result", "error", "priority",
                "dependencies")


def _now() -> float:
    return time.time()


@dataclass
class TodoItem:
    """One step of a plan."""

    id: str
    title: str
    description: str = ""
    status: str = "pending"          # pending | in_progress | completed | failed | skipped
    agent: str = ""                  # the sub-agent that owns/ran it
    model: str = ""
    prompt: str = ""                 # what the sub-agent was told
    needs_sub_agent: Optional[bool] = None
    result: str = ""
    error: str = ""
    priority: int = 0
    dependencies: list[str] = field(default_factory=list)

    @property
    def settled(self) -> bool:
        return self.status in SETTLED_ITEM_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "agent": self.agent,
            "model": self.model,
            "prompt": self.prompt,
            "needs_sub_agent": self.needs_sub_agent,
            "result": self.result,
            "error": self.error,
            "priority": self.priority,
            "dependencies": list(self.dependencies),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TodoItem":
        # Accepts the legacy adcode/standard-tool shape too ({"text": ...}).
        title = str(raw.get("title") or raw.get("text") or "").strip()
        status = str(raw.get("status") or "pending").strip()
        if status not in ITEM_STATUSES:
            status = "completed" if status in ("done", "complete") else "pending"
        dependencies = raw.get("dependencies")
        return cls(
            id=str(raw.get("id") or ""),
            title=title,
            description=str(raw.get("description") or ""),
            status=status,
            agent=str(raw.get("agent") or raw.get("sub_agent_id") or ""),
            model=str(raw.get("model") or raw.get("sub_agent_model") or ""),
            prompt=str(raw.get("prompt") or raw.get("sub_agent_prompt") or ""),
            needs_sub_agent=raw.get("needs_sub_agent"),
            result=str(raw.get("result") or ""),
            error=str(raw.get("error") or ""),
            priority=int(raw.get("priority") or 0),
            dependencies=[str(item) for item in dependencies]
            if isinstance(dependencies, list) else [],
        )


@dataclass
class TodoPlan:
    """A plan: the items plus where the work stands."""

    plan_id: str
    items: list[TodoItem] = field(default_factory=list)
    status: str = "planning"          # planning | executing | completed | failed
    current_item: str = ""
    progress: float = 0.0
    created_at: float = 0.0
    summary: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def item(self, item_id: str) -> Optional[TodoItem]:
        for item in self.items:
            if item.id == item_id:
                return item
        return None

    @property
    def done_count(self) -> int:
        return sum(1 for item in self.items if item.settled)

    @property
    def open_count(self) -> int:
        return len(self.items) - self.done_count

    @property
    def current(self) -> Optional[TodoItem]:
        """The item to show as "being worked on"."""
        if self.current_item:
            item = self.item(self.current_item)
            if item is not None:
                return item
        for item in self.items:
            if item.status == "in_progress":
                return item
        for item in self.items:
            if item.status == "pending":
                return item
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "status": self.status,
            "current_item": self.current_item,
            "progress": self.progress,
            "created_at": self.created_at,
            "summary": self.summary,
            "meta": dict(self.meta),
            "items": [item.to_dict() for item in self.items],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TodoPlan":
        items = [TodoItem.from_dict(item) for item in raw.get("items") or []
                 if isinstance(item, dict)]
        for index, item in enumerate(items):
            if not item.id:
                item.id = f"item-{index:02d}"
        status = str(raw.get("status") or "planning")
        if status not in PLAN_STATUSES:
            status = "planning"
        meta = raw.get("meta")
        return cls(
            plan_id=str(raw.get("plan_id") or raw.get("todo_id") or ""),
            items=items,
            status=status,
            current_item=str(raw.get("current_item") or ""),
            progress=float(raw.get("progress") or 0.0),
            created_at=float(raw.get("created_at") or 0.0),
            summary=str(raw.get("summary") or ""),
            meta=dict(meta) if isinstance(meta, dict) else {},
        )


class TodoStore:
    """Plans, items and change events -- shared by every agent in the process.

    Args:
        path: optional JSON file to load on construction and rewrite after
            every change.  The file holds one document:
            ``{"version": 1, "plans": [...]}``.  A legacy bare list of items
            (the shape the old ``project.todo`` tool wrote) is read as a
            single finished-by-hand plan instead of being discarded.
        backend: optional document store (``infra.store.DocumentStore``).
            When given, the plan lives **in that store** instead of in a
            file -- which is how an app keeps its state out of the project
            directory it is working on.  The file route stays for tools and
            for tests that want a file they can look at.
        key: the document key to use when a backend is given.
    """

    def __init__(self, path: str | os.PathLike[str] | None = None, *,
                 backend: Any = None, key: str = "todo.plan") -> None:
        self.path = Path(path) if path is not None else None
        self._backend = backend
        self._key = str(key)
        self._plans: dict[str, TodoPlan] = {}
        self._listeners: list[Callable[[dict[str, Any]], None]] = []
        self._lock = threading.RLock()
        # bumped on every mutation; a UI polls it once a frame
        self.revision = 0
        # finished plans kept in the file before the oldest are dropped
        self.max_plans = 20
        if self.path is not None or self._backend is not None:
            self.load()

    # ── listeners ───────────────────────────────────────────
    def add_listener(self, listener: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    # ── plans ───────────────────────────────────────────────
    def create_plan(self, items: Optional[Iterable[dict[str, Any]]] = None,
                    *, plan_id: str = "",
                    meta: Optional[dict[str, Any]] = None) -> TodoPlan:
        plan = TodoPlan(plan_id=plan_id or f"{PLAN_PREFIX}{uuid.uuid4().hex[:12]}",
                        created_at=_now(), meta=dict(meta or {}))
        if items is not None:
            plan.items = self._build_items(items)
            plan.status = "executing" if plan.items else "planning"
        with self._lock:
            self._plans[plan.plan_id] = plan
            self._recount(plan)
            self._changed({"type": "plan_created", "plan_id": plan.plan_id,
                           "plan": plan.to_dict()})
            return plan

    def set_items(self, plan_id: str,
                  items: Iterable[dict[str, Any]]) -> Optional[TodoPlan]:
        with self._lock:
            plan = self._plans.get(plan_id)
            if plan is None:
                return None
            plan.items = self._build_items(items)
            plan.status = "executing"
            plan.current_item = ""
            self._recount(plan)
            self._changed({"type": "items_set", "plan_id": plan_id,
                           "plan": plan.to_dict()})
            return plan

    def add_item(self, plan_id: str, title: str, **fields: Any) -> Optional[TodoItem]:
        title = str(title or "").strip()
        if not title:
            raise ValueError("title must not be empty")
        with self._lock:
            plan = self._plans.get(plan_id)
            if plan is None:
                return None
            item = TodoItem(id=f"item-{len(plan.items):02d}", title=title)
            for key, value in fields.items():
                if key in _ITEM_FIELDS:
                    setattr(item, key, value)
            if item.status not in ITEM_STATUSES:
                item.status = "pending"
            plan.items.append(item)
            if plan.status == "planning":
                plan.status = "executing"
            self._recount(plan)
            self._changed({"type": "item_added", "plan_id": plan_id,
                           "item_id": item.id, "item": item.to_dict(),
                           "plan": plan.to_dict()})
            return item

    def update_item(self, plan_id: str, item_id: str,
                    **fields: Any) -> Optional[TodoItem]:
        status = fields.get("status")
        if status is not None and status not in ITEM_STATUSES:
            # Validate before touching the item: a bad call must not leave a
            # half-applied status behind.
            raise ValueError(f"unknown status: {status}")
        with self._lock:
            plan = self._plans.get(plan_id)
            if plan is None:
                return None
            item = plan.item(item_id)
            if item is None:
                return None
            for key, value in fields.items():
                if key in _ITEM_FIELDS and value is not None:
                    setattr(item, key, value)
            if item.status == "in_progress":
                plan.current_item = item.id
            elif plan.current_item == item.id:
                plan.current_item = ""
            self._recount(plan)
            self._changed({"type": "item_updated", "plan_id": plan_id,
                           "item_id": item.id, "item": item.to_dict(),
                           "plan": plan.to_dict()})
            return item

    def remove_item(self, plan_id: str, item_id: str) -> bool:
        with self._lock:
            plan = self._plans.get(plan_id)
            if plan is None:
                return False
            item = plan.item(item_id)
            if item is None:
                return False
            plan.items.remove(item)
            if plan.current_item == item_id:
                plan.current_item = ""
            self._recount(plan)
            self._changed({"type": "item_removed", "plan_id": plan_id,
                           "item_id": item_id, "plan": plan.to_dict()})
            return True

    def set_completed(self, plan_id: str, summary: str = "") -> None:
        with self._lock:
            plan = self._plans.get(plan_id)
            if plan is None:
                return
            plan.status = "completed"
            plan.progress = 1.0
            plan.summary = summary
            self._changed({"type": "plan_completed", "plan_id": plan_id,
                           "summary": summary, "plan": plan.to_dict()})

    def set_failed(self, plan_id: str, error: str = "") -> None:
        with self._lock:
            plan = self._plans.get(plan_id)
            if plan is None:
                return
            plan.status = "failed"
            plan.summary = error
            self._changed({"type": "plan_failed", "plan_id": plan_id,
                           "error": error, "plan": plan.to_dict()})

    def drop_plan(self, plan_id: str) -> bool:
        with self._lock:
            removed = self._plans.pop(plan_id, None)
            if removed is None:
                return False
            self._changed({"type": "plan_dropped", "plan_id": plan_id})
            return True

    # ── queries ─────────────────────────────────────────────
    def get_plan(self, plan_id: str) -> Optional[TodoPlan]:
        with self._lock:
            return self._plans.get(plan_id)

    def get_plan_dict(self, plan_id: str) -> Optional[dict[str, Any]]:
        plan = self.get_plan(plan_id)
        return plan.to_dict() if plan is not None else None

    def active_plan(self) -> Optional[TodoPlan]:
        """The newest plan that is still being worked on, if any."""
        with self._lock:
            live = [plan for plan in self._plans.values()
                    if plan.status not in SETTLED_PLAN_STATUSES]
            if not live:
                return None
            return max(live, key=lambda plan: plan.created_at)

    def list_plans(self, *, status: Optional[str] = None,
                   meta: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
        with self._lock:
            rows = []
            for plan in self._plans.values():
                if status is not None and plan.status != status:
                    continue
                if meta and any(plan.meta.get(key) != value
                                for key, value in meta.items()):
                    continue
                rows.append({"plan_id": plan.plan_id, "status": plan.status,
                             "progress": plan.progress,
                             "item_count": len(plan.items),
                             "created_at": plan.created_at,
                             "meta": dict(plan.meta)})
            return sorted(rows, key=lambda row: row["created_at"])

    def cleanup_old(self, max_age_seconds: float = 3600) -> int:
        """Drop finished plans older than ``max_age_seconds``."""
        cutoff = _now() - max_age_seconds
        removed = 0
        with self._lock:
            for plan_id in list(self._plans):
                plan = self._plans[plan_id]
                if plan.status in SETTLED_PLAN_STATUSES and plan.created_at < cutoff:
                    del self._plans[plan_id]
                    removed += 1
        return removed

    # ── persistence ─────────────────────────────────────────
    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {"version": 1,
                    "plans": [plan.to_dict() for plan in self._plans.values()]}

    def load(self) -> None:
        """Read the plan (silently, once).

        The backend route comes first: an app that keeps its state in a
        database has no file to read.  An unreadable file stays on disk.
        """
        if self._backend is not None:
            try:
                raw = self._backend.load(self._key)
            except Exception as error:  # noqa: BLE001 - a bad store must not
                logger.warning("todo store %s is unreadable: %s",
                               self._key, error)
                return
            if not isinstance(raw, dict):
                return
            self._adopt(raw)
            return
        if self.path is None or not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            logger.warning("todo store %s is unreadable: %s", self.path, error)
            return
        self._adopt(raw)

    def _adopt(self, raw: Any) -> None:
        """Take a raw document as the current state."""
        with self._lock:
            self._plans.clear()
            if isinstance(raw, list):
                plan = self._legacy_plan(raw)
                if plan is not None:
                    self._plans[plan.plan_id] = plan
            elif isinstance(raw, dict):
                for entry in raw.get("plans") or []:
                    if not isinstance(entry, dict):
                        continue
                    plan = TodoPlan.from_dict(entry)
                    if plan.plan_id:
                        self._plans[plan.plan_id] = plan
            for plan in self._plans.values():
                self._recount(plan)

    def save(self) -> None:
        with self._lock:
            self._trim()
            document = self.to_dict()
        if self._backend is not None:
            try:
                self._backend.save(self._key, document)
            except Exception as error:  # noqa: BLE001 - a broken store must
                logger.warning("todo store %s could not be saved: %s",
                               self._key, error)
            return
        if self.path is None:
            return
        payload = json.dumps(document, ensure_ascii=False, indent=2)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=str(self.path.parent),
                                    prefix=f".{self.path.name}.",
                                    suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self.path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    # ── internals ───────────────────────────────────────────
    def _build_items(self, items: Iterable[dict[str, Any]]) -> list[TodoItem]:
        built: list[TodoItem] = []
        for index, entry in enumerate(items):
            if isinstance(entry, str):
                entry = {"title": entry}
            if not isinstance(entry, dict):
                continue
            item = TodoItem.from_dict(entry)
            item.title = item.title.strip()
            if not item.title:
                continue
            item.id = f"item-{index:02d}"
            if item.status not in ITEM_STATUSES:
                item.status = "pending"
            built.append(item)
        return built

    def _legacy_plan(self, items: list[Any]) -> Optional[TodoPlan]:
        """The old flat ``[{text, status}]`` list becomes one plan."""
        entries = [entry for entry in items if isinstance(entry, dict)]
        if not entries:
            return None
        plan = TodoPlan(plan_id=f"{PLAN_PREFIX}legacy",
                        created_at=_now(), status="executing",
                        meta={"legacy": True})
        plan.items = self._build_items(entries)
        self._recount(plan)
        return plan

    def _trim(self) -> None:
        """Keep the file bounded: every unfinished plan, plus recent history."""
        finished = sorted((plan for plan in self._plans.values()
                           if plan.status in SETTLED_PLAN_STATUSES),
                          key=lambda plan: plan.created_at)
        while len(finished) > self.max_plans:
            self._plans.pop(finished.pop(0).plan_id, None)

    def _recount(self, plan: TodoPlan) -> None:
        total = len(plan.items)
        plan.progress = (plan.done_count / total) if total else 0.0
        if total and plan.done_count >= total and plan.status not in SETTLED_PLAN_STATUSES:
            plan.status = "completed"

    def _changed(self, event: dict[str, Any]) -> None:
        """Record a mutation: bump the revision, persist, then notify."""
        with self._lock:
            self.revision += 1
            event.setdefault("ts", _now())
            event["revision"] = self.revision
            listeners = list(self._listeners)
        try:
            self.save()
        except (OSError, ValueError) as error:
            logger.warning("todo store %s could not be written: %s",
                           self.path, error)
        for listener in listeners:
            try:
                listener(event)
            except Exception:      # noqa: BLE001 - a listener must not break the call
                logger.exception("todo listener failed")


def default_todo_path(cwd: str | os.PathLike[str] = ".") -> Path:
    """Where an app's todo list lives inside a project."""
    return Path(cwd) / ".harness_todo.json"
