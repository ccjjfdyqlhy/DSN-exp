# scripts/state.py
# ScriptState — 剧本状态持久化 CRUD

from __future__ import annotations

import json
import logging
import sqlite3

logger = logging.getLogger("ScriptState")

SCRIPT_STATE_TABLE = """
CREATE TABLE IF NOT EXISTS script_state (
    uid INTEGER PRIMARY KEY,
    active_script TEXT NOT NULL DEFAULT '',
    active_chapter TEXT NOT NULL DEFAULT '',
    chapter_scores TEXT NOT NULL DEFAULT '{}',
    flags TEXT NOT NULL DEFAULT '{}',
    turn_count INTEGER DEFAULT 0,
    started_at TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
)
"""

SCRIPT_RECORDINGS_TABLE = """
CREATE TABLE IF NOT EXISTS script_recordings (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    script_id TEXT NOT NULL,
    chapter_id TEXT NOT NULL,
    key_points_met TEXT NOT NULL,
    user_input TEXT NOT NULL,
    ai_reply TEXT NOT NULL,
    tool_calls TEXT,
    context_fingerprint TEXT NOT NULL,
    replay_mode TEXT NOT NULL DEFAULT 'exact',
    hit_count INTEGER DEFAULT 0,
    is_valid INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    invalidated_at TEXT
)
"""


class ScriptState:
    def __init__(self, db):
        self._db = db
        self._init_tables()

    def _init_tables(self):
        conn = self._db._get_connection()
        try:
            conn.execute(SCRIPT_STATE_TABLE)
            conn.execute(SCRIPT_RECORDINGS_TABLE)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_recordings_lookup "
                "ON script_recordings(user_id, script_id, chapter_id, is_valid)"
            )
            conn.commit()
            logger.info("剧本状态表初始化完成")
        except sqlite3.Error as e:
            logger.error("初始化剧本状态表失败: %s", e)
            conn.rollback()

    def load(self, uid: int) -> dict | None:
        conn = self._db._get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM script_state WHERE uid = ?", (uid,)
            ).fetchone()
            if not row:
                return None
            return {
                "uid": row["uid"],
                "active_script": row["active_script"],
                "active_chapter": row["active_chapter"],
                "chapter_scores": json.loads(row["chapter_scores"]),
                "flags": json.loads(row["flags"]),
                "turn_count": row["turn_count"],
                "started_at": row["started_at"],
                "updated_at": row["updated_at"],
            }
        except sqlite3.Error as e:
            logger.error("加载剧本状态失败: %s", e)
            return None

    def save(self, uid: int, state: dict) -> None:
        conn = self._db._get_connection()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO script_state "
                "(uid, active_script, active_chapter, chapter_scores, flags, "
                "turn_count, started_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                (
                    uid,
                    state.get("active_script", ""),
                    state.get("active_chapter", ""),
                    json.dumps(state.get("chapter_scores", {})),
                    json.dumps(state.get("flags", {})),
                    state.get("turn_count", 0),
                    state.get("started_at", ""),
                ),
            )
            conn.commit()
        except sqlite3.Error as e:
            logger.error("保存剧本状态失败: %s", e)
            conn.rollback()

    def clear(self, uid: int) -> None:
        conn = self._db._get_connection()
        try:
            conn.execute("DELETE FROM script_state WHERE uid = ?", (uid,))
            conn.commit()
        except sqlite3.Error as e:
            logger.error("清除剧本状态失败: %s", e)
            conn.rollback()

    def save_recording(self, recording: dict) -> bool:
        conn = self._db._get_connection()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO script_recordings "
                "(id, user_id, script_id, chapter_id, key_points_met, "
                "user_input, ai_reply, tool_calls, context_fingerprint, "
                "replay_mode, is_valid) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
                (
                    recording["id"],
                    recording["user_id"],
                    recording["script_id"],
                    recording["chapter_id"],
                    json.dumps(recording.get("key_points_met", [])),
                    recording["user_input"],
                    recording["ai_reply"],
                    recording.get("tool_calls"),
                    recording["context_fingerprint"],
                    recording.get("replay_mode", "exact"),
                ),
            )
            conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error("保存录制失败: %s", e)
            conn.rollback()
            return False

    def find_recording(self, user_id: int, script_id: str, chapter_id: str) -> list[dict]:
        conn = self._db._get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM script_recordings "
                "WHERE user_id = ? AND script_id = ? AND chapter_id = ? AND is_valid = 1 "
                "ORDER BY hit_count DESC, created_at DESC",
                (user_id, script_id, chapter_id),
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.Error as e:
            logger.error("查找录制失败: %s", e)
            return []

    def invalidate_recordings(self, script_id: str, reason: str = "") -> int:
        conn = self._db._get_connection()
        try:
            cursor = conn.execute(
                "UPDATE script_recordings SET is_valid = 0, "
                "invalidated_at = datetime('now') "
                "WHERE script_id = ? AND is_valid = 1",
                (script_id,),
            )
            conn.commit()
            return cursor.rowcount
        except sqlite3.Error as e:
            logger.error("使录制失效失败: %s", e)
            conn.rollback()
            return 0

    def increment_hit_count(self, recording_id: str) -> None:
        conn = self._db._get_connection()
        try:
            conn.execute(
                "UPDATE script_recordings SET hit_count = hit_count + 1 WHERE id = ?",
                (recording_id,),
            )
            conn.commit()
        except sqlite3.Error as e:
            logger.error("更新录制命中计数失败: %s", e)
            conn.rollback()