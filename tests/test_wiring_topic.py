# Wiring W3.4: the topic lifecycle state machine, sunk from the study app.
#   - without a detector the machine runs fail-closed (structural only);
#   - with the drift detector the continue/new/reopen thresholds apply;
#   - a raising detector degrades to continue, never crashes the caller.

import pytest

from aicf.harness.memory.topic import (
    ACTION_CONTINUE,
    ACTION_NEW,
    ACTION_REOPEN,
    DriftTopicDetector,
    TopicManager,
)


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _vec(seed: float, dim: int = 8) -> list[float]:
    return [seed] * dim


def test_without_detector_only_structural_transitions():
    clock = _FakeClock()
    manager = TopicManager(clock=clock)
    first = manager.observe('hello')
    assert first.state == 'active'
    second = manager.observe('still the same chat')
    assert second.topic_id == first.topic_id  # continue is structural
    closed = manager.close_current(summary='done chatting')
    assert closed.state == 'closed' and closed.summary == 'done chatting'
    third = manager.observe('a brand new thread')
    assert third.topic_id != first.topic_id
    assert manager.active().topic_id == third.topic_id


def test_drift_detector_continues_within_threshold():
    clock = _FakeClock()
    manager = TopicManager(detector=DriftTopicDetector(), clock=clock)
    topic = manager.observe('talk about tea', _vec(1.0))
    assert manager.observe('more about tea', _vec(0.95)).topic_id == topic.topic_id


def test_drift_detector_opens_new_on_drift():
    clock = _FakeClock()
    manager = TopicManager(detector=DriftTopicDetector(), clock=clock)
    first = manager.observe('talk about tea', _vec(1.0))
    second = manager.observe('now the weather', _vec(0.0))
    assert second.topic_id != first.topic_id
    assert first.state == 'closed'  # opening a new topic closes the current one


def test_drift_detector_reopens_a_closed_topic():
    clock = _FakeClock()
    manager = TopicManager(detector=DriftTopicDetector(), clock=clock)
    tea = manager.observe('talk about tea', _vec(1.0))
    manager.close_current(summary='tea done')
    back = manager.observe('back to tea please', _vec(0.9))
    assert back.topic_id == tea.topic_id
    assert back.state == 'active'
    assert tea.closed_at == 0.0  # reopen clears the close mark


def test_time_boundary_closes_the_topic():
    clock = _FakeClock()
    detector = DriftTopicDetector(idle_seconds=600.0)
    manager = TopicManager(detector=detector, clock=clock)
    first = manager.observe('before the break', _vec(1.0))
    clock.advance(3600.0)
    second = manager.observe('after the break', _vec(1.0))  # same vector, too idle
    assert second.topic_id != first.topic_id


def test_raising_detector_degrades_to_continue():
    class Broken:
        def decide(self, *_args, **_kwargs):
            raise RuntimeError('detector exploded')

    clock = _FakeClock()
    manager = TopicManager(detector=Broken(), clock=clock)
    first = manager.observe('hello')
    assert manager.observe('again').topic_id == first.topic_id  # fail-closed continue
