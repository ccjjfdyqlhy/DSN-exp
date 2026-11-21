# Wiring W2: SDK parity with the CLI on the two promises that were CLI-only:
#   1. tool intents land in the managed runtime journal, and an identical
#      in-turn call replays from cache instead of re-executing;
#   2. semantic recall is reachable through create_agent(embedding_client=...).

from pathlib import Path

from aicf.harness import create_agent
from aicf.harness.cli.common import build_model
from aicf.harness.tools.function_tool import tool_from_function
from aicf.harness.tools.spec import ToolSpec
from aicf.infra.orchestrator.base import ChatResponse, ToolCall
from aicf.infra.orchestrator.stub import StubChatClient, StubEmbeddingClient


def _managed_runtime(db_path: Path, session_id: str):
    from aicf.infra.runtime import ManagedRuntime, SqliteRuntimeStore, migrate_runtime
    from aicf.infra.store.sqlite import SqliteStore

    store = SqliteStore(str(db_path))
    migrate_runtime(store)
    runtime = ManagedRuntime(SqliteRuntimeStore(store), session_id=session_id)
    runtime.start_session(session_id=session_id)
    return runtime, store


def _note_tool(calls):
    def note_something(text: str) -> str:
        """Record a note."""
        calls.append(text)
        return 'noted'
    t = tool_from_function(note_something)
    t.spec = ToolSpec(name='note_something', effect='idempotent')  # no approval needed, cacheable
    return t


def _tool_call(call_id):
    return ToolCall(id=call_id, name='note_something', arguments={'text': 'wired'})


def test_sdk_runtime_replays_identical_calls_once(tmp_path: Path):
    calls = []
    note = _note_tool(calls)
    scripted = StubChatClient(responses=[
        ChatResponse(content='', tool_calls=[_tool_call('a'), _tool_call('b')]),
        ChatResponse(content='done'),
    ])
    runtime, store = _managed_runtime(tmp_path / 'db.sqlite', 'sdk-wiring')
    try:
        agent = create_agent(model='stub', client=scripted, tools=[note], runtime=runtime)
        assert 'done' in agent.run('note it')
    finally:
        store.close()
    assert calls == ['wired']  # two identical in-turn calls, one execution


def test_sdk_without_runtime_still_runs(tmp_path: Path):
    calls = []
    note = _note_tool(calls)
    scripted = StubChatClient(responses=[
        ChatResponse(content='', tool_calls=[_tool_call('a')]),
        ChatResponse(content='done'),
    ])
    agent = create_agent(model='stub', client=scripted, tools=[note])
    assert 'done' in agent.run('note it')
    assert calls == ['wired']  # runtime=None stays a working (unjournaled) path


def test_sdk_embedding_client_reaches_the_memory_store():
    agent = create_agent(model='stub', client=build_model(model='stub'),
                         enable_memory=True, embedding_client=StubEmbeddingClient(dim=32))
    store = agent._memory_store()
    assert store is not None
    store.add_text('the quarterly report was filed on monday', role='user')
    assert store.search('q3 financial filing submitted')
