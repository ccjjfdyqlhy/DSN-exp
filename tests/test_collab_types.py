# tests/test_collab_types.py
# Agent types, mailbox settlement and the activity stream: a spawned child
# takes its system, model and tool allowlist from its registered type; the
# updates a broken turn never committed come back; a UI drains the activity
# stream without the engine pump eating it.

from __future__ import annotations

import asyncio

from harness.agent.collab import AgentManager, AgentTypeSpec
from harness.agent.engine import ConversationEngine
from harness.agent.engine_config import AgentSettings, ModelInfo
from harness.agent.events import EventSink
from harness.tools.registry import ManagedToolRegistry


class EchoClient:
    model = 'echo'

    async def stream(self, messages, tools=None, **kwargs):
        yield 'done'
        yield {'finish': 'stop'}

    def invoke(self, messages, tools=None, **kwargs):
        raise NotImplementedError


def _manager(model_resolver=None, config: AgentSettings | None = None):
    registry = ManagedToolRegistry()
    manager = AgentManager(client=EchoClient(), registry=registry,
                           model=ModelInfo(id='parent-model'),
                           config=config or AgentSettings(),
                           model_resolver=model_resolver)
    return manager, registry


def _root(manager, registry):
    engine = ConversationEngine(client=EchoClient(), registry=registry,
                                store=None, model=ModelInfo(id='parent-model'))
    loop = asyncio.new_event_loop()
    engine.sink = EventSink()
    manager.attach(engine, loop=loop)
    return engine, loop


def test_a_child_takes_the_type_system_and_tools():
    manager, registry = _manager()
    manager.register_agent_type(AgentTypeSpec(
        name='explorer', system='You explore.', tools=['read', 'glob']))
    engine, loop = _root(manager, registry)

    async def main() -> None:
        record = await manager.spawn('scout', 'go', agent_type='explorer')
        assert record.engine._allowed_tools == {'read', 'glob'}
        assert 'You explore.' in record.engine.system_prompt()
        assert 'sub-agent' in record.engine.system_prompt()
        # the allowlist limits the schema the child's requests carry
        schema = {tool['function']['name']
                  for tool in record.engine._fresh_prefix().tools}
        assert 'spawn_agent' not in schema    # the allowlist excludes it

    asyncio.run(main())
    loop.close()


def test_an_unknown_type_falls_back_to_the_default():
    manager, registry = _manager(config=AgentSettings(default_type='general'))
    manager.register_agent_type(AgentTypeSpec(name='general'))
    engine, loop = _root(manager, registry)

    async def main() -> None:
        record = await manager.spawn('worker', 'go', agent_type='nope')
        assert record.engine._allowed_tools is None

    asyncio.run(main())
    loop.close()


def test_the_type_model_is_resolved_through_the_hook():
    child_client = EchoClient()

    def resolver(model_id):
        if model_id == 'fast-model':
            return child_client, ModelInfo(id='fast-model')
        return None

    manager, registry = _manager(model_resolver=resolver)
    manager.register_agent_type(AgentTypeSpec(
        name='worker', model='fast-model'))
    engine, loop = _root(manager, registry)

    async def main() -> None:
        record = await manager.spawn('w1', 'go', agent_type='worker')
        assert record.engine._client is child_client
        assert record.engine._model.id == 'fast-model'

    asyncio.run(main())
    loop.close()


def test_a_type_model_without_a_resolver_inherits_the_parent():
    manager, registry = _manager()
    manager.register_agent_type(AgentTypeSpec(
        name='worker', model='fast-model'))
    engine, loop = _root(manager, registry)

    async def main() -> None:
        record = await manager.spawn('w1', 'go', agent_type='worker')
        assert record.engine._model.id == 'parent-model'

    asyncio.run(main())
    loop.close()


def test_the_spawn_agent_tool_carries_the_type():
    manager, registry = _manager()
    manager.register_agent_type(AgentTypeSpec(
        name='reviewer', system='You review.'))
    engine, loop = _root(manager, registry)
    manager._loop = loop

    async def main() -> None:
        tools = {tool.name: tool for tool in registry.tools()}
        spawn = tools.get('spawn_agent')
        assert spawn is not None
        assert 'agent_type' in spawn.parameters['properties']

    asyncio.run(main())
    loop.close()


def test_settle_mailbox_returns_undelivered_updates():
    manager, registry = _manager()
    engine, loop = _root(manager, registry)
    record = manager._agents['root']

    async def main() -> None:
        record.engine.conversation.committed.extend([
            {'role': 'user', 'content': 'go'}])
        updates = manager.consume_mailbox(engine)
        assert updates == []
        record.inbox.append('<subagent_update agent="a">found it</subagent_update>')
        consumed = manager.consume_mailbox(engine)
        assert len(consumed) == 1
        # the turn never staged the update: settlement puts it back
        lost = manager.settle_mailbox(engine)
        assert lost == 1
        assert manager.consume_mailbox(engine) == consumed
        # a turn that staged both updates settles to nothing
        record.engine.conversation.committed.extend(
            {'role': 'user', 'content': text} for text in consumed)
        record.inbox.append('<subagent_update agent="b">again</subagent_update>')
        record.engine.conversation.committed.extend(
            {'role': 'user', 'content': text}
            for text in manager.consume_mailbox(engine))
        assert manager.settle_mailbox(engine) == 0

    asyncio.run(main())
    loop.close()


def test_the_activity_stream_survives_the_engine_pump():
    manager, registry = _manager()
    engine, loop = _root(manager, registry)
    record = manager._agents['root']
    child = ConversationEngine(client=EchoClient(), registry=registry,
                               store=None, model=ModelInfo(id='parent-model'),
                               agent_name='child')

    async def main() -> None:
        from harness.agent.collab import _forwarding_sink
        child.sink = _forwarding_sink(child, manager)
        child.sink.emit('text_delta', {'text': 'hello'})
        child.sink.emit('tool_start', {'name': 'read'})
        child.sink.emit('agent_event', {'status': 'completed'})
        # the engine pump only drains the lifecycle stream
        engine.conversation.stage({'role': 'user', 'content': 'x'})
        engine._stage_collab_mailbox()
        lifecycle = engine.sink.drain()
        kinds = [kind for kind, _ in lifecycle]
        assert 'agent_event' in kinds
        assert 'text_delta' not in kinds
        assert 'tool_start' not in kinds
        # and the activity stream keeps everything for the UI
        activity = [kind for kind, _ in manager.drain_activity()]
        assert activity == ['text_delta', 'tool_start', 'agent_event']

    asyncio.run(main())
    loop.close()


def test_forward_events_false_silences_the_transcript_stream():
    manager, registry = _manager()
    manager.forward_events = False
    engine, loop = _root(manager, registry)
    record = manager._agents['root']
    child = ConversationEngine(client=EchoClient(), registry=registry,
                               store=None, model=ModelInfo(id='parent-model'),
                               agent_name='child')

    async def main() -> None:
        from harness.agent.collab import _forwarding_sink
        child.sink = _forwarding_sink(child, manager)
        child.sink.emit('agent_event', {'status': 'completed'})
        assert manager.drain_events() == []
        assert [kind for kind, _ in manager.drain_activity()] == ['agent_event']

    asyncio.run(main())
    loop.close()


def test_set_model_and_reinstall_tools():
    manager, registry = _manager()
    engine, loop = _root(manager, registry)
    manager.set_model(ModelInfo(id='next-model'))
    assert manager._model.id == 'next-model'
    registry.unregister_source('collab')
    manager.reinstall_tools()
    names = {tool.name for tool in registry.tools()}
    assert 'spawn_agent' in names
    loop.close()
