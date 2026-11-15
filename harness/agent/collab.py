# harness/agent/collab.py
# Multi-agent collaboration primitives: mailboxes, delegation and waiting.
#
# An AgentManager turns one ConversationEngine into the root of a team.  It
# registers a handful of collaboration tools (spawn / message / wait /
# interrupt / list), spawns child engines for delegated work, and delivers
# each child's outcome back to its parent's mailbox as a
# <subagent_update agent=... status=...> block.  The parent's turn loop
# consumes its mailbox before every model round, so updates reach the model
# as ordinary conversation content - no side channel, no magic.

from __future__ import annotations

import asyncio
import copy
import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from infra.models.base import IChatClient

from .engine import ConversationEngine
from .engine_config import AgentSettings, EngineConfig, ModelInfo
from ..tools.registry import AnnotatedTool, ManagedToolRegistry

logger = logging.getLogger("harness.collab")

ROOT_AGENT = 'root'
_TASK_NAME_RE = re.compile(r'^[a-z0-9_]+$')

SUBAGENT_SYSTEM = (
    'You are a sub-agent. Complete the delegated task and report the result. '
    'Do not talk to the terminal user; report blockers back to your parent. '
    'You may delegate sub-tasks yourself while depth allows it.'
)

# child lifecycle
PENDING_INIT = 'pending_init'
RUNNING = 'running'
INTERRUPTED = 'interrupted'
COMPLETED = 'completed'
ERRORED = 'errored'
SHUTDOWN = 'shutdown'

ACTIVE_STATES = (PENDING_INIT, RUNNING)


@dataclass
class AgentRecord:
    name: str
    parent: Optional[str]
    depth: int
    engine: ConversationEngine
    status: str = PENDING_INIT
    final_message: str = ''
    error: str = ''
    inbox: deque = field(default_factory=deque)
    task: asyncio.Task | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


def _sanitize(name: str) -> str:
    safe = re.sub(r'[^a-z0-9_]', '_', str(name).strip().lower())
    return safe.strip('_')[:48] or 'agent'


def _safe_history(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Context fork: user messages and plain assistant messages only.

    Tool-call exchanges belong to the turn that made them; copying them into
    a fresh child leaves dangling tool results no provider will accept.
    """
    return [copy.deepcopy(m) for m in messages
            if m.get('role') == 'user'
            or (m.get('role') == 'assistant' and not m.get('tool_calls'))]


def _tail_text(engine: ConversationEngine, limit: int = 400) -> str:
    for item in reversed(engine.items_snapshot()):
        if item.kind == 'assistant' and item.text:
            return item.text[-limit:]
    return ''


class AgentManager:
    """Delegation and mailboxes over a tree of ConversationEngines.

    The root engine is the one the application drives; children are spawned
    through the ``spawn_agent`` tool (or ``spawn()`` directly).  Every agent
    owns an inbox; a child posts one ``<subagent_update>`` block to its
    parent when it finishes, and the parent stages its mailbox as a user
    message before the next model round.
    """

    def __init__(self, *, client: IChatClient, registry: ManagedToolRegistry,
                 model: ModelInfo | None = None,
                 config: AgentSettings | None = None,
                 cwd: str = '',
                 store=None) -> None:
        self._client = client
        self._registry = registry
        self._model = model or ModelInfo()
        self.config = config or AgentSettings()
        self._cwd = cwd
        self._store = store
        self._agents: dict[str, AgentRecord] = {}
        self._condition: asyncio.Condition | None = None
        self._activity_version = 0
        self._events: deque[tuple[str, dict]] = deque(maxlen=2_000)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._shutdown = False

    # ── wiring ──────────────────────────────────────────────
    def attach(self, engine: ConversationEngine) -> None:
        """Make an engine the root, register the tools, capture the loop."""
        self._loop = asyncio.get_running_loop()
        self._condition = asyncio.Condition()
        self._agents[ROOT_AGENT] = AgentRecord(
            name=ROOT_AGENT, parent=None, depth=0, engine=engine,
            status=RUNNING)
        engine.collab = self
        for tool in self._collab_tools():
            self._registry.register(tool, replace=True, source='collab')

    async def shutdown(self) -> None:
        self._shutdown = True
        for record in list(self._agents.values()):
            record.engine.interrupt()
            if record.task is not None:
                try:
                    await asyncio.wait_for(record.task, timeout=5)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    record.task.cancel()
            if record.status in ACTIVE_STATES:
                record.status = SHUTDOWN    # finished agents keep their outcome

    # ── engine-facing protocol ──────────────────────────────
    def consume_mailbox(self, engine: ConversationEngine) -> list[str]:
        record = self._record_for(engine)
        if record is None:
            return []
        messages = list(record.inbox)
        record.inbox.clear()
        return messages

    def requeue_mailbox(self, engine: ConversationEngine,
                        messages: list[str]) -> None:
        record = self._record_for(engine)
        if record is None:
            return
        for message in reversed(messages):
            record.inbox.appendleft(message)

    def agents_snapshot(self) -> list[dict[str, Any]]:
        return [{'name': record.name, 'status': record.status,
                 'live': _tail_text(record.engine) if record.engine.busy() else ''}
                for record in self._agents.values()]

    def drain_events(self, limit: int = 1_000) -> list[tuple[str, dict]]:
        out: list[tuple[str, dict]] = []
        while len(out) < limit and self._events:
            out.append(self._events.popleft())
        return out

    # ── spawning ────────────────────────────────────────────
    async def spawn(self, name: str, message: str, *,
                    fork_turns: str | int = 'all',
                    system: str = '') -> AgentRecord:
        if not _TASK_NAME_RE.match(str(name)):
            raise ValueError('task_name must match ^[a-z0-9_]+$')
        name = _sanitize(name)
        parent = self._current_name()
        parent_record = self._agents.get(parent)
        depth = (parent_record.depth + 1) if parent_record else 0
        if not _TASK_NAME_RE.match(name):
            raise ValueError('task_name must match ^[a-z0-9_]+$')
        if not message.strip():
            raise ValueError('message must not be empty')
        if depth > self.config.max_depth:
            raise ValueError(f'max depth {self.config.max_depth} exceeded')
        if name in self._agents and self._agents[name].status in ACTIVE_STATES:
            raise ValueError(f'agent {name} is already active')
        active = [r for r in self._agents.values() if r.status in ACTIVE_STATES]
        if len(active) >= max(1, self.config.max_concurrent):
            raise ValueError('too many concurrent agents')

        child = ConversationEngine(
            client=self._client, registry=self._registry,
            store=self._store, cwd=self._cwd, model=self._model,
            config=EngineConfig(agents=self.config),
            system_provider=lambda: self._child_system(parent_record, system),
            agent_name=name)
        child.sink = _forwarding_sink(child, self)
        if fork_turns == 'none':
            history = []
        elif fork_turns == 'all':
            history = (_safe_history(parent_record.engine.request_messages())
                       if parent_record else [])
        else:
            try:
                keep = int(fork_turns)
            except (TypeError, ValueError):
                raise ValueError('fork_turns must be none, all or an integer')
            history = (_safe_history(parent_record.engine.request_messages())
                       if parent_record else [])
            starts = [i for i, m in enumerate(history) if m.get('role') == 'user']
            if 0 < keep < len(starts):
                history = history[starts[-keep]:]
        child.conversation.committed.extend(history)
        record = AgentRecord(name=name, parent=parent, depth=depth, engine=child)
        self._agents[name] = record
        self._touch(record)
        record.task = self._loop.create_task(self._run_child(record, message))
        return record

    async def _run_child(self, record: AgentRecord, message: str) -> None:
        record.status = RUNNING
        self._touch(record)
        engine = record.engine
        try:
            engine.start()
            engine.submit(message)
            while engine.busy() or not engine._work.empty():
                await asyncio.sleep(0.02)
            record.status = (INTERRUPTED if engine._interrupt.is_set()
                             else COMPLETED)
            record.final_message = _tail_text(engine, limit=4_000) or '(no response)'
        except Exception as error:    # noqa: BLE001 - a child failing is a report
            record.status = ERRORED
            record.error = str(error)
            record.final_message = f'(error) {error}'
        finally:
            self._touch(record)
            self._deliver_to_parent(record)

    def _deliver_to_parent(self, record: AgentRecord) -> None:
        parent = self._agents.get(record.parent) if record.parent else None
        if parent is None:
            return
        body = record.error or record.final_message
        parent.inbox.append(
            f'<subagent_update agent="{record.name}" '
            f'status="{record.status}">\n{body}\n</subagent_update>')
        self._events.append(('agent_event', {
            'agent': record.name, 'status': record.status, 'content': body}))
        self._events.append(('agents_refresh', {}))
        self._touch(record)

    def _touch(self, record: AgentRecord | None = None) -> None:
        if record is not None:
            record.updated_at = time.monotonic()
        self._activity_version += 1
        if self._loop is not None and not self._loop.is_closed():
            try:
                self._loop.create_task(self._wake_waiters())
            except RuntimeError:
                pass

    async def _wake_waiters(self) -> None:
        if self._condition is not None:
            async with self._condition:
                self._condition.notify_all()

    # ── collaboration tools ─────────────────────────────────
    def _collab_tools(self) -> list[AnnotatedTool]:
        manager = self

        def spawn_agent(task_name, message, fork_turns='all'):
            return manager._bridge(manager.spawn, name=task_name,
                                   message=message, fork_turns=fork_turns)

        def send_message(target, message, trigger=False):
            return manager._bridge(manager.send_message, target=target,
                                   message=message, trigger=trigger)

        def wait_agent(timeout_ms=30_000):
            return manager._bridge(manager.wait_for_activity,
                                   timeout_ms=timeout_ms)

        return [
            AnnotatedTool(
                name='spawn_agent',
                description=('Delegate a task to a fresh sub-agent with its own '
                             'context. fork_turns: none, all or an integer (last N '
                             'user turns).'),
                parameters={'type': 'object', 'properties': {
                    'task_name': {'type': 'string',
                                  'description': 'lowercase identifier for the agent'},
                    'message': {'type': 'string', 'description': 'The task'},
                    'fork_turns': {'type': 'string',
                                   'description': 'none | all | <integer>'},
                }, 'required': ['task_name', 'message']},
                handler=spawn_agent,
            ),
            AnnotatedTool(
                name='send_message',
                description='Deliver a message to another agent mailbox.',
                parameters={'type': 'object', 'properties': {
                    'target': {'type': 'string'},
                    'message': {'type': 'string'},
                    'trigger': {'type': 'boolean',
                                'description': 'also start a new turn'},
                }, 'required': ['target', 'message']},
                handler=send_message,
            ),
            AnnotatedTool(
                name='followup_task',
                description=('Deliver a message and trigger a new turn on the '
                             'target agent.'),
                parameters={'type': 'object', 'properties': {
                    'target': {'type': 'string'},
                    'message': {'type': 'string'},
                }, 'required': ['target', 'message']},
                handler=lambda target, message: send_message(
                    target=target, message=message, trigger=True),
            ),
            AnnotatedTool(
                name='list_agents', read_only=True,
                description='List agents with their status.',
                parameters={'type': 'object', 'properties': {
                    'path_prefix': {'type': 'string'}}, 'required': []},
                handler=lambda path_prefix=None: manager.list_agents(path_prefix),
            ),
            AnnotatedTool(
                name='wait_agent',
                description=('Wait until another agent shows activity or the '
                             'timeout passes.'),
                parameters={'type': 'object', 'properties': {
                    'timeout_ms': {'type': 'integer'}}, 'required': []},
                handler=wait_agent,
            ),
            AnnotatedTool(
                name='interrupt_agent',
                description='Interrupt a running sub-agent.',
                parameters={'type': 'object', 'properties': {
                    'target': {'type': 'string'}}, 'required': ['target']},
                handler=lambda target: manager.interrupt_agent(target),
            ),
        ]

    # ── tool backends (run on the manager's loop) ───────────
    def send_message(self, target: str, message: str,
                     trigger: bool = False) -> dict[str, Any]:
        record = self._agents.get(_sanitize(target))
        if record is None:
            return {'delivered': False, 'error': f'no such agent: {target}'}
        caller = self._current_name()
        record.inbox.append(f'From {caller}: {message}')
        self._touch(record)
        if trigger:
            record.engine.submit(message)
        return {'delivered': True, 'turn_triggered': bool(trigger)}

    def list_agents(self, path_prefix: str | None = None) -> list[dict[str, Any]]:
        rows = []
        for name, record in list(self._agents.items()):
            if path_prefix and not name.startswith(path_prefix):
                continue
            row: dict[str, Any] = {'name': record.name, 'parent': record.parent,
                                   'status': record.status}
            if record.status == COMPLETED:
                row['completed'] = record.final_message or None
            elif record.status == ERRORED:
                row['errored'] = record.error
            rows.append(row)
        return rows

    async def wait_for_activity(self, timeout_ms: int = 30_000) -> dict[str, Any]:
        timeout = max(0, min(int(timeout_ms), 3_600_000)) / 1000
        seen = self._activity_version

        def changed() -> bool:
            return self._activity_version != seen

        try:
            async with self._condition:
                await asyncio.wait_for(self._condition.wait_for(changed),
                                       timeout=timeout)
        except (asyncio.TimeoutError, TimeoutError):
            return {'timed_out': True, 'updated_agents': []}
        recent = [r.name for r in list(self._agents.values())
                  if time.monotonic() - r.updated_at < 5]
        return {'timed_out': False, 'updated_agents': recent}

    def interrupt_agent(self, target: str) -> dict[str, Any]:
        record = self._agents.get(_sanitize(target))
        if record is None:
            return {'error': f'no such agent: {target}'}
        previous = record.status
        record.engine.interrupt()
        return {'previous_status': previous}

    # ── plumbing ────────────────────────────────────────────
    def _bridge(self, coro_factory: Callable, **kwargs: Any) -> Any:
        """Run a manager coroutine from a tool handler (worker thread).

        Tool handlers execute in asyncio.to_thread workers without a loop;
        the call hops onto the manager's loop and blocks this worker until
        the result is ready, which is exactly the sync-tool contract.
        """
        coro = coro_factory(**kwargs)
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=600)
        except asyncio.TimeoutError:
            future.cancel()
            return 'Error: the operation timed out'

    def _record_for(self, engine: ConversationEngine) -> AgentRecord | None:
        for record in self._agents.values():
            if record.engine is engine:
                return record
        return None

    def _current_name(self) -> str:
        from ..tools.context import current_context
        agent = getattr(current_context(), 'agent', ROOT_AGENT)
        return agent if agent in self._agents else ROOT_AGENT

    def _child_system(self, parent_record: AgentRecord | None,
                      extra: str) -> str:
        parts = []
        if parent_record is not None:
            parts.append(parent_record.engine.system_prompt())
        parts.append(SUBAGENT_SYSTEM)
        if extra:
            parts.append(extra)
        return '\n\n'.join(p for p in parts if p)


def _forwarding_sink(engine: ConversationEngine,
                     manager: 'AgentManager') -> Any:
    """A sink for a child engine that mirrors its events into the manager."""
    from .events import EventSink

    def emit(kind: str, payload: dict[str, Any]) -> None:
        manager._events.append((kind, {'agent': engine.agent_name, **payload}))

    return EventSink(emit=emit)
