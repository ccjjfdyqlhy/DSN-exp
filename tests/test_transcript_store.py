# tests/test_transcript_store.py
# Session persistence: JSON payloads, transcript items, rewind and the
# rolling checkpoint.

from __future__ import annotations

from harness.transcript import (
    LAST_SESSION, SESSION_VERSION, SessionPayload, SessionStore,
    TranscriptItem, new_session_name,
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
