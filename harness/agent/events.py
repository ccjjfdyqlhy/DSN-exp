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

    # ── 事件词表 v2（策划案 §5.2）────────────────────────────
    #
    # 增量原则：既有 kind 一个不改（避免破坏已有消费方），只新增下面这些。
    # 新增字段 trace_id / span_id / seq 全部是**可选**的 —— 旧的事件生产者
    # 不带它们，消费方必须容忍缺失。
    'approval_request': 'id, tool, args_preview, effect, risk, expires_at',
    'approval_decision': 'id, tool, decision, decided_by, reason, scope',
    'approval_timeout': 'id, tool',
    'tool_blocked': 'tool, reason, effect, risk',
    'sandbox_degraded': 'tool, backend, detail',
    'tool_intent': 'tool, idempotency_key, effect, args_digest',
    'tool_effect_unknown': 'tool, idempotency_key, effect',
    'run_started': 'run_id, session_id',
    'run_finished': 'run_id, session_id, status, usage',
    'run_failed': 'run_id, session_id, error',
    'checkpoint_written': 'session_id, turn_seq, ref',
    'session_resumed': 'session_id, turn_seq',

    # 审计事件（策划案 §4.4.7）：与业务事件同流，但独立存储、不可被业务删除。
    'audit.tool_call': 'identity, tool, version, args_digest, effect, sandbox, '
                       'decision, duration, outcome',
    'audit.denied': 'identity, tool, reason',
    'audit.secret_access': 'identity, credential_ref, tool',
    'audit.delegation': 'from, to, scopes',
}

#: v2 新增的可选字段 —— 旧事件不带它们，消费方必须容忍缺失
TRACE_FIELDS = ('trace_id', 'span_id', 'seq')


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
