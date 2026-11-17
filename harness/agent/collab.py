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
import inspect
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


@dataclass
class AgentTypeSpec:
    """A named child profile: system text, model and tool allowlist.

    ``model`` is an opaque identifier the manager's ``model_resolver``
    understands (an application typically owns provider routing); '' keeps
    the parent's model.  An empty ``tools`` list inherits every registered
    tool; a non-empty one restricts the child to those names.
    """

    name: str
    system: str = ''
    model: str = ''
    tools: list[str] = field(default_factory=list)


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


def _last_assistant_text(engine: ConversationEngine) -> str:
    for item in reversed(engine.items_snapshot()):
        if item.kind == 'assistant' and item.text:
            return item.text
    return ''


def _tail_text(engine: ConversationEngine, limit: int = 400) -> str:
    """The end of the last assistant message: the live view wants the tail."""
    return _last_assistant_text(engine)[-limit:]


def _report_text(engine: ConversationEngine, limit: int = 4_000) -> str:
    """The child's final report, trimmed at both ends when it is too long.

    A report is read from the top: cutting the head (a plain tail slice)
    keeps the epilogue and drops the summary, and the parent then cannot
    tell what the child actually concluded.  Long reports keep both ends
    and say how much was elided.
    """
    text = _last_assistant_text(engine)
    if len(text) <= limit:
        return text
    head = limit * 3 // 5
    tail = limit - head
    elided = len(text) - limit
    return (f'{text[:head]}\n\n... <report truncated: {elided} characters '
            f'elided from the middle> ...\n\n{text[-tail:]}')


class _ChildMailbox:
    """What a child engine sees as ``engine.collab``.

    A child must consume its own mailbox -- that is how ``send_message`` and
    its parent's answers reach its context -- but it must not drain the
    manager's announcement queue.  That queue belongs to the root engine's
    transcript pump, and a child's sink feeds announcements back into it, so
    a child draining it would push the same events round forever.  Hence a
    proxy: mailboxes yes, announcements no.
    """

    def __init__(self, manager: 'AgentManager') -> None:
        self._manager = manager

    def drain_events(self, limit: int = 1_000) -> list[tuple[str, dict]]:
        return []

    def consume_mailbox(self, engine: ConversationEngine) -> list[str]:
        return self._manager.consume_mailbox(engine)

    def settle_mailbox(self, engine: ConversationEngine) -> int:
        return self._manager.settle_mailbox(engine)

    def agents_snapshot(self) -> list[dict[str, Any]]:
        return self._manager.agents_snapshot()


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
                 store=None,
                 model_resolver: Optional[Callable[
                     [str], tuple[IChatClient, ModelInfo] | None]] = None
                 ) -> None:
        self._client = client
        self._registry = registry
        self._model = model or ModelInfo()
        self.config = config or AgentSettings()
        self._cwd = cwd
        self._store = store
        # resolves an AgentTypeSpec's model identifier to (client, ModelInfo)
        self._model_resolver = model_resolver
        self._agent_types: dict[str, AgentTypeSpec] = {}
        self._agents: dict[str, AgentRecord] = {}
        # set by ``_touch`` (from any thread) to release wait_for_activity
        self._wake = asyncio.Event()
        self._activity_version = 0
        self._events: deque[tuple[str, dict]] = deque(maxlen=2_000)
        # the full child stream (deltas, tool output, usage); the engine's
        # pump never consumes it, a UI drains it itself
        self._activity: deque[tuple[str, dict]] = deque(maxlen=2_000)
        # mailbox updates handed to a turn, kept until that turn commits
        self._pending_mailbox: dict[int, list[str]] = {}
        # False silences the transcript forwarding for a UI that consumes
        # the activity stream itself
        self.forward_events = True
        self._loop: asyncio.AbstractEventLoop | None = None
        self._shutdown = False

    # ── wiring ──────────────────────────────────────────────
    def attach(self, engine: ConversationEngine,
               loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Make an engine the root, register the tools, capture the loop.

        ``loop`` is the loop the manager lives on; it defaults to the
        running one, which only exists when attach is called from inside it.
        """
        self._loop = loop or asyncio.get_running_loop()
        self._wake = asyncio.Event()
        self._agents[ROOT_AGENT] = AgentRecord(
            name=ROOT_AGENT, parent=None, depth=0, engine=engine,
            status=RUNNING)
        engine.collab = self
        self.reinstall_tools()

    def extra_tools(self) -> list[AnnotatedTool]:
        """Additional tools registered with the collaboration suite."""
        return []

    def reinstall_tools(self) -> None:
        """Re-register the collaboration tools after a registry refresh."""
        for tool in self._collab_tools() + self.extra_tools():
            self._registry.register(tool, replace=True, source='collab')

    def set_model(self, model: ModelInfo, client: IChatClient | None = None
                  ) -> None:
        """Future children spawn with this model; the client is optional."""
        self._model = model
        if client is not None:
            self._client = client

    # ── agent types ─────────────────────────────────────────
    def register_agent_type(self, spec: AgentTypeSpec) -> None:
        self._agent_types[spec.name] = spec

    def agent_type(self, name: str) -> AgentTypeSpec | None:
        return self._agent_types.get(name)

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
        """Take the inbox, but remember it until the turn that used it commits.

        A turn that fails or is interrupted after the updates were staged
        would drop them for good -- the parent never learns what its
        sub-agents found.  The copy kept here lets :meth:`settle_mailbox`
        return the undelivered updates when the turn ends.
        """
        record = self._record_for(engine)
        if record is None:
            return []
        messages = list(record.inbox)
        record.inbox.clear()
        if messages:
            self._pending_mailbox.setdefault(id(engine), []).extend(messages)
        return messages

    def requeue_mailbox(self, engine: ConversationEngine,
                        messages: list[str]) -> None:
        record = self._record_for(engine)
        if record is None:
            return
        for message in reversed(messages):
            record.inbox.appendleft(message)

    def settle_mailbox(self, engine: ConversationEngine) -> int:
        """Requeue the sub-agent updates a turn never put into the history.

        Called when the turn ends: the engine has committed or rolled back
        by then, so the history says which updates made it through.  Returns
        how many updates were put back.
        """
        pending = self._pending_mailbox.pop(id(engine), [])
        if not pending:
            return 0
        history = ''
        for message in engine.conversation.committed:
            content = message.get('content')
            if isinstance(content, str):
                history += content
        lost = [text for text in pending if text not in history]
        if lost:
            self.requeue_mailbox(engine, lost)
        return len(lost)

    def agents_snapshot(self) -> list[dict[str, Any]]:
        return [{'name': record.name, 'status': record.status,
                 'live': _tail_text(record.engine) if record.engine.busy() else ''}
                for record in self._agents.values()]

    def drain_events(self, limit: int = 1_000) -> list[tuple[str, dict]]:
        out: list[tuple[str, dict]] = []
        while len(out) < limit and self._events:
            out.append(self._events.popleft())
        return out

    def drain_activity(self, limit: int = 1_000) -> list[tuple[str, dict]]:
        """Drain the full child stream (deltas, tool output, usage).

        The engine's round pump consumes only :meth:`drain_events`; this
        stream belongs to the application, which can read it per frame
        without starving the transcript.
        """
        out: list[tuple[str, dict]] = []
        while len(out) < limit and self._activity:
            out.append(self._activity.popleft())
        return out

    # ── spawning ────────────────────────────────────────────
    async def spawn(self, name: str, message: str, *,
                    agent_type: str = '',
                    fork_turns: str | int | None = None,
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

        spec = self._agent_types.get(agent_type or self.config.default_type)
        extra = system or (spec.system if spec is not None else '')
        model_info = self._model
        client = self._client
        if spec is not None and spec.model:
            resolved = (self._model_resolver(spec.model)
                        if self._model_resolver else None)
            if resolved is not None:
                client, model_info = resolved
            else:
                logger.warning('no client resolved for agent type model %s; '
                               'the child inherits the parent model',
                               spec.model)
        allowed_tools = set(spec.tools) if spec is not None and spec.tools \
            else None

        child = ConversationEngine(
            client=client, registry=self._registry,
            store=self._store, cwd=self._cwd, model=model_info,
            config=EngineConfig(agents=self.config),
            system_provider=lambda: self._child_system(
                parent_record, extra, model_info),
            allowed_tools=allowed_tools, agent_name=name)
        child.sink = _forwarding_sink(child, self)
        # without this a child never stages the messages sent to it:
        # ``send_message`` would fill an inbox nothing ever reads
        child.collab = _ChildMailbox(self)
        if fork_turns is None:
            fork_turns = self.config.default_fork_turns
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
            late = await self._settle_descendants(record)
            record.status = (INTERRUPTED if engine.last_turn_interrupted
                             else COMPLETED)
            record.final_message = _report_text(engine) or '(no response)'
            if late:
                # Its own turn ended before these arrived; ride them along so
                # the report the parent receives is not missing the work this
                # agent started.
                record.final_message += (
                    '\n\n<reports received after this agent finished>\n'
                    + '\n'.join(late))
        except Exception as error:    # noqa: BLE001 - a child failing is a report
            record.status = ERRORED
            record.error = str(error)
            record.final_message = f'(error) {error}'
        finally:
            self._touch(record)
            self._deliver_to_parent(record)

    async def _settle_descendants(self, record: AgentRecord) -> list[str]:
        """Wait for this agent's own descendants, then take what they sent.

        A child that delegates and finishes before its children report used to
        lose those reports for good: the updates landed in an inbox that no
        later turn would ever read, because nothing drives another turn on a
        finished agent.  Waiting here makes "completed" mean *this agent and
        everything it started are done*, and the late reports travel inside
        this agent's own report so its parent still sees them.
        """
        late: list[str] = []
        while True:
            while self._has_active_descendant(record.name):
                await asyncio.sleep(0.02)
            new = list(record.inbox)
            record.inbox.clear()
            late.extend(new)
            if not new and not self._has_active_descendant(record.name):
                return late

    def _has_active_descendant(self, name: str) -> bool:
        """True while any agent below ``name`` in the tree is still running."""
        children: dict[str, list[AgentRecord]] = {}
        for record in self._agents.values():
            children.setdefault(record.parent or '', []).append(record)
        stack = list(children.get(name, []))
        while stack:
            record = stack.pop()
            if record.status in ACTIVE_STATES:
                return True
            stack.extend(children.get(record.name, []))
        return False

    def _deliver_to_parent(self, record: AgentRecord) -> None:
        parent = self._agents.get(record.parent) if record.parent else None
        if parent is None:
            return
        body = record.error or record.final_message
        parent.inbox.append(
            f'<subagent_update agent="{record.name}" '
            f'status="{record.status}">\n{body}\n</subagent_update>')
        self._publish('agent_event', {
            'agent': record.name, 'status': record.status, 'content': body})
        self._publish('agents_refresh', {})
        self._touch(record)

    def _publish(self, kind: str, payload: dict[str, Any]) -> None:
        """Lifecycle announcements: the transcript stream and the UI stream."""
        self._activity.append((kind, payload))
        if self.forward_events:
            self._events.append((kind, payload))

    def _touch(self, record: AgentRecord | None = None) -> None:
        if record is not None:
            record.updated_at = time.monotonic()
        self._activity_version += 1
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        # ``_touch`` runs from worker threads too (the tool backends), and a
        # bare ``create_task`` there is not safe and left "coroutine was never
        # awaited" warnings behind when the loop stopped first.  Handing the
        # wake to the loop itself has neither problem.
        try:
            loop.call_soon_threadsafe(self._wake_waiters)
        except RuntimeError:      # the loop closed between the check and here
            pass

    def _wake_waiters(self) -> None:
        """Release ``wait_for_activity`` waiters; always runs on the loop."""
        self._wake.set()

    # ── collaboration tools ─────────────────────────────────
    def _collab_tools(self) -> list[AnnotatedTool]:
        manager = self

        def spawn_agent(task_name, message, fork_turns=None, agent_type=''):
            spawned = manager._bridge(manager.spawn, name=task_name,
                                      message=message, fork_turns=fork_turns,
                                      agent_type=agent_type)
            # The model gets a compact receipt, not the live record (whose
            # engine field would leak an object repr into the transcript).
            if isinstance(spawned, AgentRecord):
                return {'agent': spawned.name, 'status': spawned.status,
                        'parent': spawned.parent, 'depth': spawned.depth}
            return spawned     # the bridge's 'Error: ...' text

        def send_message(target, message, trigger=False):
            return manager._bridge(manager.send_message, target=target,
                                   message=message, trigger=trigger)

        def wait_agent(timeout_ms=None):
            return manager._bridge(manager.wait_for_activity,
                                   timeout_ms=timeout_ms
                                   if timeout_ms is not None
                                   else manager.config.wait_timeout_ms)

        return [
            AnnotatedTool(
                name='spawn_agent',
                description=('Delegate a task to a fresh sub-agent with its own '
                             'context. fork_turns: none, all or an integer (last N '
                             'user turns). agent_type: a registered agent profile '
                             '(its system, model and tool allowlist), or empty '
                             'for the default type.'),
                parameters={'type': 'object', 'properties': {
                    'task_name': {'type': 'string',
                                  'description': 'lowercase identifier for the agent'},
                    'message': {'type': 'string', 'description': 'The task'},
                    'fork_turns': {'type': 'string',
                                   'description': 'none | all | <integer>'},
                    'agent_type': {'type': 'string',
                                   'description': 'a registered agent type name'},
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

    async def wait_for_activity(self, timeout_ms: int | None = None
                                ) -> dict[str, Any]:
        timeout_ms = (self.config.wait_timeout_ms
                      if timeout_ms is None else timeout_ms)
        timeout = max(0, min(int(timeout_ms), 3_600_000)) / 1000
        seen = self._activity_version

        def recent() -> list[str]:
            return [r.name for r in list(self._agents.values())
                    if time.monotonic() - r.updated_at < 5]

        deadline = time.monotonic() + timeout
        # Loop, not a single wait: a set left behind by an earlier touch would
        # otherwise return "activity" without any version change, and the
        # caller acts on that answer.
        while self._activity_version == seen:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {'timed_out': True, 'updated_agents': []}
            event = self._wake
            try:
                await asyncio.wait_for(event.wait(), timeout=remaining)
            except (asyncio.TimeoutError, TimeoutError):
                return {'timed_out': True, 'updated_agents': []}
            finally:
                # re-arm: the next activity has to wake the next wait.  A
                # waiter that grabbed the old object is already awake.
                if self._wake is event:
                    self._wake = asyncio.Event()
        return {'timed_out': False, 'updated_agents': recent()}

    def interrupt_agent(self, target: str) -> dict[str, Any]:
        record = self._agents.get(_sanitize(target))
        if record is None:
            return {'error': f'no such agent: {target}'}
        previous = record.status
        record.engine.interrupt()
        return {'previous_status': previous}

    # ── plumbing ────────────────────────────────────────────
    def _bridge(self, factory: Callable, **kwargs: Any) -> Any:
        """Run a manager method from a tool handler (worker thread).

        Tool handlers execute in asyncio.to_thread workers without a loop;
        the call hops onto the manager's loop and blocks this worker until
        the result is ready, which is exactly the sync-tool contract.

        ``factory`` may be a coroutine function or a plain sync method: both
        run on the manager's loop, because the backends touch asyncio state
        (``Queue.put_nowait`` in ``submit``, ``loop.create_task`` in
        ``_touch``) that is only safe on the owning loop.  Passing a sync
        method straight to ``run_coroutine_threadsafe`` used to raise
        "A coroutine object is required", which is how `send_message` and
        `followup_task` failed for every model call.
        """
        if self._loop is None or self._loop.is_closed():
            return 'Error: the collaboration manager is not attached to a loop'

        async def call() -> Any:
            result = factory(**kwargs)
            if inspect.isawaitable(result):
                result = await result
            return result

        future = asyncio.run_coroutine_threadsafe(call(), self._loop)
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
                      extra: str, model: ModelInfo | None = None) -> str:
        parts = []
        if parent_record is not None:
            parts.append(self._parent_system(parent_record, model))
        parts.append(SUBAGENT_SYSTEM)
        if extra:
            parts.append(extra)
        suffix = self.config.system_suffix
        if suffix:
            parts.append(suffix)
        return '\n\n'.join(p for p in parts if p)

    def _parent_system(self, parent_record: AgentRecord,
                       model: ModelInfo | None = None) -> str:
        """The parent prompt a child starts from; ``model`` is the child's."""
        return parent_record.engine.system_prompt()


def _forwarding_sink(engine: ConversationEngine,
                     manager: 'AgentManager') -> Any:
    """A sink for a child engine that mirrors its events into the manager.

    Lifecycle announcements reach the transcript stream (the engine's round
    pump forwards them); the full stream -- deltas, tool output, usage --
    lands in the activity deque a UI drains itself, so a slow transcript
    pump never eats it.
    """
    from .events import EventSink

    def emit(kind: str, payload: dict[str, Any]) -> None:
        event = {'agent': engine.agent_name, **payload}
        manager._activity.append((kind, event))
        if manager.forward_events and kind in ('agent_event', 'agents_refresh'):
            manager._events.append((kind, event))

    return EventSink(emit=emit)
