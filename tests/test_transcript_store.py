# tests/test_transcript_store.py
# Session persistence: JSON payloads, transcript items, rewind and the
# rolling checkpoint.

from __future__ import annotations

from harness.transcript import (
    DbSessionStore, LAST_SESSION, SESSION_VERSION, SessionPayload,
    SessionStore, TranscriptItem, new_session_name,
)


def _item(kind, turn, text):
    return TranscriptItem(kind=kind, turn=turn, text=text)


def _payload(name='s1', **kwargs):
    return SessionPayload(name=name, title='t',
                          messages=kwargs.get('messages', []),
                          items=kwargs.get('items', []),
                          turn=kwargs.get('turn', 0))


def test_session_save_load_roundtrip(tmp_path):
    store = SessionStore(tmp_path)
    payload = _payload()
    payload.messages = [{'role': 'user', 'content': 'hi'}]
    payload.items = [_item('user', 1, 'hi')]
    store.save(payload)
    loaded = store.load('s1')
    assert loaded is not None
    assert loaded.messages == payload.messages
    assert loaded.items[0].kind == 'user'
    assert loaded.name == 's1'
    assert loaded.to_json()['version'] == SESSION_VERSION


def test_transcript_item_dict_roundtrip():
    item = TranscriptItem(kind='tool', turn=2, name='bash', call_id='c1',
                          args={'command': 'ls'}, output='out', duration=1.5)
    restored = TranscriptItem.from_dict(item.to_dict())
    assert restored == item
    # unknown fields drop silently instead of failing the load
    assert TranscriptItem.from_dict({'kind': 'user', 'turn': 1, 'text': 'x',
                                     'future_field': 1}) is not None
    assert TranscriptItem.from_dict({'no_kind': True}) is None


def test_session_names_and_listing(tmp_path):
    store = SessionStore(tmp_path)
    base = new_session_name()
    first = store.unique_name(base)
    # a non-session json file (no messages/history/items keys) stays unlisted
    (tmp_path / f'{first}.json').write_text('{"note": "not a session"}',
                                            encoding='utf-8')
    second = store.unique_name(base)
    assert second == f'{base}_2'
    store.save(_payload('alpha'), as_name='alpha')
    rows = store.list()
    assert [row['name'] for row in rows] == ['alpha']
    assert store.list() == store.list()


def test_latest_prefers_checkpoint_and_handles_cleared(tmp_path):
    store = SessionStore(tmp_path)
    assert store.latest() is None
    payload = _payload('old')
    payload.messages = [{'role': 'user', 'content': 'hi'}]
    store.save(payload, as_name='old')
    assert store.latest().name == 'old'
    # an empty checkpoint means cleared: no resurrection of older sessions
    store.save(_payload(LAST_SESSION), as_name=LAST_SESSION)
    assert store.latest() is None


def test_rewind_cuts_messages_and_items(tmp_path):
    payload = _payload()
    payload.messages = [
        {'role': 'user', 'content': 'first'},
        {'role': 'assistant', 'content': 'ok'},
        {'role': 'user', 'content': '<tool_images>\n[image: x]\n</tool_images>'},
        {'role': 'user', 'content': 'second'},
        {'role': 'assistant', 'content': 'done'},
    ]
    payload.items = [
        _item('user', 1, 'first'),
        _item('assistant', 1, 'ok'),
        _item('user', 2, 'second'),
        _item('assistant', 2, 'done'),
    ]
    starts = SessionStore.turn_starts(payload.messages)
    assert starts == [0, 3]    # the <tool_images> injection is not a turn
    rewound = SessionStore.rewind(payload, 2)
    assert rewound.messages[0]['content'] == 'first'
    # everything before turn 2's start is kept, including turn 1's injected
    # <tool_images> block (it belongs to turn 1's tail)
    assert len(rewound.messages) == 3
    assert rewound.messages[2]['content'].startswith('<tool_images>')
    assert [item.turn for item in rewound.items] == [1, 1]
    assert rewound.turn == 1


def test_legacy_payload_builds_items():
    raw = {
        'version': 1,
        'session': 'legacy',
        'history': [
            {'role': 'user', 'content': 'old question'},
            {'role': 'assistant', 'content': 'old answer'},
        ],
    }
    payload = SessionPayload.from_json(raw)
    assert payload.name == 'legacy'
    assert [item.kind for item in payload.items] == ['user', 'assistant']


# ── DbSessionStore (the sqlite route) ──────────────────────


def _db_store(tmp_path):
    return DbSessionStore(db_path=tmp_path / 'sessions' / 'agent.db')


def test_db_store_save_load_roundtrip(tmp_path):
    store = _db_store(tmp_path)
    payload = SessionPayload(name='s1', title='t', provider='P', model='m',
                             messages=[
                                 {'role': 'user', 'content': 'hi',
                                  'reasoning_content': 'th'},
                                 {'role': 'assistant', 'content': None,
                                  'tool_calls': [{'id': 'c1', 'type': 'function',
                                                  'function': {'name': 'edit',
                                                               'arguments': '{}'}}]},
                                 {'role': 'tool', 'tool_call_id': 'c1',
                                  'content': 'done'}],
                             items=[TranscriptItem(kind='user', turn=1, text='hi'),
                                    TranscriptItem(kind='tool', turn=1,
                                                   name='edit', call_id='c1')],
                             turn=1, prefix_generation=3,
                             compaction_archive=[{'role': 'user',
                                                  'content': 'old'}])
    store.save(payload)
    loaded = store.load('s1')
    assert loaded is not None
    assert loaded.name == 's1' and loaded.provider == 'P'
    assert loaded.turn == 1 and loaded.prefix_generation == 3
    assert loaded.messages[0]['reasoning_content'] == 'th'
    assert loaded.messages[1]['tool_calls'][0]['function']['name'] == 'edit'
    assert loaded.messages[2]['content'] == 'done'
    assert [item.kind for item in loaded.items] == ['user', 'tool']
    assert loaded.compaction_archive == [{'role': 'user', 'content': 'old'}]
    # a second save replaces the rows instead of appending
    payload.messages = payload.messages[:1]
    store.save(payload)
    assert len(store.load('s1').messages) == 1


def test_db_store_names_listing_and_delete(tmp_path):
    store = _db_store(tmp_path)
    store.save(SessionPayload(name='alpha', title='A', messages=[
        {'role': 'user', 'content': 'x'}]))
    assert store.unique_name('alpha') == 'alpha_2'
    assert store.unique_name('fresh') == 'fresh'
    rows = store.list()
    assert [row['name'] for row in rows] == ['alpha']
    assert rows[0]['messages'] == 1
    assert store.delete('alpha') is True
    assert store.delete('alpha') is False
    assert store.list() == []


def test_db_store_latest_checkpoint_semantics(tmp_path):
    store = _db_store(tmp_path)
    assert store.latest() is None
    store.save(SessionPayload(name='old', messages=[
        {'role': 'user', 'content': 'hi'}]), as_name='old')
    assert store.latest().name == 'old'
    store.save(SessionPayload(name=LAST_SESSION), as_name=LAST_SESSION)
    assert store.latest() is None, 'a cleared checkpoint must not resurrect'
    store.save(SessionPayload(name='next', messages=[
        {'role': 'user', 'content': 'hi'}]), as_name='next')
    store.save(SessionPayload(name='next', messages=[
        {'role': 'user', 'content': 'hi'}]), as_name=LAST_SESSION)
    assert store.latest().name == 'next'


def test_db_store_rewind_helpers_match_the_json_store(tmp_path):
    payload = SessionPayload(name='s', messages=[
        {'role': 'user', 'content': 'first'},
        {'role': 'assistant', 'content': 'ok'},
        {'role': 'user', 'content': 'second'},
    ])
    starts = DbSessionStore.turn_starts(payload.messages)
    assert starts == [0, 2]
    rewound = DbSessionStore.rewind(payload, 2)
    assert [m['content'] for m in rewound.messages] == ['first', 'ok']


def test_engine_persists_through_the_db_store(tmp_path):
    import asyncio

    from infra.orchestrator.stub import StubChatClient
    from harness.agent import ConversationEngine, EngineConfig, ModelInfo
    from harness.transcript import SessionStore

    from harness.tools.registry import ManagedToolRegistry

    client = StubChatClient(responses=[], model='stub')
    store = _db_store(tmp_path)
    engine = ConversationEngine(
        client=client, registry=ManagedToolRegistry(), store=store,
        cwd=str(tmp_path), model=ModelInfo(id='m', provider='p', wire='chat'),
        config=EngineConfig(), system_provider=lambda: 'sys')

    async def main():
        engine.start()
        engine.submit('hello there')

        async def poll():
            # a turn is done when it went busy at least once and is idle
            # again with content on the transcript
            while engine.busy() or not engine.items or \
                    engine.items[-1].kind not in ('assistant', 'notice'):
                await asyncio.sleep(0.01)
        await asyncio.wait_for(poll(), timeout=5)
        engine.save_active()
        await engine.shutdown()

    asyncio.run(main())
    # the session lives in the sqlite file, not in a json file
    assert (tmp_path / 'sessions' / 'agent.db').exists()
    rows = store.list()
    assert rows and rows[0]['messages'] >= 2
    loaded = store.load(rows[0]['name'])
    assert loaded.messages[0]['content'] == 'hello there'


def test_an_old_session_table_gains_the_own_name_column(tmp_path):
    """A database written before ``own_name`` must be migrated, not broken.

    Regression: the column was added to the CREATE TABLE script only, so an
    existing ``agent.db`` kept the old shape and every session save died with
    "table agent_sessions has no column named own_name" -- for anyone who had
    run an older build, no turn could be persisted at all.
    """
    import sqlite3

    db = tmp_path / 'sessions' / 'agent.db'
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE agent_sessions (
            name TEXT PRIMARY KEY,
            title TEXT DEFAULT '',
            created TEXT NOT NULL,
            updated TEXT NOT NULL,
            provider TEXT DEFAULT '',
            model TEXT DEFAULT '',
            turn INTEGER DEFAULT 0,
            prefix_generation INTEGER DEFAULT 1,
            compaction_archive TEXT DEFAULT '[]'
        );
        """
    )
    conn.commit()
    conn.close()

    store = DbSessionStore(db_path=db)      # this used to leave the table as is

    conn = sqlite3.connect(db)
    columns = {row[1] for row in conn.execute('PRAGMA table_info(agent_sessions)')}
    conn.close()
    assert 'own_name' in columns

    payload = _payload(name='s_old')
    payload.messages = [{'role': 'user', 'content': 'hi'}]
    store.save(payload)                     # used to raise OperationalError
    assert store.load('s_old').messages[0]['content'] == 'hi'
