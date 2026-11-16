# harness/agent/events.py
# The conversation engine's event vocabulary and the sink that carries it.
#
# The engine reports everything through (kind, payload) events.  The sink is
# thread-safe: the loop emits from its task, any consumer drains from any
# thread.

from __future__ import annotations

import queue
import threading
from typing import Any, Callable

#: status event values
STATUSES = ('idle', 'connecting', 'thinking', 'answering', 'tool',
            'compacting', 'aside')

#: notice levels
LEVELS = ('info', 'warning', 'error')

#: every event kind the engine can emit, with its payload keys
EVENT_KINDS: dict[str, str] = {
    'turn_start': 'turn, text',
    'status': 'status[, retrying]',
    'thinking_delta': 'text',
    'thinking_end': 'text, duration',
    'text_delta': 'text',
    'text_end': 'text, duration',
    'tool_start': 'turn, call_id, name, display, args',
    'tool_output': 'call_id, text',
    'tool_end': 'turn, call_id, name, display, output, diff, duration, error',
    'usage': 'input_tokens, cached_input_tokens, uncached_input_tokens, '
             'output_tokens, cache_hit_rate[, prefix_generation, prefix_hash, '
             'provider, model, latency_ms]',
    'notice': 'text, level',
    'error': 'text',
    'interrupted': '',
    'diff_added': '',
    'queued': 'text, mode, position',
    'turn_end': "turn, status('done'|'interrupted'), stats",
    'compaction_start': '',
    'compaction_delta': 'text',
    'compaction_end': 'text, removed',
    'aside_start': 'question',
    'aside_delta': 'text',
    'aside_end': 'question, answer',
    'agent_event': 'agent, status, content',
    'agents_refresh': '',
    'session_loaded': 'name, title',
    'session_cleared': '',
    'session_rewound': 'turn',
    'model_changed': 'provider, model',
    'tools_refreshed': '',
}


EventCallback = Callable[[str, dict[str, Any]], None]


class EventSink:
    """Collect engine events for a UI: optional live callback plus a queue.

    ``emit`` never raises: a broken callback must not kill a turn.  The queue
    is unbounded, drained by the consumer with
    ``drain(limit)``.
    """

    def __init__(self, emit: EventCallback | None = None) -> None:
        self._emit = emit
        self._events: 'queue.Queue[tuple[str, dict[str, Any]]]' = queue.Queue()
        self._lock = threading.Lock()

    def emit(self, kind: str, payload: dict[str, Any] | None = None) -> None:
        event = dict(payload or {})
        with self._lock:
            self._events.put((kind, event))
        if self._emit is not None:
            try:
                self._emit(kind, event)
            except Exception:
                pass

    def drain(self, limit: int = 2_000) -> list[tuple[str, dict[str, Any]]]:
        out: list[tuple[str, dict[str, Any]]] = []
        while len(out) < limit:
            try:
                out.append(self._events.get_nowait())
            except queue.Empty:
                break
        return out

    @property
    def depth(self) -> int:
        """The events waiting in the queue, drained or not."""
        return self._events.qsize()
