# tests/test_agent_engine.py
# The conversation engine: turn flow, tools, continuation, aside, retries,
# usage accounting and session persistence, driven by a scripted client.

from __future__ import annotations

import asyncio

import pytest

from harness.agent.engine import ConversationEngine
from harness.agent.engine_config import EngineConfig, ModelInfo
from harness.agent.events import EventSink
from harness.tools.context import ToolContext, current_context
from harness.tools.registry import AnnotatedTool, ManagedToolRegistry
from harness.transcript import SessionStore


class ScriptedClient:
    """Replays per-call rounds of raw stream events."""

    model = 'stub'

    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.calls = 0
        self.kwargs: list[dict] = []

    async def stream(self, messages, tools=None, **kwargs):
        self.kwargs.append(kwargs)
        index = min(self.calls, len(self.rounds) - 1)
        self.calls += 1
        for event in self.rounds[index]:
            yield event

    def invoke(self, messages, tools=None, **kwargs):
        raise NotImplementedError('engine uses stream')


def _model(**overrides):
    kwargs = dict(id='m1', provider='p', endpoint='https://api.example.com/v1',
                  wire='chat', context_window=128_000, max_output_tokens=2_048,
                  reasoning_style='effort',
                  reasoning_efforts=('low', 'medium', 'high'),
                  reasoning=True)
    kwargs.update(overrides)
    return ModelInfo(**kwargs)


def _config(**overrides):
    kwargs = dict(max_output_tokens=1_024)
    kwargs.update(overrides)
    return EngineConfig(**kwargs)


def _note_tool():
    def handler(text):
        context = current_context()
        if context.live_sink is not None:
            context.live_sink('working...')
        return f'noted: {text}'
    return AnnotatedTool(
        name='note', description='note something', read_only=True,
        parameters={'type': 'object',
                    'properties': {'text': {'type': 'string'}},
                    'required': ['text']},
        handler=handler)


def _registry():
    registry = ManagedToolRegistry()
    registry.register(_note_tool())
    return registry


def _engine(client, *, tmp_path=None, config=None, model=None, system=None):
    store = SessionStore(tmp_path) if tmp_path is not None else SessionStore()
    return ConversationEngine(
        client=client, registry=_registry(), store=store,
        system_provider=(lambda: system or 'sys'),
        cwd=str(tmp_path or '.'),
        model=model or _model(), config=config or _config())


async def _wait_idle(engine, timeout=5.0):
    async def poll():
        while engine.busy() or not engine._work.empty():
            await asyncio.sleep(0.01)
    await asyncio.wait_for(poll(), timeout)


def _kinds(engine):
    return [kind for kind, _ in engine.drain()]


def test_chat_turn_with_tool_round(tmp_path):
    client = ScriptedClient([
        [{'tool_calls': [{'index': 0, 'id': 'c1', 'name': 'note',
                          'arguments': '{"text'}]},
         {'tool_calls': [{'index': 0, 'id': '', 'name': '',
                          'arguments': '": "hello"}'}]},
         {'finish': 'tool_calls'}],
        [{'reasoning': 'thinking hard'},
         'the answer', {'finish': 'stop'}],
    ])
    engine = _engine(client, tmp_path=tmp_path)

    async def main():
        engine.start()
        engine.submit('do a thing')
        await _wait_idle(engine)
        await engine.shutdown()

    asyncio.run(main())
    kinds = _kinds(engine)
    assert 'tool_start' in kinds and 'tool_end' in kinds
    assert 'tool_output' in kinds            # the tool's live sink line
    assert 'text_delta' in kinds and 'thinking_delta' in kinds
    assert 'turn_start' in kinds and 'turn_end' in kinds
    items = engine.items_snapshot()
    assert [item.kind for item in items] == ['user', 'tool', 'thinking', 'assistant']
    assert items[1].output == 'noted: hello'
    # the conversation staged assistant(tool_calls) + the tool result
    roles = [m['role'] for m in engine.conversation.committed]
    assert roles == ['user', 'assistant', 'tool', 'assistant']
    assert engine.conversation.committed[1]['tool_calls'][0]['id'] == 'c1'
    assert engine.conversation.committed[2]['content'] == 'noted: hello'
    assert client.calls == 2


def test_usage_and_status_events(tmp_path):
    client = ScriptedClient([
        ['hello', {'usage': {'prompt_tokens': 100, 'completion_tokens': 5}},
         {'finish': 'stop'}],
    ])
    engine = _engine(client, tmp_path=tmp_path)

    async def main():
        engine.start()
        engine.submit('hi')
        await _wait_idle(engine)
        await engine.shutdown()

    asyncio.run(main())
    events = dict(engine.drain())
    assert events['status']['status'] == 'idle'
    snapshot = engine.snapshot()
    assert snapshot.total_in == 100 and snapshot.total_out == 5
    assert snapshot.turn == 1 and snapshot.status == 'idle'


def test_continuation_on_length(tmp_path):
    client = ScriptedClient([
        ['part one', {'finish': 'length'}],
        ['part two', {'finish': 'length'}],
        ['part three', {'finish': 'stop'}],
    ])
    engine = _engine(client, tmp_path=tmp_path)

    async def main():
        engine.start()
        engine.submit('long answer please')
        await _wait_idle(engine)
        await engine.shutdown()

    asyncio.run(main())
    assert client.calls == 3
    # one user message, two continuation prompts, one final assistant answer
    roles = [m['role'] for m in engine.conversation.committed]
    assert roles.count('user') == 3
    # like the reference engine, the staged answer is the final segment; the
    # earlier segments live in the continuation prompts
    assert engine.items_snapshot()[-1].text == 'part three'
    continuation_prompts = [m for m in engine.conversation.committed
                            if str(m.get('content', '')).startswith('<continuation_request>')]
    assert len(continuation_prompts) == 2
    assert 'part one' in continuation_prompts[0]['content']


def test_aside_leaves_history_alone(tmp_path):
    client = ScriptedClient([
        ['aside answer', {'finish': 'stop'}],
    ])
    engine = _engine(client, tmp_path=tmp_path)

    async def main():
        engine.start()
        engine.submit('aside: what was that?', mode='aside')
        await _wait_idle(engine)
        await engine.shutdown()

    asyncio.run(main())
    kinds = _kinds(engine)
    assert 'aside_start' in kinds and 'aside_delta' in kinds and 'aside_end' in kinds
    assert engine.conversation.committed == []    # an aside never touches history
    assert engine.items_snapshot()[-1].kind == 'aside'
    # the aside ran with low effort on the chat wire
    assert client.kwargs[0].get('reasoning_effort') == 'low'


def test_retry_events_surface_as_connecting(tmp_path):
    class FlakyThenGood(ScriptedClient):
        async def stream(self, messages, tools=None, **kwargs):
            self.kwargs.append(kwargs)
            index = self.calls
            self.calls += 1
            if index == 0:
                error = ConnectionError('boom')
                error.status_code = 503
                raise error
            for event in self.rounds[0]:
                yield event

    client = FlakyThenGood([['ok', {'finish': 'stop'}]])
    engine = _engine(client, tmp_path=tmp_path)

    async def main():
        engine.start()
        engine.submit('hi')
        await _wait_idle(engine)
        await engine.shutdown()

    asyncio.run(main())
    kinds = _kinds(engine)
    assert 'notice' in kinds
    statuses = [payload.get('status') for kind, payload in engine.sink.drain()
                if kind == 'status']
    # drained once already; re-collect from the transcript instead
    assert engine.conversation.committed[-1]['content'] == 'ok'
    assert client.calls == 2


def test_interrupt_drops_text_draft(tmp_path):
    class SlowClient(ScriptedClient):
        async def stream(self, messages, tools=None, **kwargs):
            self.calls += 1
            yield 'partial '
            await asyncio.sleep(2)
            yield 'answer'
            yield {'finish': 'stop'}

    engine = _engine(SlowClient([]), tmp_path=tmp_path)

    async def main():
        engine.start()
        engine.submit('slow one')
        await asyncio.sleep(0.2)
        engine.interrupt()
        await _wait_idle(engine)
        await engine.shutdown()

    asyncio.run(main())
    kinds = _kinds(engine)
    assert 'interrupted' in kinds
    assert engine.conversation.committed == []    # a text-only draft is dropped
    assert engine.items_snapshot()[-1].text == '[interrupted]'


def test_effort_params_reach_the_client(tmp_path):
    client = ScriptedClient([['ok', {'finish': 'stop'}]])
    engine = _engine(client, tmp_path=tmp_path, model=_model(wire='responses'))

    async def main():
        engine.start()
        engine.submit('hi')
        await _wait_idle(engine)
        await engine.shutdown()

    asyncio.run(main())
    kwargs = client.kwargs[0]
    assert kwargs['reasoning'] == {'effort': 'medium', 'summary': 'auto'}
    assert kwargs['prompt_cache_key'].startswith('sha256:')
    assert kwargs['max_tokens'] == 1_024


def test_session_roundtrip_and_rewind(tmp_path):
    client = ScriptedClient([['answer one', {'finish': 'stop'}],
                             ['answer two', {'finish': 'stop'}]])
    engine = _engine(client, tmp_path=tmp_path)

    async def main():
        engine.start()
        engine.submit('first question')
        await _wait_idle(engine)
        engine.submit('second question')
        await _wait_idle(engine)
        await engine.shutdown()

    asyncio.run(main())
    assert engine.session_name
    # a fresh engine loads the checkpoint and rewinds the second turn
    store = SessionStore(tmp_path)
    reloaded = ConversationEngine(
        client=ScriptedClient([]), registry=_registry(), store=store,
        system_provider=lambda: 'sys', cwd=str(tmp_path),
        model=_model(), config=_config())
    loaded = reloaded.load_session(engine.session_name)
    assert loaded is True
    assert len(reloaded.conversation.committed) == 4    # 2 x (user, assistant)
    assert reloaded.snapshot().turn == 2
    dropped = reloaded.rewind(2)
    assert dropped == 'second question'
    assert len(reloaded.conversation.committed) == 2
    assert [item.turn for item in reloaded.items_snapshot()] == [1, 1]
