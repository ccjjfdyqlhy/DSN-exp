# prompt/personality_v3/persistence.py
# V3 持久化层 — character_cards / distilled_traits / user_character_cards / character_experiences

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Optional

logger = logging.getLogger("PersonalityV3Persistence")

CREATE_CARDS_TABLE = """
CREATE TABLE IF NOT EXISTS character_cards (
    card_id TEXT PRIMARY KEY,
    is_active INTEGER NOT NULL DEFAULT 1,
    yaml_content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

CREATE_DISTILLED_TABLE = """
CREATE TABLE IF NOT EXISTS distilled_traits (
    distillation_id TEXT PRIMARY KEY,
    card_id TEXT NOT NULL REFERENCES character_cards(card_id),
    version INTEGER NOT NULL DEFAULT 1,
    content_fingerprint TEXT NOT NULL,
    model_used TEXT DEFAULT '',
    json_content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

CREATE_USER_CARDS_TABLE = """
CREATE TABLE IF NOT EXISTS user_character_cards (
    uid INTEGER NOT NULL,
    card_id TEXT NOT NULL REFERENCES character_cards(card_id),
    active_distillation_id TEXT DEFAULT '',
    total_interactions INTEGER NOT NULL DEFAULT 0,
    affinity_value REAL NOT NULL DEFAULT 20.0,
    mood_state_json TEXT NOT NULL DEFAULT '{}',
    dynamic_config_json TEXT NOT NULL DEFAULT '{}',
    seed INTEGER NOT NULL DEFAULT 42,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (uid, card_id)
)
"""

CREATE_EXPERIENCES_TABLE = """
CREATE TABLE IF NOT EXISTS character_experiences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id TEXT NOT NULL REFERENCES character_cards(card_id),
    source_type TEXT NOT NULL DEFAULT 'inline',
    original_filename TEXT DEFAULT '',
    original_content_hash TEXT DEFAULT '',
    summary_text TEXT NOT NULL,
    original_length INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

ALL_TABLES = [
    ("character_cards", CREATE_CARDS_TABLE),
    ("distilled_traits", CREATE_DISTILLED_TABLE),
    ("user_character_cards", CREATE_USER_CARDS_TABLE),
    ("character_experiences", CREATE_EXPERIENCES_TABLE),
]


class V3Persistence:
    def __init__(self, db=None):
        self._db = db
        self._pending: dict[str, dict] = {}
        self._pending_count: int = 0
        self._last_flush: float = time.time()
        self._lock = threading.Lock()
        self.PERSIST_INTERVAL = 5.0
        self.MAX_PENDING = 3

    def _get_conn(self):
        if self._db is None:
            return None
        return self._db._get_connection()

    @property
    def has_db(self) -> bool:
        return self._db is not None

    def init_tables(self) -> None:
        if self._db is None:
            logger.info("db 未注入，V3 持久层为仅内存模式")
            return
        conn = self._get_conn()
        try:
            for name, sql in ALL_TABLES:
                conn.execute(sql)
            conn.commit()
            logger.info("V3 持久层表已就绪")
        except Exception as e:
            logger.error("创建 V3 持久层表失败: %s", e)
            conn.rollback()
            raise

    # ---- 角色卡 CRUD ----

    def save_card(self, card_id: str, yaml_content: str) -> None:
        if self._db is None:
            return
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO character_cards (card_id, yaml_content, updated_at)
                   VALUES (?, ?, datetime('now'))
                   ON CONFLICT(card_id) DO UPDATE SET
                   yaml_content = excluded.yaml_content,
                   updated_at = datetime('now')""",
                (card_id, yaml_content),
            )
            conn.commit()
            logger.info("角色卡已保存: %s", card_id)
        except Exception as e:
            logger.error("保存角色卡失败 %s: %s", card_id, e)
            conn.rollback()

    def load_card_yaml(self, card_id: str) -> Optional[str]:
        if self._db is None:
            return None
        conn = self._get_conn()
        row = conn.execute(
            "SELECT yaml_content FROM character_cards WHERE card_id = ? AND is_active = 1",
            (card_id,),
        ).fetchone()
        return row["yaml_content"] if row else None

    def list_cards(self) -> list[dict]:
        if self._db is None:
            return []
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT card_id, is_active, created_at, updated_at FROM character_cards WHERE is_active = 1 ORDER BY card_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_card(self, card_id: str) -> None:
        if self._db is None:
            return
        conn = self._get_conn()
        try:
            conn.execute("UPDATE character_cards SET is_active = 0 WHERE card_id = ?", (card_id,))
            conn.commit()
            logger.info("角色卡已标记删除: %s", card_id)
        except Exception as e:
            logger.error("删除角色卡失败 %s: %s", card_id, e)
            conn.rollback()

    # ---- 蒸馏产物 CRUD ----

    def save_distillation(self, distillation_id: str, card_id: str, version: int,
                          fingerprint: str, model_used: str, json_content: str) -> None:
        if self._db is None:
            return
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO distilled_traits (distillation_id, card_id, version,
                   content_fingerprint, model_used, json_content)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (distillation_id, card_id, version, fingerprint, model_used, json_content),
            )
            conn.commit()
            logger.info("蒸馏产物已保存: %s (v%d)", distillation_id, version)
        except Exception as e:
            logger.error("保存蒸馏产物失败: %s", e)
            conn.rollback()

    def load_distillation(self, card_id: str) -> Optional[dict]:
        if self._db is None:
            return None
        conn = self._get_conn()
        row = conn.execute(
            """SELECT * FROM distilled_traits
               WHERE card_id = ?
               ORDER BY version DESC LIMIT 1""",
            (card_id,),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        try:
            result["json_content"] = json.loads(result["json_content"])
        except (json.JSONDecodeError, TypeError):
            pass
        return result

    def load_distillation_by_id(self, distillation_id: str) -> Optional[dict]:
        if self._db is None:
            return None
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM distilled_traits WHERE distillation_id = ?",
            (distillation_id,),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        try:
            result["json_content"] = json.loads(result["json_content"])
        except (json.JSONDecodeError, TypeError):
            pass
        return result

    # ---- 用户角色卡绑定 CRUD ----

    def bind_user_card(self, uid: int, card_id: str, distillation_id: str = "",
                       seed: int = 42) -> None:
        if self._db is None:
            return
        conn = self._get_conn()
        try:
            config_json = json.dumps({}, ensure_ascii=False)
            conn.execute(
                """INSERT INTO user_character_cards (uid, card_id, active_distillation_id,
                   seed, created_at, updated_at)
                   VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))
                   ON CONFLICT(uid, card_id) DO UPDATE SET
                   active_distillation_id = excluded.active_distillation_id,
                   seed = excluded.seed,
                   updated_at = datetime('now')""",
                (uid, card_id, distillation_id, seed),
            )
            conn.commit()
            logger.info("用户 %d 已绑定角色卡: %s", uid, card_id)
        except Exception as e:
            logger.error("绑定用户角色卡失败: %s", e)
            conn.rollback()

    def get_user_active_card(self, uid: int) -> Optional[dict]:
        if self._db is None:
            return None
        conn = self._get_conn()
        row = conn.execute(
            """SELECT ucc.*, cc.yaml_content
               FROM user_character_cards ucc
               JOIN character_cards cc ON ucc.card_id = cc.card_id
               WHERE ucc.uid = ? AND cc.is_active = 1
               ORDER BY ucc.updated_at DESC LIMIT 1""",
            (uid,),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        try:
            result["mood_state_json"] = json.loads(result.get("mood_state_json", "{}"))
        except (json.JSONDecodeError, TypeError):
            result["mood_state_json"] = {}
        try:
            result["dynamic_config_json"] = json.loads(result.get("dynamic_config_json", "{}"))
        except (json.JSONDecodeError, TypeError):
            result["dynamic_config_json"] = {}
        return result

    def update_user_state(self, uid: int, card_id: str, total_interactions: int,
                          affinity_value: float, mood_state: dict) -> None:
        if self._db is None:
            return
        data = {
            "total_interactions": total_interactions,
            "affinity_value": affinity_value,
            "mood_state_json": json.dumps(mood_state, ensure_ascii=False),
        }
        with self._lock:
            key = f"{uid}_{card_id}"
            self._pending[key] = data
            self._pending_count += 1
        self._try_flush()

    def _try_flush(self) -> None:
        if self._db is None:
            return
        with self._lock:
            if self._pending_count < self.MAX_PENDING:
                if time.time() - self._last_flush < self.PERSIST_INTERVAL:
                    return
        self._flush()

    def _flush(self) -> None:
        if self._db is None:
            return
        with self._lock:
            if not self._pending:
                return
            pending = dict(self._pending)
            self._pending.clear()
            self._pending_count = 0
            self._last_flush = time.time()

        conn = self._get_conn()
        try:
            for key, data in pending.items():
                uid_str, card_id = key.rsplit("_", 1)
                uid = int(uid_str)
                conn.execute(
                    """UPDATE user_character_cards
                       SET total_interactions = ?, affinity_value = ?,
                           mood_state_json = ?, updated_at = datetime('now')
                       WHERE uid = ? AND card_id = ?""",
                    (data["total_interactions"], data["affinity_value"],
                     data["mood_state_json"], uid, card_id),
                )
            conn.commit()
            logger.info("已刷新 %d 条用户人格状态", len(pending))
        except Exception as e:
            logger.error("刷新用户人格状态失败: %s", e)
            conn.rollback()

    def force_flush(self) -> None:
        self._flush()
