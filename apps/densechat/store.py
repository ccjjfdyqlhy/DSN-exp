# store.py — 全局工作区会话存储。
#
# 所有会话统一持久化到 ~/.densechat/densechat.db，并按 workspace 分组。
# 兼容 harness SessionStore 的主要接口，同时增加 workspace 维度。

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from harness.models.base import ChatMessage
from harness.store import Migration, MigrationRunner
from harness.store.sqlite import SqliteStore

from .profiles import DEFAULT_PROFILE

_MIGRATIONS = [
    Migration("001_workspaces", lambda c: c.executescript(
        """
        CREATE TABLE IF NOT EXISTS workspaces (
            id TEXT PRIMARY KEY,
            path TEXT UNIQUE NOT NULL,
            name TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            workspace_id TEXT,
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
        CREATE INDEX IF NOT EXISTS idx_sessions_workspace ON sessions(workspace_id);
        """
    )),
    # 任务模式（TaskProfile）：每个会话绑定一个任务模式（dekacode/random/anaii）
    Migration("002_session_profile", lambda c: c.execute(
        "ALTER TABLE sessions ADD COLUMN profile TEXT DEFAULT 'dekacode'"
    )),
    # 多用户：会话归属（NULL = 匿名/旧数据，对所有用户可见）
    Migration("003_session_user", lambda c: c.execute(
        "ALTER TABLE sessions ADD COLUMN user_id TEXT"
    )),
    Migration("004_message_reasoning", lambda c: c.execute(
        "ALTER TABLE messages ADD COLUMN reasoning_content TEXT"
    )),
]


def _now() -> str:
    return datetime.now().isoformat()


class CentralSessionStore:
    def __init__(self, db_path: str = ""):
        if not db_path:
            db_path = str(Path.home() / ".densechat" / "densechat.db")
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.store = SqliteStore(db_path)
        MigrationRunner(self.store).migrate(_MIGRATIONS)
        self._session_id: Optional[str] = None

    # ── Workspaces ──

    def ensure_workspace(self, path: str) -> str:
        p = str(Path(path).resolve())
        rows = self.store.execute("SELECT id FROM workspaces WHERE path = ?", (p,))
        if rows:
            return rows[0]["id"]
        wid = "ws_" + datetime.now().strftime("%Y%m%d_%H%M%S%f")
        self.store.execute(
            "INSERT INTO workspaces (id, path, name, created_at) VALUES (?, ?, ?, ?)",
            (wid, p, Path(p).name, _now()))
        return wid

    def list_workspaces(self) -> list[dict]:
        rows = self.store.execute(
            "SELECT w.*, COUNT(s.id) AS session_count"
            " FROM workspaces w LEFT JOIN sessions s ON s.workspace_id = w.id"
            " GROUP BY w.id ORDER BY w.created_at DESC"
        )
        return [dict(r) for r in rows]

    # ── Session current pointer ──

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    def create_session(self, workspace_id: Optional[str] = None,
                       profile: Optional[str] = None,
                       user_id: Optional[str] = None) -> str:
        sid = datetime.now().strftime("%Y%m%d_%H%M%S%f")
        now = _now()
        profile = profile or DEFAULT_PROFILE
        self.store.execute(
            "INSERT OR IGNORE INTO sessions (id, workspace_id, profile, user_id, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (sid, workspace_id, profile, user_id, now, now))
        self._session_id = sid
        return sid

    def ensure_session(self, session_id: str, profile: Optional[str] = None,
                       workspace_id: Optional[str] = None,
                       user_id: Optional[str] = None) -> str:
        """按指定 id 幂等创建会话（群聊房间持久化等固定 id 场景）。"""
        now = _now()
        self.store.execute(
            "INSERT OR IGNORE INTO sessions (id, workspace_id, profile, user_id, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, workspace_id, profile or DEFAULT_PROFILE, user_id, now, now))
        self._session_id = session_id
        return session_id

    def set_session(self, session_id: str) -> bool:
        rows = self.store.execute("SELECT id FROM sessions WHERE id = ?", (session_id,))
        if rows:
            self._session_id = session_id
            return True
        return False

    def list_sessions(self, limit: int = 200, workspace_id: Optional[str] = None,
                      user_id: Optional[str] = None) -> list[dict]:
        sql = (
            "SELECT s.id, s.workspace_id, s.created_at, s.updated_at, s.summary, s.mode,"
            " s.profile AS profile, s.user_id AS user_id,"
            " w.path AS workspace_path,"
            " COALESCE(m.cnt, 0) AS message_count,"
            " COALESCE(u.cost, 0) AS total_cost, COALESCE(u.tok, 0) AS total_input"
            " FROM sessions s"
            " LEFT JOIN workspaces w ON s.workspace_id = w.id"
            " LEFT JOIN (SELECT session_id, COUNT(*) cnt FROM messages GROUP BY session_id) m"
            "  ON s.id = m.session_id"
            " LEFT JOIN (SELECT session_id, SUM(cost) cost, SUM(input_tokens) tok"
            "            FROM turn_usage GROUP BY session_id) u ON s.id = u.session_id"
        )
        conds: list[str] = []
        params: list = []
        if workspace_id:
            conds.append("s.workspace_id = ?")
            params.append(workspace_id)
        # 用户过滤：已登录用户只看自己的会话；匿名/NULL（旧数据）对所有人生效
        if user_id and user_id != "anon":
            conds.append("(s.user_id = ? OR s.user_id IS NULL)")
            params.append(user_id)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY s.updated_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.store.execute(sql, params)]

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

    def get_profile(self, session_id: Optional[str] = None) -> Optional[str]:
        sid = session_id or self._session_id
        if not sid:
            return None
        rows = self.store.execute("SELECT profile FROM sessions WHERE id = ?", (sid,))
        return rows[0]["profile"] or DEFAULT_PROFILE if rows else None

    def set_profile(self, profile: str, session_id: Optional[str] = None) -> None:
        sid = session_id or self._session_id
        if sid:
            self.store.execute("UPDATE sessions SET profile = ? WHERE id = ?", (profile, sid))

    def update_summary(self, summary: str, session_id: Optional[str] = None) -> None:
        sid = session_id or self._session_id
        if sid:
            self.store.execute("UPDATE sessions SET summary = ? WHERE id = ?",
                               (summary[:200], sid))

    def update_workspace(self, workspace_id: str, session_id: Optional[str] = None) -> None:
        sid = session_id or self._session_id
        if sid:
            self.store.execute("UPDATE sessions SET workspace_id = ? WHERE id = ?",
                               (workspace_id, sid))

    def get_session_workspace(self, session_id: str) -> Optional[str]:
        rows = self.store.execute("SELECT workspace_id FROM sessions WHERE id = ?", (session_id,))
        return rows[0]["workspace_id"] if rows else None

    def get_session_user(self, session_id: str) -> Optional[str]:
        """会话归属用户；None = 匿名/旧数据（不限制访问）。"""
        rows = self.store.execute("SELECT user_id FROM sessions WHERE id = ?", (session_id,))
        return rows[0]["user_id"] if rows else None

    def get_workspace_path(self, workspace_id: str) -> Optional[str]:
        rows = self.store.execute("SELECT path FROM workspaces WHERE id = ?", (workspace_id,))
        return rows[0]["path"] if rows else None

    def delete_session(self, session_id: str) -> None:
        self.store.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        self.store.execute("DELETE FROM turn_usage WHERE session_id = ?", (session_id,))
        self.store.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    # ── Messages ──

    def save_messages(self, messages: list[ChatMessage], session_id: Optional[str] = None) -> None:
        sid = session_id or self._session_id
        if not sid or not messages:
            return
        now = _now()
        self.store.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, sid))
        self.store.execute_many(
                        "INSERT INTO messages (session_id, role, content, tool_calls, tool_call_id, name,"
                        " reasoning_content, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(sid, m.role, m.content,
              json.dumps(m.tool_calls, ensure_ascii=False) if m.tool_calls else None,
                            m.tool_call_id, m.name, m.reasoning_content, now) for m in messages])

    def load_messages(self, session_id: Optional[str] = None) -> list[ChatMessage]:
        sid = session_id or self._session_id
        if not sid:
            return []
        rows = self.store.execute(
            "SELECT role, content, tool_calls, tool_call_id, name, reasoning_content FROM messages"
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
                                    name=r["name"], reasoning_content=r["reasoning_content"]))
        return msgs

    # ── Usage ──

    def save_usage(self, turn: int, *, tier: str = "", input_tokens: int = 0,
                   output_tokens: int = 0, cache_hit_input: int = 0,
                   cost: float = 0.0, session_id: Optional[str] = None) -> None:
        sid = session_id or self._session_id
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
