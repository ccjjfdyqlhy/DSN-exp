# prompt/personality_v3/persistence.py
# V3 持久化层 — 仅保存动态运行时状态 (用户绑定 / 情绪状态)
# 角色卡和蒸馏产物完全托管在 character_cards/ 目录下

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Optional

logger = logging.getLogger("PersonalityV3Persistence")

CREATE_USER_CARDS_TABLE = """
CREATE TABLE IF NOT EXISTS user_character_cards (
    uid INTEGER NOT NULL,
    card_id TEXT NOT NULL,
    active_distillation_id TEXT DEFAULT '',
    total_interactions INTEGER NOT NULL DEFAULT 0,
    affinity_value REAL NOT NULL DEFAULT 20.0,
    mood_state_json TEXT NOT NULL DEFAULT '{}',
    dynamic_config_json TEXT NOT NULL DEFAULT '{}',
    seed INTEGER NOT NULL DEFAULT 42,
    last_interaction_ts TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (uid, card_id)
)
"""

CREATE_EVIDENCE_TABLE = """
CREATE TABLE IF NOT EXISTS personality_evidence (
    card_id TEXT PRIMARY KEY,
    mu_json TEXT NOT NULL DEFAULT '{}',
    sigma_json TEXT NOT NULL DEFAULT '{}',
    counts_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

ALL_TABLES = [
    ("user_character_cards", CREATE_USER_CARDS_TABLE),
    ("personality_evidence", CREATE_EVIDENCE_TABLE),
]


def _get_conn_from_db(db):
    """从不同类型的 DB 适配器中安全提取 sqlite3.Connection。
    支持 SqliteStore、DSN 原生 db 或已有连接。
    """
    if db is None:
        return None
    if hasattr(db, "get_connection"):
        return db.get_connection()
    if hasattr(db, "_get_connection"):
        return db._get_connection()
    return getattr(db, "conn", db)


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
        return _get_conn_from_db(self._db)

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
            self._migrate(conn)
            logger.info("V3 持久层表已就绪 (蒸馏产物 + 用户状态 + 证据)")
        except Exception as e:
            logger.error("创建 V3 持久层表失败: %s", e)
            conn.rollback()
            raise

    def _migrate(self, conn) -> None:
        """老库升级: 补充新增列。"""
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(user_character_cards)").fetchall()]
            if "last_interaction_ts" not in cols:
                conn.execute("ALTER TABLE user_character_cards ADD COLUMN last_interaction_ts TEXT DEFAULT ''")
                conn.commit()
        except Exception as e:
            logger.warning("V3 持久层迁移 last_interaction_ts 失败: %s", e)

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
            """SELECT *
               FROM user_character_cards
               WHERE uid = ?
               ORDER BY updated_at DESC LIMIT 1""",
            (uid,),
        ).fetchone()
        if not row:
            return None
        result = dict(row)

        # 合并尚未 flush 的待写状态（read-your-writes），避免 5 秒窗口内读到旧值
        with self._lock:
            for key, pending in self._pending.items():
                uid_str, pcard_id = key.split("_", 1)
                if int(uid_str) == uid and pcard_id == result.get("card_id"):
                    result["total_interactions"] = pending["total_interactions"]
                    result["affinity_value"] = pending["affinity_value"]
                    try:
                        result["mood_state_json"] = json.loads(pending["mood_state_json"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                    if pending.get("last_interaction_ts"):
                        result["last_interaction_ts"] = pending["last_interaction_ts"]
                    break

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
                          affinity_value: float, mood_state: dict,
                          last_interaction_ts: str = "") -> None:
        if self._db is None:
            return
        data = {
            "total_interactions": total_interactions,
            "affinity_value": affinity_value,
            "mood_state_json": json.dumps(mood_state, ensure_ascii=False),
            "last_interaction_ts": last_interaction_ts,
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
                uid_str, card_id = key.split("_", 1)
                uid = int(uid_str)
                conn.execute(
                    """UPDATE user_character_cards
                       SET total_interactions = ?, affinity_value = ?,
                           mood_state_json = ?, last_interaction_ts = ?,
                           updated_at = datetime('now')
                       WHERE uid = ? AND card_id = ?""",
                    (data["total_interactions"], data["affinity_value"],
                     data["mood_state_json"], data.get("last_interaction_ts", ""),
                     uid, card_id),
                )
            conn.commit()
            logger.info("已刷新 %d 条用户人格状态", len(pending))
        except Exception as e:
            logger.error("刷新用户人格状态失败: %s", e)
            conn.rollback()

    def force_flush(self) -> None:
        self._flush()
