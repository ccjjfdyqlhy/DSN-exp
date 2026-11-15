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


def group_turns(items: Iterable[TranscriptItem]) -> list[tuple[int, TranscriptItem]]:
    """Return (turn, item) rows in order; notices with turn 0 stay at the top."""
    return [(item.turn, item) for item in items]


def new_session_name() -> str:
    return time.strftime('%Y%m%d_%H%M%S')
