# harness/transcript.py
# Session persistence: transcript items, JSON payloads, rewind and fork.
#
# A transcript is the UI's model of a conversation; the LLM history itself
# lives in the conversation state and stays provider-shaped.  Payloads are
# atomic JSON files under a sessions directory, with a rolling checkpoint
# name for resume.

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from aicf.infra.store.base import Migration, MigrationRunner
from aicf.infra.store.sqlite import SqliteStore
from typing import Any, Iterable

SESSION_VERSION = 2
LAST_SESSION = '__last__'
# A goal store may share the sessions directory; these files are not sessions.
RESERVED_SESSION_NAMES = {LAST_SESSION, 'goals'}
_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_DEVICES = {
    'con', 'prn', 'aux', 'nul',
    *(f'com{index}' for index in range(1, 10)),
    *(f'lpt{index}' for index in range(1, 10)),
}

# user message prefixes injected by the engine; they never start a transcript turn
_INJECTED_PREFIXES = ('<conversation_summary>', '<subagent_updates>',
                      '<agent_mailbox>', '<tool_')


@dataclass
class TranscriptItem:
    """One visual block in the conversation transcript.

    The transcript is the UI's model of the conversation.  ``turn`` links every
    item back to the user message that started it, which is what rewind, fork
    and edit operate on.  The LLM history itself is stored separately in the
    conversation context so tool-call payloads stay provider-shaped.
    """

    kind: str                       # user | assistant | thinking | tool | notice |
                                    # aside | compaction | agent
    turn: int = 0
    text: str = ''
    call_id: str = ''
    name: str = ''
    display: str = ''
    args: dict[str, Any] = field(default_factory=dict)
    status: str = ''
    output: str = ''
    diff: dict[str, Any] | None = None
    duration: float = 0.0
    level: str = 'info'
    agent: str = ''
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> 'TranscriptItem | None':
        if not isinstance(raw, dict) or not raw.get('kind'):
            return None
        known = {field_name for field_name in cls.__dataclass_fields__}
        payload = {key: value for key, value in raw.items() if key in known}
        try:
            return cls(**payload)
        except TypeError:
            return None


@dataclass
class SessionPayload:
    name: str = ''
    title: str = ''
    created: str = ''
    updated: str = ''
    provider: str = ''
    model: str = ''
    turn: int = 0
    prefix_generation: int = 1
    messages: list[dict[str, Any]] = field(default_factory=list)
    compaction_archive: list[dict[str, Any]] = field(default_factory=list)
    items: list[TranscriptItem] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            'version': SESSION_VERSION,
            'name': self.name,
            'title': self.title,
            'created': self.created,
            'updated': self.updated,
            'provider': self.provider,
            'model': self.model,
            'turn': self.turn,
            'prefix_generation': self.prefix_generation,
            'messages': self.messages,
            'compaction_archive': self.compaction_archive,
            'items': [item.to_dict() for item in self.items],
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> 'SessionPayload':
        if not isinstance(raw, dict):
            raw = {}
        items: list[TranscriptItem] = []
        raw_items = raw.get('items')
        if isinstance(raw_items, list):
            for raw_item in raw_items:
                item = TranscriptItem.from_dict(raw_item)
                if item is not None:
                    items.append(item)
        raw_messages = raw.get('messages') or raw.get('history') or []
        if isinstance(raw_messages, dict):
            raw_messages = [raw_messages]
        if not isinstance(raw_messages, list):
            raw_messages = []
        # A message without a role cannot be sent to any provider.
        messages = [dict(message) for message in raw_messages
                    if isinstance(message, dict) and message.get('role')]
        if not items and messages:
            items = _items_from_legacy_messages(messages)
        raw_archive = raw.get('compaction_archive')
        archive = ([dict(message) for message in raw_archive
                    if isinstance(message, dict)]
                   if isinstance(raw_archive, list) else [])
        return cls(
            name=str(raw.get('name') or raw.get('session') or ''),
            title=str(raw.get('title') or ''),
            created=str(raw.get('created') or ''),
            updated=str(raw.get('updated') or ''),
            provider=str(raw.get('provider') or ''),
            model=str(raw.get('model') or ''),
            turn=_safe_int(raw.get('turn'), 0),
            prefix_generation=max(1, _safe_int(raw.get('prefix_generation'), 1)),
            messages=messages,
            compaction_archive=archive,
            items=items,
        )


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _items_from_legacy_messages(messages: list[dict[str, Any]]) -> list[TranscriptItem]:
    """Build a transcript for a session written by a 1.x engine."""
    items: list[TranscriptItem] = []
    turn = 0
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get('role')
        content = message.get('content')
        text = content if isinstance(content, str) else ''
        if role == 'user':
            if text.startswith(('<conversation_summary>', '<subagent_updates>',
                                '<agent_mailbox>')):
                continue
            turn += 1
            items.append(TranscriptItem(kind='user', turn=turn, text=text))
        elif role == 'assistant':
            reasoning = message.get('reasoning_content') or ''
            if reasoning:
                items.append(TranscriptItem(kind='thinking', turn=turn,
                                            text=str(reasoning)))
            calls = message.get('tool_calls') or []
            if isinstance(calls, dict):
                calls = [calls]
            for call in calls if isinstance(calls, list) else []:
                if not isinstance(call, dict):
                    continue
                function = call.get('function')
                if not isinstance(function, dict):
                    function = {}
                items.append(TranscriptItem(
                    kind='tool', turn=turn, name=str(function.get('name', '')),
                    display=str(function.get('name', '')), status='done'))
            if text:
                items.append(TranscriptItem(kind='assistant', turn=turn, text=text))
    return items


class SessionStore:
    """Atomic JSON persistence under ``sessions/``."""

    def __init__(self, directory: str | os.PathLike[str] = 'sessions') -> None:
        self.directory = Path(directory)
        self._lock = threading.Lock()

    def path_for(self, name: str) -> Path:
        safe = name.strip()
        safe = _INVALID_FILENAME.sub('_', safe).strip(' .')
        safe = safe[:100] or 'session'
        if safe.lower() in _RESERVED_DEVICES:
            safe = f'_{safe}'
        return self.directory / f'{safe}.json'

    def unique_name(self, base: str) -> str:
        """Return a session name whose file does not exist yet."""
        stem = base.strip() or new_session_name()
        candidate = stem
        index = 2
        while self.path_for(candidate).exists():
            candidate = f'{stem}_{index}'
            index += 1
        return candidate

    def save(self, payload: SessionPayload, as_name: str | None = None) -> None:
        name = (as_name if as_name is not None else payload.name).strip()
        if not name:
            raise ValueError('session name must not be empty')
        payload.updated = time.strftime('%Y-%m-%d %H:%M')
        if not payload.created:
            payload.created = payload.updated
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.path_for(name)
            fd, temp_name = tempfile.mkstemp(
                prefix=f'.{path.name}.', suffix='.tmp', dir=str(self.directory))
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    json.dump(payload.to_json(), stream, ensure_ascii=False, indent=2)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp_name, path)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)

    def load(self, name: str) -> SessionPayload | None:
        path = self.path_for(name)
        try:
            raw = json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            return None
        if not isinstance(raw, dict):
            return None
        try:
            payload = SessionPayload.from_json(raw)
        except (TypeError, ValueError):
            return None
        if not payload.name:
            payload.name = name
        return payload

    def delete(self, name: str) -> bool:
        try:
            self.path_for(name).unlink()
            return True
        except OSError:
            return False

    def list(self) -> list[dict[str, Any]]:
        if not self.directory.is_dir():
            return []
        rows: list[dict[str, Any]] = []
        for path in self.directory.glob('*.json'):
            name = path.stem
            if name in RESERVED_SESSION_NAMES:
                continue
            try:
                raw = json.loads(path.read_text(encoding='utf-8-sig'))
            except (OSError, ValueError):
                continue
            if not isinstance(raw, dict):
                continue
            if not any(key in raw for key in ('messages', 'history', 'items')):
                # Not a session payload (for example goals.json).
                continue
            messages = raw.get('messages')
            rows.append({
                'name': name,
                'title': str(raw.get('title') or name),
                'created': str(raw.get('created') or ''),
                'updated': str(raw.get('updated') or ''),
                'messages': len(messages) if isinstance(messages, list) else 0,
            })
        rows.sort(key=lambda row: (row['updated'], row['created']), reverse=True)
        return rows

    def latest(self) -> SessionPayload | None:
        checkpoint = self.path_for(LAST_SESSION)
        if checkpoint.exists():
            payload = self.load(LAST_SESSION)
            # An explicitly cleared checkpoint must not fall through to an old
            # named session and resurrect the cleared conversation, and neither
            # must a corrupt one.
            if payload is None:
                return None
            return payload if payload.messages else None
        rows = self.list()
        if not rows:
            return None
        return self.load(rows[0]['name'])

    # ── rewind / fork helpers ───────────────────────────────
    @staticmethod
    def turn_starts(messages: Iterable[dict[str, Any]]) -> list[int]:
        """Indices of user messages that begin a turn (ignoring injected blocks)."""
        starts: list[int] = []
        for index, message in enumerate(messages):
            if message.get('role') != 'user':
                continue
            content = message.get('content')
            if not isinstance(content, str):
                content = str(content)
            if content.startswith(_INJECTED_PREFIXES):
                continue
            starts.append(index)
        return starts

    @classmethod
    def rewind(cls, payload: SessionPayload, turn: int,
               edit_text: str | None = None) -> SessionPayload:
        """Drop every item and message from ``turn`` onwards.

        ``turn`` is the 1-based transcript turn id.  When ``edit_text`` is given
        the caller re-submits the edited text as a fresh turn.
        """
        starts = cls.turn_starts(payload.messages)
        if 1 <= turn <= len(starts):
            cut = starts[turn - 1]
        else:
            cut = len(payload.messages)
        payload.messages = payload.messages[:cut]
        payload.items = [item for item in payload.items if item.turn < turn]
        payload.turn = max(0, turn - 1)
        return payload



def _add_own_name(conn: Any) -> None:
    """Give pre-existing session tables the ``own_name`` column.

    The column is part of the create script, so a fresh database already
    has it and only a database written by an older build needs the ALTER
    -- hence the guard: a bare ``ALTER TABLE ... ADD COLUMN`` would fail
    on every new install and take the whole migration run with it.
    """
    columns = {row[1] for row in conn.execute('PRAGMA table_info(agent_sessions)')}
    if 'own_name' not in columns:
        conn.execute(
            "ALTER TABLE agent_sessions ADD COLUMN own_name TEXT DEFAULT ''")


_DB_MIGRATIONS = [
    Migration('harness-001-agent-sessions', lambda c: c.executescript(
        """
        CREATE TABLE IF NOT EXISTS agent_sessions (
            name TEXT PRIMARY KEY,
            title TEXT DEFAULT '',
            created TEXT NOT NULL,
            updated TEXT NOT NULL,
            provider TEXT DEFAULT '',
            model TEXT DEFAULT '',
            turn INTEGER DEFAULT 0,
            prefix_generation INTEGER DEFAULT 1,
            compaction_archive TEXT DEFAULT '[]',
            own_name TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS agent_messages (
            session_name TEXT NOT NULL,
            seq INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            tool_calls TEXT,
            tool_call_id TEXT,
            reasoning_content TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_agent_messages_session
            ON agent_messages(session_name, seq);
        CREATE TABLE IF NOT EXISTS agent_items (
            session_name TEXT NOT NULL,
            seq INTEGER NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_agent_items_session
            ON agent_items(session_name, seq);
        """
    )),
    Migration('harness-002-agent-sessions-own-name', _add_own_name),
]



class DbSessionStore:
    """SQLite-backed session store: the same duck type as SessionStore.

    The conversation thread (messages) lives in rows, so it stays queryable
    and survives without any session JSON file; the UI transcript items and
    the compaction archive ride on the session row as JSON documents (the
    same shape the infra chat_store uses for its compressed chunks).  The
    engine accepts either store - this one is the default.

    Args:
        store: an existing infra.store SqliteStore to share; one is created
            at ``db_path`` when omitted (parent directories are made).
        db_path: database file, used only when ``store`` is omitted.
    """

    def __init__(self, store: Any = None, *,
                 db_path: str | os.PathLike[str] = 'sessions/agent.db') -> None:
        self.db_path = str(db_path)
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self.store = store or SqliteStore(self.db_path)
        MigrationRunner(self.store).migrate(_DB_MIGRATIONS)
        self._lock = threading.Lock()

    def _now(self) -> str:
        return time.strftime('%Y-%m-%d %H:%M')

    def _row_exists(self, name: str) -> bool:
        return bool(self.store.execute(
            'SELECT name FROM agent_sessions WHERE name = ?', (name,)))

    def save(self, payload: SessionPayload, as_name: str | None = None) -> None:
        name = (as_name if as_name is not None else payload.name).strip()
        if not name:
            raise ValueError('session name must not be empty')
        updated = self._now()
        created = updated
        if self._row_exists(name):
            row = self.store.execute(
                'SELECT created FROM agent_sessions WHERE name = ?', (name,))
            created = row[0]['created'] or updated
        with self._lock:
            self.store.execute(
                'INSERT INTO agent_sessions (name, title, created, updated,'
                ' provider, model, turn, prefix_generation, compaction_archive,'
                ' own_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'
                ' ON CONFLICT(name) DO UPDATE SET title=excluded.title,'
                ' updated=excluded.updated, provider=excluded.provider,'
                ' model=excluded.model, turn=excluded.turn,'
                ' prefix_generation=excluded.prefix_generation,'
                ' compaction_archive=excluded.compaction_archive,'
                ' own_name=excluded.own_name',
                (name, payload.title, created, updated, payload.provider,
                 payload.model, payload.turn, payload.prefix_generation,
                 json.dumps(payload.compaction_archive, ensure_ascii=False),
                 payload.name))
            self.store.execute('DELETE FROM agent_messages WHERE session_name = ?',
                               (name,))
            self.store.execute('DELETE FROM agent_items WHERE session_name = ?',
                               (name,))
            rows = []
            for seq, message in enumerate(payload.messages):
                rows.append((name, seq, str(message.get('role', 'user')),
                             message.get('content')
                             if isinstance(message.get('content'), str) else None,
                             json.dumps(message.get('tool_calls') or [],
                                        ensure_ascii=False)
                             if message.get('tool_calls') else None,
                             message.get('tool_call_id'),
                             message.get('reasoning_content')))
            if rows:
                self.store.execute_many(
                    'INSERT INTO agent_messages (session_name, seq, role,'
                    ' content, tool_calls, tool_call_id, reasoning_content)'
                    ' VALUES (?, ?, ?, ?, ?, ?, ?)', rows)
            item_rows = [(name, seq,
                          json.dumps(item.to_dict(), ensure_ascii=False))
                         for seq, item in enumerate(payload.items)]
            if item_rows:
                self.store.execute_many(
                    'INSERT INTO agent_items (session_name, seq, payload)'
                    ' VALUES (?, ?, ?)', item_rows)

    def load(self, name: str) -> SessionPayload | None:
        rows = self.store.execute(
            'SELECT name, own_name, title, created, updated, provider, model,'
            ' turn, prefix_generation, compaction_archive FROM agent_sessions'
            ' WHERE name = ?', (name,))
        if not rows:
            return None
        row = rows[0]
        messages = [dict(m) for m in self.store.execute(
            'SELECT role, content, tool_calls, tool_call_id,'
            ' reasoning_content FROM agent_messages'
            ' WHERE session_name = ? ORDER BY seq', (name,))]
        out: list[dict[str, Any]] = []
        for message in messages:
            entry: dict[str, Any] = {'role': message['role'],
                                     'content': message['content'] or ''}
            if message['tool_calls']:
                try:
                    entry['tool_calls'] = json.loads(message['tool_calls'])
                except ValueError:
                    pass
            if message['tool_call_id']:
                entry['tool_call_id'] = message['tool_call_id']
            if message['reasoning_content']:
                entry['reasoning_content'] = message['reasoning_content']
            out.append(entry)
        items = []
        for record in self.store.execute(
                'SELECT payload FROM agent_items WHERE session_name = ?'
                ' ORDER BY seq', (name,)):
            item = TranscriptItem.from_dict(json.loads(record['payload']))
            if item is not None:
                items.append(item)
        try:
            archive = json.loads(row['compaction_archive'] or '[]')
        except ValueError:
            archive = []
        payload = SessionPayload(
            # the checkpoint row is keyed __last__ but the payload keeps the
            # session's own name, like the json store
            name=str(row['own_name'] or row['name']),
            title=str(row['title'] or ''),
            created=str(row['created'] or ''),
            updated=str(row['updated'] or ''),
            provider=str(row['provider'] or ''),
            model=str(row['model'] or ''),
            turn=_safe_int(row['turn'], 0),
            prefix_generation=max(1, _safe_int(row['prefix_generation'], 1)),
            messages=out,
            compaction_archive=archive,
            items=items,
        )
        return payload

    def delete(self, name: str) -> bool:
        if not self._row_exists(name):
            return False
        with self._lock:
            self.store.execute('DELETE FROM agent_sessions WHERE name = ?', (name,))
            self.store.execute('DELETE FROM agent_messages WHERE session_name = ?',
                               (name,))
            self.store.execute('DELETE FROM agent_items WHERE session_name = ?',
                               (name,))
        return True

    def list(self) -> list[dict[str, Any]]:
        rows = [dict(row) for row in self.store.execute(
            'SELECT s.name, s.title, s.created, s.updated,'
            ' COALESCE(m.cnt, 0) AS messages FROM agent_sessions s'
            ' LEFT JOIN (SELECT session_name, COUNT(*) cnt FROM agent_messages'
            '  GROUP BY session_name) m ON s.name = m.session_name'
            ' ORDER BY s.updated DESC, s.created DESC')]
        return [row for row in rows
                if row['name'] not in RESERVED_SESSION_NAMES]

    def latest(self) -> SessionPayload | None:
        checkpoint = self.load(LAST_SESSION)
        if checkpoint is not None:
            # an explicitly cleared checkpoint must not resurrect an older
            # session, mirroring the json store
            return checkpoint if checkpoint.messages else None
        rows = self.list()
        if not rows:
            return None
        return self.load(rows[0]['name'])

    def unique_name(self, base: str) -> str:
        stem = base.strip() or new_session_name()
        candidate = stem
        index = 2
        while self._row_exists(candidate):
            candidate = f'{stem}_{index}'
            index += 1
        return candidate

    @staticmethod
    def turn_starts(messages: Iterable[dict[str, Any]]) -> list[int]:
        return SessionStore.turn_starts(messages)

    @classmethod
    def rewind(cls, payload: SessionPayload, turn: int,
               edit_text: str | None = None) -> SessionPayload:
        return SessionStore.rewind(payload, turn, edit_text)


def group_turns(items: Iterable[TranscriptItem]) -> list[tuple[int, TranscriptItem]]:
    """Return (turn, item) rows in order; notices with turn 0 stay at the top."""
    return [(item.turn, item) for item in items]


def new_session_name() -> str:
    return time.strftime('%Y%m%d_%H%M%S')
