# tests/test_agent_collab.py
# Mailbox collaboration: spawn, delegated turns, parent mailbox delivery,
# messaging and waiting.

from __future__ import annotations

import asyncio

import pytest

from harness.agent.collab import AgentManager
from harness.agent.engine import ConversationEngine
from harness.agent.engine_config import AgentSettings, EngineConfig, ModelInfo
from harness.tools.registry import AnnotatedTool, ManagedToolRegistry


class ScriptedClient:
    """Replays per-call rounds of raw stream events, shared by all agents."""

    model = 'stub'

    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.calls = 0
        self.prompts: list[list[str]] = []

    async def stream(self, messages, tools=None, **kwargs):
        self.prompts.append([str(m.get('content') if isinstance(m, dict)
                                 else m.content)[:60] for m in messages])
        index = min(self.calls, len(self.rounds) - 1)
        self.calls += 1
        for event in self.rounds[index]:
            yield event

    def invoke(self, messages, tools=None, **kwargs):
        raise NotImplementedError('engine uses stream')


def _model():
    return ModelInfo(id='m1', provider='p', endpoint='https://x/v1',
                     wire='chat', context_window=32_000, max_output_tokens=1_024,
                     reasoning_style='effort',
                     reasoning_efforts=('low', 'medium', 'high'),
                     reasoning=False)


def _registry():
    registry = ManagedToolRegistry()
    registry.register(AnnotatedTool(
        name='echo', description='echo text', read_only=True,
        parameters={'type': 'object',
                    'properties': {'text': {'type': 'string'}},
                    'required': ['text']},
        handler=lambda text: f'echo: {text}'))
    return registry


def _rounds():
    # round 0 (root, turn 1): delegates; round 1 (child): answers its task;
    # round 2 (root, turn 2): sees the subagent update and answers
    return [
        [{'tool_calls': [{'index': 0, 'id': 'c1', 'name': 'spawn_agent',
                          'arguments': '{"task_name": "scout", "message": "look '
                                        'around"}'}]},
         {'finish': 'tool_calls'}],
        ['scout report: all clear', {'finish': 'stop'}],
        ['root acknowledges: all clear', {'finish': 'stop'}],
    ]


async def _wait_idle(engine, timeout=5.0):
    async def poll():
        while engine.busy() or not engine._work.empty():
            await asyncio.sleep(0.01)
    await asyncio.wait_for(poll(), timeout)


def test_spawn_delivers_update_to_parent_mailbox():
    client = ScriptedClient(_rounds())
    registry = _registry()

    async def main():
        root = ConversationEngine(
            client=client, registry=registry, cwd='.',
            model=_model(),
            config=EngineConfig(agents=AgentSettings(max_concurrent=3)),
            system_provider=lambda: 'sys')
        manager = AgentManager(client=client, registry=registry,
                               model=_model(),
                               config=AgentSettings(max_concurrent=3))
        manager.attach(root)
        root.start()
        root.submit('scout the area')
        await _wait_idle(root)
        # the child keeps running after the parent's turn ends; wait for it
        async def child_done():
            while manager._agents.get('scout') is None or \
                    manager._agents['scout'].status not in ('completed', 'errored',
                                                            'interrupted'):
                await asyncio.sleep(0.02)
        await asyncio.wait_for(child_done(), timeout=5)
        # a second root turn consumes the mailbox before its model round
        root.submit('what did you find?')
        await _wait_idle(root)
        await manager.shutdown()
        await root.shutdown()
        return root, manager

    root, manager = asyncio.run(main())
    # the child ran and completed
    rows = manager.list_agents()
    child = [row for row in rows if row['name'] == 'scout'][0]
    assert child['status'] == 'completed'
    assert 'all clear' in child['completed']
    # the parent consumed the update in its second turn
    user_messages = [m for m in root.conversation.committed
                     if m['role'] == 'user']
    updates = [m for m in user_messages
               if str(m.get('content', '')).startswith('<subagent_updates>')]
    assert updates, 'the parent turn must stage the mailbox'
    assert 'scout report: all clear' in updates[0]['content']
    assert '<subagent_update agent="scout" status="completed">' in updates[0]['content']


def test_send_message_and_list():
    client = ScriptedClient([['ok', {'finish': 'stop'}]])
    registry = _registry()

    async def main():
        root = ConversationEngine(client=client, registry=registry, cwd='.',
                                  model=_model(), system_provider=lambda: 'sys')
        manager = AgentManager(client=client, registry=registry, model=_model())
        manager.attach(root)
        # simulate a child record without running a turn
        from harness.agent.collab import AgentRecord, PENDING_INIT
        child_engine = ConversationEngine(
            client=client, registry=registry, cwd='.', model=_model(),
            agent_name='helper')
        manager._agents['helper'] = AgentRecord(name='helper', parent='root',
                                                depth=1, engine=child_engine,
                                                status=PENDING_INIT)
        result = manager.send_message('helper', 'hello there')
        assert result == {'delivered': True, 'turn_triggered': False}
        assert manager.consume_mailbox(child_engine) == ['From root: hello there']
        assert manager.send_message('ghost', 'x')['delivered'] is False
        rows = manager.list_agents()
        assert {row['name'] for row in rows} == {'root', 'helper'}
        await root.shutdown()

    asyncio.run(main())


def test_spawn_validates_input():
    client = ScriptedClient([['ok', {'finish': 'stop'}]])
    registry = _registry()

    async def main():
        root = ConversationEngine(client=client, registry=registry, cwd='.',
                                  model=_model(), system_provider=lambda: 'sys')
        manager = AgentManager(client=client, registry=registry, model=_model())
        manager.attach(root)
        with pytest.raises(ValueError):
            await manager.spawn('Bad Name!', 'task')
        with pytest.raises(ValueError):
            await manager.spawn('worker', '   ')
        await root.shutdown()

    asyncio.run(main())


def test_fork_turns_none_starts_blank():
    client = ScriptedClient(_rounds())

    async def main():
        registry = _registry()
        root = ConversationEngine(client=client, registry=registry, cwd='.',
                                  model=_model(), system_provider=lambda: 'sys')
        manager = AgentManager(client=client, registry=registry, model=_model())
        manager.attach(root)
        root.conversation.committed.extend([
            {'role': 'user', 'content': 'earlier context'},
            {'role': 'assistant', 'content': 'earlier answer'},
        ])
        record = await manager.spawn('fresh', 'go', fork_turns='none')
        assert record.engine.conversation.committed == []
        record_all = await manager.spawn('full', 'go', fork_turns='all')
        contents = [m['content'] for m in record_all.engine.conversation.committed]
        assert 'earlier context' in contents
        await manager.shutdown()
        await root.shutdown()

    asyncio.run(main())


def test_wait_agent_reports_activity():
    client = ScriptedClient([['ok', {'finish': 'stop'}]])
    registry = _registry()

    async def main():
        root = ConversationEngine(client=client, registry=registry, cwd='.',
                                  model=_model(), system_provider=lambda: 'sys')
        manager = AgentManager(client=client, registry=registry, model=_model())
        manager.attach(root)
        from harness.agent.collab import AgentRecord, RUNNING
        child_engine = ConversationEngine(
            client=client, registry=registry, cwd='.', model=_model(),
            agent_name='busy')
        record = AgentRecord(name='busy', parent='root', depth=1,
                             engine=child_engine, status=RUNNING)
        manager._agents['busy'] = record
        waiter = asyncio.create_task(manager.wait_for_activity(1_000))
        await asyncio.sleep(0.05)
        manager._touch(record)
        result = await waiter
        assert result['timed_out'] is False
        assert 'busy' in result['updated_agents']
        stale = await manager.wait_for_activity(50)
        assert stale['timed_out'] is True
        await root.shutdown()

    asyncio.run(main())
