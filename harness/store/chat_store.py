# harness/store/chat_store.py
# SessionStore — 会话持久化（sessions / messages / turn_usage / 压缩块）。
#
# 基于 harness SqliteStore + MigrationRunner，通用与具体会话语义无关。

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Optional

from ..models.base import ChatMessage
from .base import Migration, MigrationRunner
from .sqlite import SqliteStore

_MIGRATIONS = [
    Migration("001_sessions", lambda c: c.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            summary TEXT DEFAULT '',
            mode TEXT DEFAULT 'agent'
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            tool_calls TEXT,
            tool_call_id TEXT,
            name TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
        CREATE TABLE IF NOT EXISTS turn_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            turn INTEGER NOT NULL,
            tier TEXT,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            cache_hit_input INTEGER DEFAULT 0,
            cost REAL DEFAULT 0.0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS compressed_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            messages TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_compressed_session ON compressed_chunks(session_id, chunk_index);
        """
    )),
]


def _now() -> str:
    return datetime.now().isoformat()


class SessionStore:
    """SQLite 会话存储。"""

    def __init__(self, store: Optional[SqliteStore] = None, *, db_path: str = ":memory:"):
        self.store = store or SqliteStore(db_path)
        MigrationRunner(self.store).migrate(_MIGRATIONS)
        self._session_id: Optional[str] = None

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    def create_session(self) -> str:
        sid = datetime.now().strftime("%Y%m%d_%H%M%S%f")
        now = _now()
        self.store.execute(
            "INSERT OR IGNORE INTO sessions (id, created_at, updated_at) VALUES (?, ?, ?)",
            (sid, now, now))
        self._session_id = sid
        return sid

    def set_session(self, session_id: str) -> bool:
        rows = self.store.execute("SELECT id FROM sessions WHERE id = ?", (session_id,))
        if rows:
            self._session_id = session_id
            return True
        return False

    def list_sessions(self, limit: int = 20) -> list[dict]:
        rows = self.store.execute(
            "SELECT s.id, s.created_at, s.updated_at, s.summary, s.mode,"
            " COALESCE(m.cnt, 0) AS message_count,"
            " COALESCE(u.cost, 0) AS total_cost, COALESCE(u.tok, 0) AS total_input"
            " FROM sessions s"
            " LEFT JOIN (SELECT session_id, COUNT(*) cnt FROM messages GROUP BY session_id) m"
            "  ON s.id = m.session_id"
            " LEFT JOIN (SELECT session_id, SUM(cost) cost, SUM(input_tokens) tok"
            "            FROM turn_usage GROUP BY session_id) u ON s.id = u.session_id"
            " ORDER BY s.updated_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def get_mode(self, session_id: Optional[str] = None) -> Optional[str]:
        sid = session_id or self._session_id
        if not sid:
            return None
        rows = self.store.execute("SELECT mode FROM sessions WHERE id = ?", (sid,))
        return rows[0]["mode"] if rows else None

    def set_mode(self, mode: str, session_id: Optional[str] = None) -> None:
        sid = session_id or self._session_id
        if sid:
            self.store.execute("UPDATE sessions SET mode = ? WHERE id = ?", (mode, sid))

    def save_messages(self, messages: list[ChatMessage]) -> None:
        sid = self._session_id
        if not sid or not messages:
            return
        now = _now()
        self.store.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, sid))
        self.store.execute_many(
            "INSERT INTO messages (session_id, role, content, tool_calls, tool_call_id, name, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(sid, m.role, m.content,
              json.dumps(m.tool_calls, ensure_ascii=False) if m.tool_calls else None,
              m.tool_call_id, m.name, now) for m in messages])

    def load_messages(self, session_id: Optional[str] = None) -> list[ChatMessage]:
        sid = session_id or self._session_id
        if not sid:
            return []
        rows = self.store.execute(
            "SELECT role, content, tool_calls, tool_call_id, name FROM messages"
            " WHERE session_id = ? ORDER BY id", (sid,))
        msgs = []
        for r in rows:
            tool_calls = None
            if r["tool_calls"]:
                try:
                    tool_calls = json.loads(r["tool_calls"])
                except (TypeError, ValueError):
                    tool_calls = None
            msgs.append(ChatMessage(role=r["role"], content=r["content"] or "",
                                    tool_calls=tool_calls, tool_call_id=r["tool_call_id"],
                                    name=r["name"]))
        return msgs

    def save_usage(self, turn: int, *, tier: str = "", input_tokens: int = 0,
                   output_tokens: int = 0, cache_hit_input: int = 0,
                   cost: float = 0.0) -> None:
        sid = self._session_id
        if not sid:
            return
        self.store.execute(
            "INSERT INTO turn_usage (session_id, turn, tier, input_tokens, output_tokens,"
            " cache_hit_input, cost, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, turn, tier, input_tokens, output_tokens, cache_hit_input, cost, _now()))

    def load_usage(self, session_id: Optional[str] = None) -> list[dict]:
        sid = session_id or self._session_id
        if not sid:
            return []
        return [dict(r) for r in self.store.execute(
            "SELECT turn, tier, input_tokens, output_tokens, cache_hit_input, cost"
            " FROM turn_usage WHERE session_id = ? ORDER BY turn", (sid,))]

    def save_compressed_chunk(self, messages: list[ChatMessage],
                              session_id: Optional[str] = None) -> None:
        sid = session_id or self._session_id
        if not sid or not messages:
            return
        rows = self.store.execute(
            "SELECT COALESCE(MAX(chunk_index), -1) FROM compressed_chunks WHERE session_id = ?",
            (sid,))
        idx = (rows[0][0] if rows else -1) + 1
        data = [{"role": m.role, "content": m.content, "tool_calls": m.tool_calls,
                 "tool_call_id": m.tool_call_id} for m in messages]
        self.store.execute(
            "INSERT INTO compressed_chunks (session_id, chunk_index, messages, created_at)"
            " VALUES (?, ?, ?, ?)", (sid, idx, json.dumps(data, ensure_ascii=False), _now()))

    def load_compressed_chunks(self, session_id: Optional[str] = None) -> list[list[ChatMessage]]:
        sid = session_id or self._session_id
        if not sid:
            return []
        chunks = []
        for r in self.store.execute(
                "SELECT messages FROM compressed_chunks WHERE session_id = ? ORDER BY chunk_index",
                (sid,)):
            raw = json.loads(r["messages"])
            chunks.append([ChatMessage(**{k: v for k, v in m.items() if v is not None})
                           for m in raw])
        return chunks

    def update_summary(self, summary: str, session_id: Optional[str] = None) -> None:
        sid = session_id or self._session_id
        if sid:
            self.store.execute("UPDATE sessions SET summary = ? WHERE id = ?",
                               (summary[:200], sid))
