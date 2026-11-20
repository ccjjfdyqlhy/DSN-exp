# harness/memory/topic.py
# Topic lifecycle state machine (W3.4, sunk from the study app's design).
#
# Division of labor -- the trimming engine is NOT rewritten here:
#   - lifecycle (open / continue / close / reopen) lives here;
#   - trimming stays with harness.context_assembly.SegmentedContextAssembler
#     (the app turns topics into ContextSegments, the assembler cuts them);
#   - boundary detection is a port: apps inject their own TopicDetectorPort,
#     and the shipped DriftTopicDetector is only the cosine-drift fallback,
#     the same "real classifier is a port, heuristics ship as fallback" rule
#     the voice package uses.
#
# Fail-closed contract: without a detector the manager still runs -- the
# first message opens a topic, the current one continues, close_current
# closes it -- but NO semantic new/reopen happens, because deciding that a
# message "belongs to another topic" is semantics the framework must not
# invent. A raising detector is treated the same way (logged, then continue).

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional, Protocol

from aicf.infra.vector import cosine_similarity

logger = logging.getLogger('aicf.harness.memory.topic')

TOPIC_ACTIVE = 'active'
TOPIC_CLOSED = 'closed'

ACTION_CONTINUE = 'continue'
ACTION_NEW = 'new'
ACTION_REOPEN = 'reopen'

#: default boundaries, all injectable (they are parameters, not framework constants)
DEFAULT_CONTINUE_THRESHOLD = 0.65
DEFAULT_REOPEN_THRESHOLD = 0.50
DEFAULT_IDLE_SECONDS = 1800.0


@dataclass
class TopicRecord:
    """One topic: identity, lifecycle state, and its centroid vector."""

    topic_id: str
    title: str = ''
    state: str = TOPIC_ACTIVE
    opened_at: float = 0.0
    last_active_at: float = 0.0
    closed_at: float = 0.0
    summary: str = ''
    vector: list[float] | None = None
    message_count: int = 0
    meta: dict = field(default_factory=dict)


@dataclass
class TopicDecision:
    """What the detector wants to do with the incoming message."""

    action: str                      # continue | new | reopen
    topic_id: str = ''               # for reopen: which closed topic
    reason: str = ''


class TopicDetectorPort(Protocol):
    """Boundary detection port. Framework owns the state machine, you own this."""

    def decide(self, message_vector: list[float] | None, *,
               current: Optional[TopicRecord],
               closed: Iterable[TopicRecord],
               idle_seconds: float) -> TopicDecision: ...


class DriftTopicDetector:
    """Cosine-drift fallback detector (the study app's semantic boundary).

    continue: message stays near the current topic centroid;
    reopen:   message matches a closed topic better than the continue floor;
    new:      everything else, or the topic went idle past the time boundary.
    """

    def __init__(self, *,
                 continue_threshold: float = DEFAULT_CONTINUE_THRESHOLD,
                 reopen_threshold: float = DEFAULT_REOPEN_THRESHOLD,
                 idle_seconds: float = DEFAULT_IDLE_SECONDS):
        self.continue_threshold = continue_threshold
        self.reopen_threshold = reopen_threshold
        self.idle_seconds = idle_seconds

    def decide(self, message_vector: list[float] | None, *,
               current: Optional[TopicRecord],
               closed: Iterable[TopicRecord],
               idle_seconds: float) -> TopicDecision:
        if current is None:
            # no open topic: the only semantic choice is reopen-vs-new, and
            # reopen is exactly what happens when the user returns to an old thread
            best, best_score = self._best_closed_match(message_vector, closed)
            if best is not None:
                return TopicDecision(ACTION_REOPEN, topic_id=best.topic_id,
                                     reason=f'cosine {best_score:.2f} to closed topic')
            return TopicDecision(ACTION_NEW, reason='no open topic')
        if idle_seconds >= self.idle_seconds:
            return TopicDecision(ACTION_NEW, reason='time boundary reached')
        if message_vector is None or current.vector is None:
            return TopicDecision(ACTION_CONTINUE, reason='no vectors to compare')
        if cosine_similarity(message_vector, current.vector) >= self.continue_threshold:
            return TopicDecision(ACTION_CONTINUE, reason='drift below threshold')
        best, _best_score = self._best_closed_match(message_vector, closed)
        if best is not None:
            return TopicDecision(ACTION_REOPEN, topic_id=best.topic_id,
                                 reason='drift above threshold, closed topic matches')
        return TopicDecision(ACTION_NEW, reason='drift above threshold, no reopen match')

    def _best_closed_match(self, message_vector, closed):
        best, best_score = None, self.reopen_threshold
        for candidate in closed or []:
            if candidate.vector is None or message_vector is None:
                continue
            score = cosine_similarity(message_vector, candidate.vector)
            if score >= best_score:
                best, best_score = candidate, score
        return best, best_score


class TopicManager:
    """Lifecycle owner: open / continue / close / reopen, nothing else.

    The manager never decides semantics itself. Detection is delegated to
    the injected port; without one the machine runs fail-closed (structural
    opens and closes only). Storage stays a port too -- hand in a callable
    pair to persist state, or keep it in memory.
    """

    def __init__(self, *,
                 detector: TopicDetectorPort | None = None,
                 clock: Callable[[], float] = time.time,
                 topic_id_factory: Callable[[], str] | None = None):
        self._detector = detector
        self._clock = clock
        self._seq = 0
        self.topics: dict[str, TopicRecord] = {}
        self._current_id: str | None = None
        self._id_factory = topic_id_factory or (lambda: f'topic-{self._seq:04d}')

    # ── state ───────────────────────────────────────────
    def active(self) -> Optional[TopicRecord]:
        return self.topics.get(self._current_id) if self._current_id else None

    def closed_topics(self) -> list[TopicRecord]:
        return [t for t in self.topics.values() if t.state == TOPIC_CLOSED]

    # ── lifecycle ───────────────────────────────────────
    def observe(self, text: str, vector: list[float] | None = None,
                *, title: str = '') -> TopicRecord:
        """Feed one message in; returns the topic it landed on."""
        now = self._clock()
        current = self.active()
        idle = (now - current.last_active_at) if current else 0.0
        decision = self._decide(vector, current, idle)
        if decision.action == ACTION_CONTINUE and current is not None:
            self._touch(current, text, vector, now)
            return current
        if decision.action == ACTION_REOPEN:
            target = self.topics.get(decision.topic_id)
            if target is not None and target.state == TOPIC_CLOSED:
                if current is not None:
                    self.close_current()
                self._reopen(target, now)
                self._touch(target, text, vector, now)
                return target
            logger.warning('detector asked to reopen unknown topic %s; opening new',
                           decision.topic_id)
        # ACTION_NEW, or a reopen that could not be honored
        if current is not None:
            self.close_current()
        return self._open(text, vector, now, title=title)

    def close_current(self, *, summary: str = '') -> Optional[TopicRecord]:
        """Structural close: the current topic is frozen with a summary."""
        current = self.active()
        if current is None:
            return None
        current.state = TOPIC_CLOSED
        current.closed_at = self._clock()
        if summary:
            current.summary = summary
        self._current_id = None
        return current

    # ── internals ───────────────────────────────────────
    def _decide(self, vector, current, idle) -> TopicDecision:
        if self._detector is None:
            # fail-closed: structural transitions only, no invented semantics
            return TopicDecision(ACTION_CONTINUE if current else ACTION_NEW,
                                 reason='no detector injected')
        try:
            return self._detector.decide(vector, current=current,
                                         closed=self.closed_topics(),
                                         idle_seconds=idle)
        except Exception as error:  # noqa: BLE001
            logger.warning('topic detector failed (%s); fail-closed continue', error)
            return TopicDecision(ACTION_CONTINUE if current else ACTION_NEW,
                                 reason='detector error')

    def _open(self, text: str, vector, now: float, *, title: str = '') -> TopicRecord:
        self._seq += 1
        record = TopicRecord(
            topic_id=self._id_factory(),
            title=title or (text[:32] if text else ''),
            state=TOPIC_ACTIVE,
            opened_at=now,
            last_active_at=now,
            vector=vector,
        )
        self.topics[record.topic_id] = record
        self._current_id = record.topic_id
        return record

    def _reopen(self, record: TopicRecord, now: float) -> None:
        record.state = TOPIC_ACTIVE
        record.closed_at = 0.0
        record.last_active_at = now
        self._current_id = record.topic_id

    def _touch(self, record: TopicRecord, text: str, vector, now: float) -> None:
        record.last_active_at = now
        record.message_count += 1
        if vector is not None:
            # running centroid: the topic vector tracks the conversation
            if record.vector is None:
                record.vector = list(vector)
            else:
                weight = 1.0 / max(record.message_count, 1)
                record.vector = [old * (1 - weight) + new * weight
                                 for old, new in zip(record.vector, vector)]


__all__ = [
    'TOPIC_ACTIVE', 'TOPIC_CLOSED',
    'ACTION_CONTINUE', 'ACTION_NEW', 'ACTION_REOPEN',
    'DEFAULT_CONTINUE_THRESHOLD', 'DEFAULT_REOPEN_THRESHOLD', 'DEFAULT_IDLE_SECONDS',
    'TopicRecord', 'TopicDecision', 'TopicDetectorPort',
    'DriftTopicDetector', 'TopicManager',
]
