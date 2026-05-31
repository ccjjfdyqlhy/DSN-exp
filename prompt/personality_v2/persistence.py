# prompt/personality_v2/persistence.py
# PersonalityStateStore — 人格状态 SQLite 持久化

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Optional

logger = logging.getLogger("PersonalityStateStore")

CREATE_PERSONALITY_TABLE = """
CREATE TABLE IF NOT EXISTS personality_state (
    uid INTEGER PRIMARY KEY,
    -- 情绪模块
    joly            REAL NOT NULL DEFAULT 0.5,
    sorw            REAL NOT NULL DEFAULT 0.5,
    angr            REAL NOT NULL DEFAULT 0.5,
    fear            REAL NOT NULL DEFAULT 0.5,
    meta            REAL NOT NULL DEFAULT 0.7,
    joly_baseline   REAL NOT NULL DEFAULT 0.5,
    sorw_baseline   REAL NOT NULL DEFAULT 0.5,
    angr_baseline   REAL NOT NULL DEFAULT 0.5,
    fear_baseline   REAL NOT NULL DEFAULT 0.5,
    meta_baseline   REAL NOT NULL DEFAULT 0.7,
    emotion_inertia_json TEXT NOT NULL DEFAULT '{}',
    -- 亲和力模块
    affinity            REAL NOT NULL DEFAULT 20.0,
    affinity_extra_json TEXT NOT NULL DEFAULT '{}',
    -- 习性模块
    habits_json         TEXT NOT NULL DEFAULT '[]',
    innate_weight       REAL NOT NULL DEFAULT 1.0,
    -- 元数据
    preset_name         TEXT NOT NULL DEFAULT 'default',
    total_interactions  INTEGER NOT NULL DEFAULT 0,
    last_interaction    TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
)
"""


class PersonalityStateStore:
    """
    人格状态持久化器。

    使用 ChatDBManager 的连接做 CRUD，不创建独立连接。
    """

    PERSIST_INTERVAL = 5.0
    MAX_PENDING = 3

    def __init__(self, db=None):
        """
        :param db: ChatDBManager 实例（共享连接）
        """
        self._db = db
        self._pending: dict[int, dict] = {}
        self._pending_count: int = 0
        self._last_flush: float = time.time()
        self._lock = threading.Lock()

    def _get_conn(self):
        if self._db is None:
            return None
        return self._db._get_connection()

    @property
    def has_db(self) -> bool:
        return self._db is not None

    def init_table(self) -> None:
        """在数据库中创建 personality_state 表"""
        if self._db is None:
            logger.info("db 未注入，跳过长时持久化（仅内存模式）")
            return
        conn = self._get_conn()
        try:
            conn.execute(CREATE_PERSONALITY_TABLE)
            conn.commit()
            logger.info("personality_state 表已就绪")
        except Exception as e:
            logger.error("创建 personality_state 表失败: %s", e)
            conn.rollback()
            raise

    def load(self, uid: int) -> dict | None:
        """加载指定用户的人格状态，db 不可用时返回 None（触发新建默认状态）"""
        if self._db is None:
            return None
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM personality_state WHERE uid = ?", (uid,)
            ).fetchone()
            if row is None:
                return None
            logger.info("加载人格状态 uid=%d preset=%s", uid, row["preset_name"])
            return dict(row)
        except Exception as e:
            logger.error("加载人格状态失败 uid=%d: %s", uid, e)
            return None

    def save(self, uid: int, emotion_dict: dict, affinity_dict: dict,
             habits_list: list[dict], preset_name: str = "default",
             total_interactions: int = 0, innate_weight: float = 1.0,
             last_interaction: str | None = None) -> None:
        """保存人格状态（延迟批量写模式）。db 不可用时静默跳过。"""
        if self._db is None:
            return
        data = {
            "emotion": emotion_dict,
            "affinity": affinity_dict,
            "habits": habits_list,
            "preset_name": preset_name,
            "total_interactions": total_interactions,
            "innate_weight": innate_weight,
            "last_interaction": last_interaction or "",
        }
        with self._lock:
            self._pending[uid] = data
            self._pending_count += 1
        self._try_flush()

    def _try_flush(self) -> None:
        """条件触发刷新"""
        if self._db is None:
            return
        with self._lock:
            if self._pending_count < self.MAX_PENDING:
                elapsed = time.time() - self._last_flush
                if elapsed < self.PERSIST_INTERVAL:
                    return

        self._flush()

    def _flush(self) -> None:
        """执行批量写入"""
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
            for uid, data in pending.items():
                emo = data["emotion"]
                aff = data["affinity"]

                values = emo.get("values", {})
                baselines = emo.get("baselines", {})
                inertia = emo.get("inertia", {})

                now = data.get("last_interaction") or ""

                conn.execute("""
                    INSERT INTO personality_state (
                        uid, joly, sorw, angr, fear, meta,
                        joly_baseline, sorw_baseline, angr_baseline, fear_baseline, meta_baseline,
                        emotion_inertia_json,
                        affinity, affinity_extra_json,
                        habits_json, innate_weight,
                        preset_name, total_interactions, last_interaction, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(uid) DO UPDATE SET
                        joly = excluded.joly, sorw = excluded.sorw,
                        angr = excluded.angr, fear = excluded.fear, meta = excluded.meta,
                        joly_baseline = excluded.joly_baseline,
                        sorw_baseline = excluded.sorw_baseline,
                        angr_baseline = excluded.angr_baseline,
                        fear_baseline = excluded.fear_baseline,
                        meta_baseline = excluded.meta_baseline,
                        emotion_inertia_json = excluded.emotion_inertia_json,
                        affinity = excluded.affinity,
                        affinity_extra_json = excluded.affinity_extra_json,
                        habits_json = excluded.habits_json,
                        innate_weight = excluded.innate_weight,
                        preset_name = excluded.preset_name,
                        total_interactions = excluded.total_interactions,
                        last_interaction = excluded.last_interaction,
                        updated_at = datetime('now')
                """, (
                    uid,
                    values.get("joly", 0.5), values.get("sorw", 0.5),
                    values.get("angr", 0.5), values.get("fear", 0.5), values.get("meta", 0.7),
                    baselines.get("joly", 0.5), baselines.get("sorw", 0.5),
                    baselines.get("angr", 0.5), baselines.get("fear", 0.5), baselines.get("meta", 0.7),
                    json.dumps(inertia, ensure_ascii=False),
                    aff.get("value", 20.0),
                    json.dumps({
                        "action_cooldowns": aff.get("action_cooldowns", {}),
                        "action_daily_counts": aff.get("action_daily_counts", {}),
                        "last_insult_time": aff.get("last_insult_time"),
                        "recent_changes": aff.get("recent_changes", []),
                        "decay_enabled": aff.get("decay_enabled", False),
                        "last_interaction": aff.get("last_interaction"),
                    }, ensure_ascii=False),
                    json.dumps(data["habits"], ensure_ascii=False),
                    data.get("innate_weight", 1.0),
                    data.get("preset_name", "default"),
                    data.get("total_interactions", 0),
                    now or None,
                ))

            conn.commit()
            logger.info("已持久化 %d 条人格状态", len(pending))
        except Exception as e:
            logger.error("刷新人格状态失败: %s", e)
            conn.rollback()

    def force_flush(self) -> None:
        """强制立即刷新所有待保存状态"""
        self._flush()

    def ensure_exists(self, uid: int, preset_name: str = "default") -> None:
        """确保 uid 有人格状态记录，没有则创建默认记录。db 不可用时静默跳过。"""
        if self._db is None:
            return
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT uid FROM personality_state WHERE uid = ?", (uid,)
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO personality_state (uid, preset_name) VALUES (?, ?)",
                    (uid, preset_name),
                )
                conn.commit()
                logger.info("为用户 %d 创建默认人格状态", uid)
        except Exception as e:
            logger.error("确保人格状态存在失败 uid=%d: %s", uid, e)
            conn.rollback()
