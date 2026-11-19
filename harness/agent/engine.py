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
import os
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
from ..images import MARKER_RE, image_marker
from ..tools.context import ToolContext, pop_context, push_context
from ..tools.registry import ManagedToolRegistry
from ..paths import state_file
from ..transcript import (
    DbSessionStore, LAST_SESSION, SessionPayload, SessionStore, TranscriptItem,
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

#: What the model sees in front of the reasoning of a round that never
#: finished.  It has to be in the history, not only in the transcript: the
#: model has to know that it was cut off and what it had worked out.
UNFINISHED_NOTE = ('[this turn did not finish - it was interrupted or the '
                   'response was cut off. Continue from here instead of '
                   'starting over.]')


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
                 store: Any = None,
                 sink: EventSink | None = None,
                 system_provider: Callable[[], str] | None = None,
                 cwd: str = '',
                 model: ModelInfo | None = None,
                 config: EngineConfig | None = None,
                 allowed_tools: set[str] | None = None,
                 agent_name: str = 'root') -> None:
        self._client = client
        self._registry = registry
        self.sink = sink or EventSink()
        self._system_provider = system_provider
        self._cwd = cwd
        # persistence defaults to the sqlite route (infra.store under the
        # hood); the json store stays available and duck-types the same
        # 默认落点**不在工作目录里**：引擎的运行时状态不该在
        # 「agent 正在改的那个项目」里留下文件。
        self._store = store or DbSessionStore(
            db_path=str(state_file('sessions', 'agent.db')))
        self.config = config or EngineConfig()
        self._model = model or ModelInfo()
        # sub-agent tool allowlist: None means every registered tool
        self._allowed_tools = allowed_tools
        self.agent_name = agent_name
        # set at the end of every turn, before the interrupt flag is cleared
        self.last_turn_interrupted = False
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
        # The reasoning flushed so far in the round in flight.  The flush
        # empties the stream buffer as soon as the answer text starts, so
        # the reasoning that came first would otherwise be gone from the
        # request the round returns -- and with it from the history.
        self._round_thinking: list[str] = []
        # The reasoning and text of the round that did not finish, if any.
        self._unfinished_round: tuple[str, str] | None = None

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
                # snapshot before clearing: a manager running the turn reads
                # this afterwards (engine._interrupt is reset for the next one)
                self.last_turn_interrupted = self._interrupt.is_set()
                self._interrupt.clear()

    # ── control plane ───────────────────────────────────────
    def busy(self) -> bool:
        return self.status != 'idle'

    def submit(self, text: str, mode: str = 'chat',
               announce: bool = True) -> bool:
        if not text.strip():
            return False
        self._work.put_nowait((mode, text))
        if announce:
            self.sink.emit('queued', {'text': text, 'mode': mode,
                                      'position': self._work.qsize()})
        return True

    def interrupt(self) -> None:
        self._interrupt.set()
        self._interrupt.set()

    @property
    def interrupt_event(self) -> threading.Event:
        """The interrupt flag; a client watches it to stop its stream."""
        return self._interrupt

    def clear_interrupt(self) -> None:
        self._interrupt.clear()

    def usage_records(self) -> list[dict[str, Any]]:
        """The per-request usage records (most engines keep the last 200)."""
        return list(self._usage_records)

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
        """Drop the given transcript turn and everything after it.

        Transcript turn ids survive compaction, but the retained history
        starts later.  Align the oldest retained user message with the suffix
        of transcript turns instead of assuming ``turn - 1``.  Returns the
        dropped user text (a compaction summary prefix is stripped).
        """
        self._require_idle('rewind')
        with self._lock:
            from ..transcript import SessionStore
            starts = SessionStore.turn_starts(self.conversation.committed)
            turn_ids = sorted({item.turn for item in self.items
                               if item.kind == 'user' and item.turn > 0})
            index = len(starts) - sum(1 for value in turn_ids if value >= turn)
            if index < 0:
                # The requested turn was archived by compaction; roll back to
                # the oldest retained turn instead of wiping the context.
                index = 0
            text = ''
            if 0 <= index < len(starts):
                cut = starts[index]
                message = self.conversation.committed[cut]
                text = str(message.get('content') or '')
                marker = '</conversation_summary>'
                if text.startswith('<conversation_summary>') and marker in text:
                    text = text.split(marker, 1)[1].lstrip('\n')
                del self.conversation.committed[cut:]
            else:
                self.conversation.committed.clear()
            self.conversation.draft.clear()
            self.conversation.invalidate()
            self.items[:] = [item for item in self.items if item.turn < turn]
            self.turn = max(0, turn - 1)
        self.sink.emit('session_rewound', {'turn': turn})
        self.save_active()
        return text

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
        self._unfinished_round = None
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
                message = _assistant_message(full, thinking)
                if finish == 'incomplete' and not full and thinking:
                    # The Responses and the Anthropic wire have no reasoning
                    # field, and a turn that says nothing is a turn the model
                    # cannot continue: the reasoning travels as the text.
                    message['content'] = UNFINISHED_NOTE + '\n' + thinking
                self.conversation.stage(message)
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
        if self.collab is not None:
            self._settle_collab_mailbox()
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
        """Commit the part of a turn that is worth keeping.

        The longest tool-closed prefix of the draft is committed (unanswered
        calls repaired).  The reasoning of the round that never finished is
        kept as its own assistant turn: dropping it makes the next turn
        re-read the same files and re-plan the same work.
        """
        draft = self.conversation.draft
        cut = 0
        for index, message in enumerate(draft):
            if message.get('role') == 'tool':
                cut = index + 1
        prefix = draft[:cut]
        committed = False
        if prefix:
            repaired, _ = repair_messages(prefix)
            self.conversation.draft.clear()
            self.conversation.stage(*repaired)
            self.conversation.commit()
            committed = True
        unfinished = self._unfinished_round
        if unfinished is not None and (unfinished[0] or unfinished[1]):
            self.conversation.stage(self._unfinished_message(*unfinished))
            self.conversation.commit()
            committed = True
        if not committed and self._interrupt.is_set():
            # Nothing was produced, but the request itself is part of the
            # context: the next turn has to answer it.
            draft = self.conversation.draft
            if draft and draft[0].get('role') == 'user':
                self.conversation.commit()
                committed = True
        return committed

    @staticmethod
    def _unfinished_message(thinking: str, full: str) -> dict[str, Any]:
        """The assistant turn that carries an unfinished round's reasoning.

        The reasoning goes into the text as well: the Responses and the
        Anthropic wire have no field for it, and a turn that says nothing is
        a turn the model cannot continue.
        """
        parts = [UNFINISHED_NOTE]
        if full:
            parts.append(full)
        if thinking:
            parts.append(thinking)
        return {'role': 'assistant', 'content': '\n'.join(parts),
                'reasoning_content': thinking}

    def _settle_collab_mailbox(self) -> None:
        """Return sub-agent updates the turn never put into the history."""
        try:
            lost = self.collab.settle_mailbox(self)
        except Exception:    # noqa: BLE001 - settling never kills the turn
            logger.exception('mailbox settlement failed')
            return
        if lost:
            self.add_notice(f'{lost} sub-agent update(s) were kept for the '
                            'next turn.', 'warning')

    async def _stream_request(self, budget: TokenBudget
                              ) -> tuple[str, str, list[dict[str, Any]], str]:
        """One model round, with the hold retry loop around it.

        The retry lives here and not in the client: a round that broke may
        already have streamed text, and only the engine knows which parts
        belong to the failed attempt.
        """
        attempt = 0
        while True:
            self._round_thinking = []
            try:
                result = await self._round_once(budget)
            except asyncio.CancelledError:
                raise
            except Exception as error:    # noqa: BLE001 - the hold retries
                if not self._hold_active() or self._interrupt.is_set():
                    raise
                attempt += 1
                if attempt > self.config.hold.max_retries:
                    raise
                self._retry_notice(attempt, str(error))
                await asyncio.sleep(self._hold_delay(attempt))
                continue
            thinking, full, _tool_calls, finish = result
            if self._interrupt.is_set():
                # The user stopped the turn: remember what this round had
                # produced.  It is the difference between continuing the
                # work and starting it over.
                if thinking or full:
                    self._unfinished_round = (thinking, full)
                return result
            if finish != 'incomplete':
                self._unfinished_round = None
                return result
            if thinking:
                self._unfinished_round = (thinking, full)
            # The provider closed the stream without a finish signal: the
            # answer is truncated, not final.
            if not self._hold_active() or self._interrupt.is_set():
                return result
            attempt += 1
            if attempt > self.config.hold.max_retries:
                retries = self.config.hold.max_retries
                self.add_notice(
                    f'Gave up after {retries} '
                    f'retr{"y" if retries == 1 else "ies"}: '
                    'the response kept ending early.', 'warning')
                return result
            self._retry_notice(attempt, 'the response ended without a finish '
                                        'signal')
            await asyncio.sleep(self._hold_delay(attempt))

    def configure_hold(self, enabled: bool, max_retries: int,
                       delay: float) -> None:
        """Apply the hold settings to the running engine."""
        self.config.hold.enabled = bool(enabled)
        self.config.hold.max_retries = max(0, int(max_retries))
        self.config.hold.delay = max(0.0, float(delay))

    def _hold_active(self) -> bool:
        hold = self.config.hold
        return bool(hold.enabled and hold.max_retries > 0)

    def _hold_delay(self, attempt: int) -> float:
        hold = self.config.hold
        return min(hold.delay * (2 ** max(0, attempt - 1)), hold.max_delay)

    def _retry_notice(self, attempt: int, reason: str) -> None:
        self._set_status('connecting', retrying=True)
        self.add_notice(f'Retrying ({attempt}/{self.config.hold.max_retries}): '
                        f'{reason[:160]}', 'warning')

    async def _round_once(self, budget: TokenBudget
                          ) -> tuple[str, str, list[dict[str, Any]], str]:
        """One model round: returns (thinking, text, tool_calls, finish_reason).

        ``thinking`` is the full reasoning of the round, including the part
        flushed before the answer text started.
        """
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

        if thinking_parts:
            self._thinking_done(''.join(thinking_parts), started)
        full = ''.join(text_parts)
        thinking = ''.join(self._round_thinking)
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
        # Keep what the flush is about to empty: the round's own reasoning
        # has to reach the history even when the answer text started first.
        if text:
            self._round_thinking.append(text)
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
                reference = image_marker(match)
                if reference not in image_markers:
                    image_markers.append(reference)

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
        # The aside must know it is one: without this system prompt the model
        # would happily continue the main task instead of answering briefly.
        msgs = [ChatMessage.system(ASIDE_SYSTEM), *msgs]
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
