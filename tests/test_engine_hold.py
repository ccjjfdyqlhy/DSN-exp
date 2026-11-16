# tests/test_engine_hold.py
# The hold mode and the interrupted-round context: the reasoning of a round
# that never finished stays in the history, and a held request is retried
# until it works, the user interrupts, or the retries run out.

from __future__ import annotations

import asyncio

import pytest

from harness.agent.engine import UNFINISHED_NOTE, ConversationEngine
from harness.agent.engine_config import EngineConfig, HoldSettings, ModelInfo
from harness.agent.events import EventSink
from harness.tools.registry import ManagedToolRegistry


class ScriptedClient:
    """A client whose rounds come from a script of events."""

    model = 'scripted'

    def __init__(self, script: list) -> None:
        self.script = script
        self.calls = 0

    async def stream(self, messages, tools=None, **kwargs):
        self.calls += 1
        for event in self.script:
            yield event

    def invoke(self, messages, tools=None, **kwargs):
        raise NotImplementedError


def _engine(client, tmp_path, hold: HoldSettings | None = None):
    config = EngineConfig(hold=hold or HoldSettings())
    return ConversationEngine(client=client, registry=ManagedToolRegistry(),
                              store=None, cwd=str(tmp_path),
                              model=ModelInfo(context_window=100_000),
                              config=config)


async def _wait_idle(engine, timeout=10.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if not engine.busy() and engine._work.empty():
            return
        await asyncio.sleep(0.02)
    raise AssertionError('the engine did not become idle')


def test_the_full_round_reasoning_reaches_the_history(tmp_path):
    """Reasoning that streamed before the answer text used to be dropped
    from the request the round returns; the history needs all of it."""
    client = ScriptedClient([
        {'reasoning': 'the plan is to move the caret back. '},
        'the answer',
        {'reasoning': 'and the wrap follows. '},
        {'finish': 'stop'},
    ])
    engine = _engine(client, tmp_path)

    async def main() -> None:
        engine.start()
        engine.submit('go')
        await _wait_idle(engine)
        await engine.shutdown()

    asyncio.run(main())
    committed = engine.conversation.committed
    assistant = [m for m in committed if m.get('role') == 'assistant']
    assert assistant
    reasoning = str(assistant[-1].get('reasoning_content') or '')
    assert 'the plan is to move the caret back' in reasoning
    assert 'the wrap follows' in reasoning


def test_a_cut_response_keeps_its_reasoning(tmp_path):
    client = ScriptedClient([
        {'reasoning': 'The plan is to move the caret back after the frame.'},
        {'finish': 'incomplete'},
    ])
    engine = _engine(client, tmp_path)

    async def main() -> None:
        engine.start()
        engine.submit('go')
        await _wait_idle(engine)
        await engine.shutdown()

    asyncio.run(main())
    committed = engine.conversation.committed
    contents = [str(m.get('content') or '') for m in committed]
    assert any(UNFINISHED_NOTE in text for text in contents), contents
    assert any('move the caret back' in text for text in contents), contents


def test_hold_retries_a_cut_response_until_it_works(tmp_path):
    class Flaky(ScriptedClient):
        async def stream(self, messages, tools=None, **kwargs):
            self.calls += 1
            if self.calls < 3:
                yield {'reasoning': 'partial'}
                yield {'finish': 'incomplete'}
                return
            yield {'reasoning': 'finally'}
            yield {'finish': 'stop'}

    engine = _engine(Flaky([]), tmp_path,
                     hold=HoldSettings(enabled=True, max_retries=5, delay=0))

    async def main() -> None:
        engine.start()
        engine.submit('go')
        await _wait_idle(engine)
        await engine.shutdown()

    asyncio.run(main())
    assert engine._client.calls == 3
    # The successful attempt is the one that counts: the partial answers of
    # the failed attempts are not in the history.
    last = engine.conversation.committed[-1]
    assert 'finally' in str(last.get('reasoning_content') or '')
    assert 'partial' not in str(last.get('reasoning_content') or '')


def test_hold_gives_up_after_the_configured_retries(tmp_path):
    class Broken(ScriptedClient):
        async def stream(self, messages, tools=None, **kwargs):
            self.calls += 1
            yield {'reasoning': 'partial'}
            yield {'finish': 'incomplete'}

    engine = _engine(Broken([]), tmp_path,
                     hold=HoldSettings(enabled=True, max_retries=3, delay=0))

    async def main() -> None:
        engine.start()
        engine.submit('go')
        await _wait_idle(engine)
        await engine.shutdown()

    asyncio.run(main())
    # One attempt plus three retries.
    assert engine._client.calls == 4


def test_without_hold_a_cut_response_ends_the_turn(tmp_path):
    client = ScriptedClient([{'reasoning': 'partial'}, {'finish': 'incomplete'}])
    engine = _engine(client, tmp_path, hold=HoldSettings(enabled=False))

    async def main() -> None:
        engine.start()
        engine.submit('go')
        await _wait_idle(engine)
        await engine.shutdown()

    asyncio.run(main())
    assert client.calls == 1


def test_hold_retries_an_exception(tmp_path):
    class Broken(ScriptedClient):
        def __init__(self) -> None:
            super().__init__([])
            self.calls = 0

        async def stream(self, messages, tools=None, **kwargs):
            self.calls += 1
            if self.calls < 2:
                raise RuntimeError('connection dropped')
            yield 'ok'
            yield {'finish': 'stop'}

    engine = _engine(Broken(), tmp_path,
                     hold=HoldSettings(enabled=True, max_retries=3, delay=0))

    async def main() -> None:
        engine.start()
        engine.submit('go')
        await _wait_idle(engine)
        await engine.shutdown()

    asyncio.run(main())
    assert engine._client.calls == 2
    assert engine.conversation.committed[-1]['content'] == 'ok'


def test_hold_stops_when_the_user_interrupts(tmp_path):
    class Slow(ScriptedClient):
        async def stream(self, messages, tools=None, **kwargs):
            self.calls += 1
            yield {'reasoning': 'partial'}
            yield {'finish': 'incomplete'}
            await asyncio.sleep(0.3)

    engine = _engine(Slow([]), tmp_path,
                     hold=HoldSettings(enabled=True, max_retries=50,
                                       delay=0.05))

    async def main() -> None:
        engine.start()
        engine.submit('go')
        await asyncio.sleep(0.15)
        engine.interrupt()
        await _wait_idle(engine)
        await engine.shutdown()

    asyncio.run(main())
    # The retry loop stops at the interrupt instead of hammering on.
    assert engine._client.calls < 50


def test_the_retry_waits_longer_each_time(tmp_path):
    engine = _engine(ScriptedClient([]), tmp_path,
                     hold=HoldSettings(enabled=True, max_retries=6,
                                       delay=1.0, max_delay=4.0))
    assert engine._hold_delay(1) == 1.0
    assert engine._hold_delay(2) == 2.0
    assert engine._hold_delay(3) == 4.0
    assert engine._hold_delay(9) == 4.0    # capped at max_delay


def test_configure_hold_updates_a_running_engine(tmp_path):
    engine = _engine(ScriptedClient([]), tmp_path)
    engine.configure_hold(True, 7, 0.5)
    assert engine.config.hold.enabled is True
    assert engine.config.hold.max_retries == 7
    assert engine.config.hold.delay == 0.5


def test_the_public_accessors(tmp_path):
    engine = _engine(ScriptedClient([]), tmp_path)
    assert engine.interrupt_event is engine._interrupt
    engine.interrupt()
    assert engine.interrupt_event.is_set()
    engine.clear_interrupt()
    assert not engine.interrupt_event.is_set()
    assert engine.usage_records() == []

    async def main() -> None:
        # submit without announce emits no queued event
        engine.sink = EventSink()
        engine.start()
        engine.submit('go', announce=False)
        assert engine.sink.drain() == []
        assert engine._work.qsize() == 1
        await engine.shutdown()

    asyncio.run(main())
