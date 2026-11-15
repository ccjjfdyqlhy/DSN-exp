# harness/agent/engine.py
# The stateful conversation engine: a work queue, a status machine and
# events, on top of the harness primitives.
#
# AgentLoop (loop.py) is a short-lived "messages in, events out" loop.  An
# interactive session needs more around it: turns queued while one runs,
# side questions that never touch the main history, history compaction,
# checkpoints and resumable sessions, and a transcript a UI can render.
# ConversationEngine owns that state.  It is asyncio-native; a thread-based
# UI drains the EventSink from its own thread.

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass, replace
from typing import Any, Callable, Optional

from infra.models.base import ChatMessage, IChatClient
from infra.orchestrator.base import effort_stream_params, retrying_stream

from .events import EventSink
from .loop import _merge_tool_arguments
from ..conversation import (
    COMPACTION_SYSTEM, ManagedConversation, StablePrefix, canonical_json,
    repair_messages, stream_compact,
)
from ..images import MARKER_RE
from ..tools.context import ToolContext, pop_context, push_context
from ..tools.registry import ManagedToolRegistry
from ..transcript import (
    LAST_SESSION, SessionPayload, SessionStore, TranscriptItem,
)
from ..usage import (
    TokenBudget, TokenBudgetExceeded, effective_reserved, estimate_tokens,
    normalize_tool_result, normalize_usage,
)
from .engine_config import EngineConfig, ModelInfo

logger = logging.getLogger("harness.engine")

ASIDE_SYSTEM = (
    'Answer the user aside briefly and self-contained. It is a side question '
    'about the ongoing session: do not continue the main task, do not call '
    'tools, do not ask follow-up questions.'
)

_CONTINUATION_NOTE = (
    'Continue exactly where it stopped. Do not repeat earlier text; resume '
    'the answer mid-sentence if that is where it stopped.'
)


@dataclass
class EngineSnapshot:
    """What a header/footer needs about the engine, sampled under a lock."""

    status: str = 'idle'
    turn: int = 0
    turn_in: int = 0
    turn_out: int = 0
    total_in: int = 0
    total_out: int = 0
    context_tokens: int = 0
    context_window: int = 0
    model: str = ''
    provider: str = ''
    effort: str = 'medium'
    session_name: str = ''
    session_title: str = ''
    queued: int = 0
    agents: list[dict[str, Any]] | None = None


class ConversationEngine:
    """Owns turns, the transcript, the conversation state and sessions.

    Args:
        client: any IChatClient; the engine never constructs clients.
        registry: a ManagedToolRegistry with the session's tools.
        store: optional SessionStore for persistence (save/load/rewind/fork).
        sink: optional EventSink; one is created when omitted.
        system_provider: returns the current system prompt; re-evaluated every
            round so goals and skill previews stay fresh.
        cwd: the working directory pushed into every turn's ToolContext.
        model: the initial ModelInfo (window / output caps / reasoning knobs).
        config: engine settings; defaults apply when omitted.
    """

    def __init__(self, *, client: IChatClient,
                 registry: ManagedToolRegistry,
                 store: SessionStore | None = None,
                 sink: EventSink | None = None,
                 system_provider: Callable[[], str] | None = None,
                 cwd: str = '',
                 model: ModelInfo | None = None,
                 config: EngineConfig | None = None,
                 allowed_tools: set[str] | None = None,
                 agent_name: str = 'root') -> None:
        self._client = client
        self._registry = registry
        self._store = store or SessionStore()
        self.sink = sink or EventSink()
        self._system_provider = system_provider
        self._cwd = cwd
        self.config = config or EngineConfig()
        self._model = model or ModelInfo()
        # sub-agent tool allowlist: None means every registered tool
        self._allowed_tools = allowed_tools
        self.agent_name = agent_name
        # set by an AgentManager (harness.agent.collab); None = no collaboration
        self.collab: Any | None = None

        # Control-plane methods are loop-affine: call them from the event
        # loop thread (or via loop.call_soon_threadsafe).  A thread+queue
        # bridge for legacy UIs is a thin wrapper added at integration time.
        self._work: 'asyncio.Queue[tuple[str, str] | None]' = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._stop = False
        # one interrupt flag for the engine loop and for tools running in
        # worker threads (the shell polls it)
        self._interrupt = threading.Event()

        self.conversation = ManagedConversation(
            stable_prefix=self._fresh_prefix(), committed=[])
        self.items: list[TranscriptItem] = []
        self.status = 'idle'
        self.turn = 0
        self.turn_in = 0
        self.turn_out = 0
        self.total_in = 0
        self.total_out = 0
        self.session_name = ''
        self.session_title = ''
        self._lock = threading.RLock()
        self._last_checkpoint = time.monotonic()
        self._usage_records: list[dict[str, Any]] = []

    # ── lifecycle ───────────────────────────────────────────
    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._run())

    async def shutdown(self) -> None:
        self._stop = True
        self._interrupt.set()
        await self._work.put(None)
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        while not self._stop:
            try:
                work = await self._work.get()
            except asyncio.CancelledError:
                return
            if work is None:
                return
            mode, text = work
            try:
                if mode == 'aside':
                    await self._run_aside(text)
                elif mode == 'compact':
                    await self._run_compact()
                else:
                    await self._run_chat(text)
            except Exception as error:    # noqa: BLE001 - a turn never kills the engine
                logger.exception('turn failed')
                self._add_item('notice', text=f'Request failed: {error}',
                               level='error')
                self.sink.emit('error', {'text': str(error)})
            finally:
                self._set_status('idle')
                self._interrupt.clear()

    # ── control plane ───────────────────────────────────────
    def busy(self) -> bool:
        return self.status != 'idle'

    def submit(self, text: str, mode: str = 'chat') -> bool:
        if not text.strip():
            return False
        self._work.put_nowait((mode, text))
        self.sink.emit('queued', {'text': text, 'mode': mode,
                                  'position': self._work.qsize()})
        return True

    def interrupt(self) -> None:
        self._interrupt.set()
        self._interrupt.set()

    stop_turn = interrupt

    def request_compact(self) -> None:
        self._work.put_nowait(('compact', ''))

    def add_notice(self, text: str, level: str = 'info') -> None:
        self._add_item('notice', text=text, level=level)
        self.sink.emit('notice', {'text': text, 'level': level})

    def add_diff_item(self, display: str,
                      file_diff: Any | None) -> None:
        if file_diff is None:
            self.add_notice('No working-tree changes.')
            return
        self._add_item('tool', name='diff', display=display,
                       output=getattr(file_diff, 'unified', ''))
        self.sink.emit('diff_added', {})

    def set_client(self, client: IChatClient, model: ModelInfo) -> None:
        self._require_idle('model change')
        self._client = client
        self._model = model
        self._refresh_prefix(force=True)
        self.turn = 0
        self.sink.emit('model_changed', {'provider': model.provider,
                                         'model': model.id})

    def refresh_tools(self) -> None:
        self._require_idle('tool refresh')
        self._refresh_prefix(force=True)
        self.sink.emit('tools_refreshed', {})

    def drain(self, limit: int = 2_000) -> list[tuple[str, dict[str, Any]]]:
        return self.sink.drain(limit)

    def agents_snapshot(self) -> list[dict[str, Any]] | None:
        if self.collab is None:
            return None
        return self.collab.agents_snapshot()

    def snapshot(self) -> EngineSnapshot:
        with self._lock:
            return EngineSnapshot(
                status=self.status, turn=self.turn,
                turn_in=self.turn_in, turn_out=self.turn_out,
                total_in=self.total_in, total_out=self.total_out,
                context_tokens=self.conversation.estimated_tokens(),
                context_window=self._model.context_window,
                model=self._model.id, provider=self._model.provider,
                effort=self.config.reasoning.effort,
                session_name=self.session_name,
                session_title=self.session_title,
                queued=self._work.qsize(),
                agents=self.agents_snapshot(),
            )

    # ── transcript ──────────────────────────────────────────
    def items_snapshot(self) -> list[TranscriptItem]:
        with self._lock:
            return list(self.items)

    def _add_item(self, kind: str, **fields: Any) -> TranscriptItem:
        item = TranscriptItem(kind=kind, turn=self.turn, **fields)
        with self._lock:
            self.items.append(item)
        return item

    # ── sessions ────────────────────────────────────────────
    def payload(self) -> SessionPayload:
        with self._lock:
            return SessionPayload(
                name=self.session_name, title=self.session_title,
                provider=self._model.provider, model=self._model.id,
                turn=self.turn,
                prefix_generation=self.conversation.stable_prefix.generation,
                messages=[*self.conversation.committed, *self.conversation.draft],
                compaction_archive=list(self.conversation.archived),
                items=list(self.items),
            )

    def save_active(self) -> None:
        payload = self.payload()
        if not (payload.messages or payload.items):
            return
        try:
            if not self.session_name:
                self.session_name = self._store.unique_name(_new_session_name())
            self._store.save(payload, as_name=self.session_name)
            self._store.save(payload, as_name=LAST_SESSION)
        except OSError as error:
            logger.warning('session save failed: %s', error)

    def save_as(self, name: str) -> None:
        self._require_idle('session rename')
        if not name.strip():
            raise ValueError('session name must not be empty')
        self.session_name = name
        self.save_active()

    def load_session(self, name: str) -> bool:
        payload = self._store.load(name)
        if payload is None:
            return False
        self.apply_payload(payload)
        return True

    def apply_payload(self, payload: SessionPayload) -> None:
        self._require_idle('session load')
        with self._lock:
            self.session_name = payload.name
            self.session_title = payload.title
            self.turn = payload.turn
            self.items = list(payload.items)
            archived = list(payload.compaction_archive)
            committed, changed = repair_messages(payload.messages)
            if changed:
                self.add_notice(f'repaired {changed} dangling tool call(s).')
        self.conversation = ManagedConversation(
            stable_prefix=StablePrefix.create(
                provider=self._model.provider, endpoint=self._model.endpoint,
                model=self._model.id, system=self._current_system(),
                tools=self._registry.build_schema(vision=self._model.vision),
                generation=max(1, payload.prefix_generation),
                wire=self._model.wire),
            committed=committed)
        self.conversation.restore(archived, max(1, payload.prefix_generation))
        self.sink.emit('session_loaded', {'name': payload.name,
                                          'title': payload.title})

    def clear(self) -> None:
        self._require_idle('session clear')
        with self._lock:
            self.conversation = ManagedConversation(
                stable_prefix=self._fresh_prefix(), committed=[])
            self._context = self.conversation
            self.items = []
            self.turn = 0
            self.turn_in = self.turn_out = 0
            self.total_in = self.total_out = 0
            self._usage_records = []
        self._store.save(SessionPayload(name=LAST_SESSION), as_name=LAST_SESSION)
        self.sink.emit('session_cleared', {})

    def rewind(self, turn: int) -> str:
        self._require_idle('rewind')
        payload = self.payload()
        dropped_text = ''
        starts = self._store.turn_starts(payload.messages)
        if 1 <= turn <= len(starts):
            cut = starts[turn - 1]
            dropped = payload.messages[cut:]
            for message in dropped:
                if message.get('role') == 'user':
                    content = message.get('content') or ''
                    if not str(content).startswith('<'):
                        dropped_text = str(content)
                        break
        else:
            cut = len(payload.messages)
        payload.messages = payload.messages[:cut]
        payload.items = [item for item in payload.items if item.turn < turn]
        payload.turn = max(0, turn - 1)
        self.apply_payload(payload)
        self.sink.emit('session_rewound', {'turn': turn})
        self.save_active()
        return dropped_text

    def fork(self, name: str = '') -> str:
        self._require_idle('fork')
        new_name = name or self._store.unique_name(
            f'{self.session_name or _new_session_name()}_fork')
        payload = self.payload()
        payload.name = new_name
        payload.title = f'Fork of {self.session_title or self.session_name}'.strip()
        self._store.save(payload, as_name=new_name)
        return new_name

    # ── snapshots for the model layer ───────────────────────
    def request_messages(self) -> list[dict[str, Any]]:
        return self.conversation.request_messages()

    # ── turn engine ─────────────────────────────────────────
    def _require_idle(self, action: str) -> None:
        if self.busy():
            raise RuntimeError(f'{action} while a turn is still running')

    def _set_status(self, status: str, **extra: Any) -> None:
        self.status = status
        self.sink.emit('status', {'status': status, **extra})

    def _stage_collab_mailbox(self) -> None:
        """Pump collaboration events and stage this engine's mailbox."""
        if self.collab is None:
            return
        for kind, payload in self.collab.drain_events():
            self.sink.emit(kind, payload)
        updates = self.collab.consume_mailbox(self)
        if updates:
            self.conversation.stage(*_stage_mailbox(updates))
            self.add_notice(f'Received {len(updates)} sub-agent update(s).')

    def _current_system(self) -> str:
        if self._system_provider is None:
            return ''
        return self._system_provider()

    def system_prompt(self) -> str:
        """The current system prompt (what the next request would carry)."""
        return self._current_system()

    def _fresh_prefix(self) -> StablePrefix:
        return StablePrefix.create(
            provider=self._model.provider, endpoint=self._model.endpoint,
            model=self._model.id, system=self._current_system(),
            tools=self._registry.build_schema(names=self._allowed_tools,
                                              vision=self._model.vision),
            wire=self._model.wire)

    def _refresh_prefix(self, force: bool = False) -> None:
        current = self.conversation.stable_prefix
        candidate = self._fresh_prefix()
        if force or candidate.fingerprint != current.fingerprint:
            self.conversation.stable_prefix = replace(
                candidate, generation=current.generation + 1)

    def _budget(self) -> TokenBudget:
        prefix = self.conversation.stable_prefix
        stable = estimate_tokens({'system': prefix.system, 'tools': prefix.tools})
        return TokenBudget(
            context_window=self._model.context_window,
            reserved_output=effective_reserved(
                self._model.context_window, self.config.context.reserved_output,
                self._model.max_output_tokens),
            stable_tokens=stable)

    async def _run_chat(self, text: str) -> None:
        with self._lock:
            self.turn += 1
            if not self.session_name and self._store is not None:
                self.session_name = self._store.unique_name(_new_session_name())
            self.session_title = _title_from(text)
            self.turn_in = self.turn_out = 0
        self._add_item('user', text=text)
        self._set_status('connecting')
        self.sink.emit('turn_start', {'turn': self.turn, 'text': text})
        self.conversation.stage({'role': 'user', 'content': text})
        self._interrupt.clear()

        context = ToolContext(cwd=self._cwd or '.',
                              interrupt=self._interrupt,
                              agent=self.agent_name)
        context_token = push_context(context)
        committed = False
        try:
            continuations = 0
            while True:
                if self._stop or self._interrupt.is_set():
                    break
                self._stage_collab_mailbox()
                self._refresh_prefix()
                budget = self._budget()
                if (self.config.context.auto_compact
                        and self.conversation.needs_compaction(
                            budget, self.config.context.compact_threshold)):
                    await self._compact(budget)
                self.conversation.enforce_budget(
                    budget, self.config.context.keep_recent_turns)
                thinking, full, tool_calls, finish = await self._stream_request(budget)
                if self._interrupt.is_set():
                    break
                if tool_calls:
                    if not await self._execute_tools(full, thinking, tool_calls):
                        break
                    self._maybe_checkpoint()
                    self._set_status('connecting')
                    continue
                if finish == 'length':
                    if continuations >= self.config.max_continuations:
                        self.add_notice('Output token limit reached; '
                                        'continuation stopped.', 'warning')
                        self.conversation.stage(_assistant_message(full, thinking))
                        self.conversation.commit()
                        committed = True
                        break
                    continuations += 1
                    self.conversation.stage(_continuation_prompt(full, thinking))
                    continue
                if finish == 'incomplete':
                    self.add_notice('The response ended without a finish signal.',
                                    'warning')
                self._add_item('assistant', text=full)
                self.conversation.stage(_assistant_message(full, thinking))
                self.conversation.commit()
                committed = True
                break
        except TokenBudgetExceeded as error:
            self.conversation.rollback()
            self.add_notice(str(error), 'error')
            self.sink.emit('error', {'text': str(error)})
        except Exception as error:    # noqa: BLE001 - keep the finished work
            self._add_item('notice', text=f'Request failed: {error}',
                           level='error')
            self.sink.emit('error', {'text': str(error)})
        finally:
            pop_context(context_token)
            if not committed:
                committed = self._commit_partial()
            if not committed:
                self.conversation.rollback()
        if self._interrupt.is_set():
            self._add_item('notice', text='[interrupted]')
            self.sink.emit('interrupted', {})
        self.sink.emit('turn_end', {
            'turn': self.turn, 'status': 'interrupted' if self._interrupt.is_set()
            else 'done',
            'stats': {'input_tokens': self.turn_in,
                      'output_tokens': self.turn_out,
                      'duration': 0.0}})
        self.save_active()

    def _commit_partial(self) -> bool:
        """Commit the longest tool-closed prefix of the draft, if any.

        An interrupted turn keeps the work it already finished: the draft
        prefix that ends on a complete tool result is committed (unanswered
        calls repaired), everything after it is dropped.
        """
        draft = self.conversation.draft
        if not draft:
            return False
        cut = 0
        for index, message in enumerate(draft):
            if message.get('role') == 'tool':
                cut = index + 1
        prefix = draft[:cut]
        if not prefix:
            return False
        repaired, _ = repair_messages(prefix)
        self.conversation.draft.clear()
        self.conversation.stage(*repaired)
        self.conversation.commit()
        return True

    async def _stream_request(self, budget: TokenBudget
                              ) -> tuple[str, str, list[dict[str, Any]], str]:
        """One model round: returns (thinking, text, tool_calls, finish_reason)."""
        prefix = self.conversation.stable_prefix
        max_tokens = max(256, min(self.config.max_output_tokens,
                                  self._model.max_output_tokens,
                                  budget.reserved_output))
        kwargs = effort_stream_params(
            self._model.wire,
            effort=self.config.reasoning.effort,
            reasoning_style=self._model.reasoning_style,
            reasoning_efforts=self._model.reasoning_efforts,
            reasoning=self._model.reasoning,
            force=self.config.reasoning.force,
            prompt_cache_key=prefix.fingerprint)
        kwargs['max_tokens'] = max_tokens
        msgs = [ChatMessage.from_dict(m) if isinstance(m, dict) else m
                for m in self.conversation.request_messages()]
        if prefix.system:
            msgs = [ChatMessage.system(prefix.system), *msgs]

        thinking_parts: list[str] = []
        text_parts: list[str] = []
        tool_acc: dict[int, dict[str, Any]] = {}
        finish = 'incomplete'
        started = time.monotonic()
        first_chunk_seen = False
        async for chunk in retrying_stream(self._client, msgs, prefix.tools,
                                           attempts=3, **kwargs):
            if not first_chunk_seen:
                first_chunk_seen = True
                self._set_status('thinking')
            if isinstance(chunk, str):
                if thinking_parts:
                    self._thinking_done(''.join(thinking_parts), started)
                    thinking_parts = []
                if self.status == 'thinking':
                    self._set_status('answering')
                text_parts.append(chunk)
                self.sink.emit('text_delta', {'text': chunk})
                continue
            if not isinstance(chunk, dict):
                continue
            reasoning = chunk.get('reasoning') or chunk.get('reasoning_content')
            if reasoning:
                thinking_parts.append(reasoning)
                self.sink.emit('thinking_delta', {'text': reasoning})
            for item in chunk.get('tool_calls', []) or []:
                index = item.get('index', 0)
                acc = tool_acc.setdefault(index, {'id': '', 'name': '', 'arguments': ''})
                acc['id'] = item.get('id') or acc.get('id', '')
                acc['name'] = item.get('name') or acc.get('name', '')
                prev = acc.get('arguments', '') or ''
                acc['arguments'] = _merge_tool_arguments(
                    prev, item.get('arguments') or '')
            if chunk.get('usage'):
                self._record_usage(chunk['usage'])
            if chunk.get('retry'):
                retry = chunk['retry']
                self._set_status('connecting', retrying=True)
                self.add_notice(f"Reconnecting ({retry.get('attempt')}): "
                                f"{retry.get('error')}")
            if chunk.get('finish'):
                finish = str(chunk['finish'])

        thinking = ''.join(thinking_parts)
        if thinking:
            self._thinking_done(thinking, started)
        full = ''.join(text_parts)
        self.sink.emit('text_end', {'text': full,
                                    'duration': time.monotonic() - started})

        tool_calls: list[dict[str, Any]] = []
        for index in sorted(tool_acc):
            call = tool_acc[index]
            if call['name']:
                try:
                    args = json.loads(call['arguments'] or '{}')
                except ValueError:
                    args = {}
                if not isinstance(args, dict):
                    args = {'value': args}
                tool_calls.append({'id': call['id'] or f'call_{index}',
                                   'name': call['name'], 'args': args})
        return thinking, full, tool_calls, finish

    def _thinking_done(self, text: str, started: float) -> None:
        if self.config.thinking.show_completed:
            self._add_item('thinking', text=text)
        self.sink.emit('thinking_end', {'text': text,
                                        'duration': time.monotonic() - started})

    def _record_usage(self, raw: Any) -> None:
        usage = normalize_usage(raw)
        record = {**usage, 'provider': self._model.provider,
                  'model': self._model.id,
                  'prefix_generation': self.conversation.stable_prefix.generation,
                  'prefix_hash': self.conversation.stable_prefix.fingerprint}
        self.turn_in += usage.get('input_tokens') or 0
        self.turn_out += usage.get('output_tokens') or 0
        self.total_in += usage.get('input_tokens') or 0
        self.total_out += usage.get('output_tokens') or 0
        self._usage_records.append(record)
        del self._usage_records[:-200]
        self.sink.emit('usage', dict(record))

    async def _execute_tools(self, full: str, thinking: str,
                             tool_calls: list[dict[str, Any]]) -> bool:
        """Run the round's tools; False when the turn was interrupted."""
        self._set_status('tool')
        results: list[dict[str, Any]] = []
        image_markers: list[str] = []
        for call in tool_calls:
            if self._interrupt.is_set():
                break
            call_id = call['id']
            display = call['name']
            self._add_item('tool', call_id=call_id, name=call['name'],
                           display=display, args=dict(call['args']),
                           status='running')
            self.sink.emit('tool_start', {
                'turn': self.turn, 'call_id': call_id, 'name': call['name'],
                'display': display, 'args': dict(call['args'])})
            started = time.monotonic()
            sink_lines: list[str] = []

            def live_sink(line: str, _call_id: str = call_id) -> None:
                sink_lines.append(line)
                self.sink.emit('tool_output', {'call_id': _call_id, 'text': line})

            context = ToolContext(cwd=self._cwd or '.',
                                  interrupt=self._interrupt,
                                  live_sink=live_sink, agent=self.agent_name)
            # asyncio.to_thread copies the current contextvars into the
            # worker thread, so the tool sees the ToolContext pushed here.
            context_token = push_context(context)
            try:
                text, file_diff, error = await asyncio.to_thread(
                    self._registry.execute, call['name'], dict(call['args']))
            finally:
                pop_context(context_token)
            normalized = normalize_tool_result(call['name'], text)['text']
            duration = time.monotonic() - started
            item = self._last_item('tool', call_id)
            diff_dict = _diff_dict(file_diff)
            if item is not None:
                item.status = 'error' if error else 'done'
                item.output = normalized
                item.duration = duration
                item.diff = diff_dict
            self.sink.emit('tool_end', {
                'turn': self.turn, 'call_id': call_id, 'name': call['name'],
                'display': display, 'output': normalized, 'duration': duration,
                'error': error, 'diff': diff_dict})
            results.append({'tool_call_id': call_id,
                            'role': 'tool', 'content': normalized})
            for match in MARKER_RE.findall(normalized):
                if match not in image_markers:
                    image_markers.append(match)

        # stage the assistant tool_calls + one tool message per result, exactly
        # the shapes every wire adapter understands
        calls_wire = [{'id': call['id'], 'type': 'function',
                       'function': {'name': call['name'],
                                    'arguments': canonical_json(call['args'])}}
                      for call in tool_calls]
        self.conversation.stage(_assistant_message(full, thinking, calls_wire))
        self.conversation.stage(*results)
        if image_markers:
            self.conversation.stage({
                'role': 'user',
                'content': '<tool_images>\n' + '\n'.join(image_markers)
                           + '\n</tool_images>'})
        return not self._interrupt.is_set()

    def _last_item(self, kind: str, call_id: str) -> TranscriptItem | None:
        with self._lock:
            for item in reversed(self.items):
                if item.kind == kind and item.call_id == call_id:
                    return item
        return None

    def _maybe_checkpoint(self) -> None:
        if time.monotonic() - self._last_checkpoint >= self.config.checkpoint_interval:
            self._last_checkpoint = time.monotonic()
            self.save_active()

    # ── aside ───────────────────────────────────────────────
    async def _run_aside(self, question: str) -> None:
        if self._interrupt.is_set():
            return
        self._set_status('aside')
        self.sink.emit('aside_start', {'question': question})
        messages = [*self.conversation.committed,
                    {'role': 'user', 'content': question}]
        msgs = [ChatMessage.from_dict(m) if isinstance(m, dict) else m
                for m in messages]
        kwargs = effort_stream_params(self._model.wire, effort='low',
                                      reasoning_style=self._model.reasoning_style,
                                      reasoning_efforts=self._model.reasoning_efforts,
                                      reasoning=self._model.reasoning)
        kwargs['max_tokens'] = max(256, min(4_096, self.config.max_output_tokens,
                                            self._model.max_output_tokens))
        parts: list[str] = []
        async for chunk in retrying_stream(self._client, msgs, None, attempts=3,
                                           **kwargs):
            if isinstance(chunk, str):
                parts.append(chunk)
                self.sink.emit('aside_delta', {'text': chunk})
            elif isinstance(chunk, dict) and chunk.get('usage'):
                self._record_usage(chunk['usage'])
        answer = ''.join(parts)
        self._add_item('aside', display=question, text=answer)
        self.sink.emit('aside_end', {'question': question, 'answer': answer})
        self.save_active()

    # ── compaction ──────────────────────────────────────────
    async def _compact(self, budget: TokenBudget | None = None) -> int:
        budget = budget or self._budget()
        self._set_status('compacting')
        self.sink.emit('compaction_start', {})
        target = max(1_024, budget.usable() - estimate_tokens(self.conversation.draft))

        def factory(messages, *, system='', max_tokens=0, tools=None):
            kwargs = effort_stream_params(
                self._model.wire,
                effort=self.config.context.compaction_reasoning_effort,
                reasoning_style=self._model.reasoning_style,
                reasoning_efforts=self._model.reasoning_efforts,
                reasoning=self._model.reasoning)
            kwargs['max_tokens'] = max_tokens or 2_048
            msgs = [ChatMessage.from_dict(m) if isinstance(m, dict) else m
                    for m in messages]
            if system:
                msgs = [ChatMessage.system(system), *msgs]
            return retrying_stream(self._client, msgs, None, attempts=1, **kwargs)

        def emit_delta(text: str) -> None:
            self.sink.emit('compaction_delta', {'text': text})

        removed = await stream_compact(
            self.conversation, target, factory, emit=emit_delta,
            keep_recent_turns=self.config.context.keep_recent_turns)
        self.sink.emit('compaction_end', {'text': '', 'removed': removed})
        self._refresh_prefix(force=True)
        self._set_status('connecting')
        return removed


def _assistant_message(content: str, reasoning: str,
                       tool_calls: list[dict] | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {'role': 'assistant', 'content': content or None}
    if reasoning:
        message['reasoning_content'] = reasoning
    if tool_calls:
        message['tool_calls'] = tool_calls
    return message


def _continuation_prompt(full: str, thinking: str) -> dict[str, Any]:
    parts = ['<continuation_request>']
    if thinking:
        parts.append(f'<reasoning>\n{thinking}\n</reasoning>')
    parts.append(f'<output>\n{full}\n</output>')
    parts.append(_CONTINUATION_NOTE + '</continuation_request>')
    return {'role': 'user', 'content': '\n'.join(parts)}


def _stage_mailbox(messages: list[str]) -> list[dict[str, Any]]:
    """Wrap consumed sub-agent updates as one injected user message."""
    if not messages:
        return []
    return [{'role': 'user',
             'content': '<subagent_updates>\n' + '\n'.join(messages)
                        + '\n</subagent_updates>'}]


def _title_from(text: str) -> str:
    first_line = text.strip().splitlines()[0] if text.strip() else ''
    return first_line[:60]


def _new_session_name() -> str:
    return time.strftime('%Y%m%d_%H%M%S')


def _diff_dict(file_diff: Any | None) -> dict[str, Any] | None:
    if file_diff is None:
        return None
    return {'path': getattr(file_diff, 'path', ''),
            'unified': getattr(file_diff, 'unified', ''),
            'additions': getattr(file_diff, 'additions', 0),
            'deletions': getattr(file_diff, 'deletions', 0),
            'omitted': getattr(file_diff, 'omitted', False)}
