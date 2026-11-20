# Wiring W3: the memory pieces finally reach the main path.
#   - layered recall (L0-L3 budget view) via create_agent(memory_mode=...);
#   - the MemoryStorePort has a framework default registered on the runtime;
#   - vectors persist through SessionStore (pack/unpack_embedding consumers).

from pathlib import Path

from aicf.harness import create_agent
from aicf.harness.cli.common import build_model
from aicf.infra.orchestrator.stub import StubEmbeddingClient


def _agent(**options):
    return create_agent(model='stub', client=build_model(model='stub'),
                        enable_memory=True,
                        embedding_client=StubEmbeddingClient(dim=32), **options)


def test_default_recall_stays_flat():
    agent = _agent()
    store = agent._memory_store()
    store.add_text('user likes tea', role='memo')
    block = agent._recall('tea')
    assert block and 'user likes tea' in block[0].content
    assert '[L' not in block[0].content  # off mode: no layer tags


def test_layered_mode_tags_layers_and_honors_budget():
    agent = _agent(memory_mode='layered', memory_budget=12000)
    store = agent._memory_store()
    store.add_text('likes tea', role='memo')
    store.add_text('filed the report on monday', role='user')
    block = agent._recall('tea and reports')
    assert block, 'layered recall must still produce a block'
    assert '[L2]' in block[0].content  # everything stored lands in L2 by default


def test_layered_budget_drops_overflow():
    agent = _agent(memory_mode='layered', memory_budget=10)  # tiny budget
    store = agent._memory_store()
    for i in range(20):
        store.add_text(f'long memory entry number {i} ' * 8, role='user')
    block = agent._recall('memory entries')
    assert block
    assert len(block[0].content) <= 12000  # the view never exceeds its budget


def test_memory_port_is_registered_and_speaks_the_protocol():
    from aicf.harness.memory import SessionMemoryStore
    from aicf.harness.memory.base import MemoryStorePort

    agent = _agent()
    port = agent._assembled.runtime.get('memory_port')
    assert isinstance(port, SessionMemoryStore)
    assert isinstance(port, MemoryStorePort)  # runtime-checkable protocol
    port.summarize_turn(1, 1, 1, 'hello there', 'hi!')
    assert port.search(1, ['hello'])  # the turn landed in the recall index


def test_vectors_persist_in_session_store(tmp_path: Path):
    from aicf.harness.memory import SqliteVectorMemory
    from aicf.infra.store.chat_store import SessionStore

    db = tmp_path / 'mem.sqlite'
    store = SessionStore(db_path=str(db))
    store.create_session()
    memory = SqliteVectorMemory(store, StubEmbeddingClient(dim=32))
    memory.add_text('the quarterly report was filed on monday')
    assert memory.count() == 1
    assert memory.search('q3 financial filing submitted')

    # a fresh store instance over the same db finds it: persistence works
    memory2 = SqliteVectorMemory(SessionStore(db_path=str(db)), StubEmbeddingClient(dim=32))
    assert memory2.count() == 1
    assert memory2.search('quarterly report')
