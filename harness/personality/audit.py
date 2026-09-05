# prompt/personality_v3/audit.py
# 状态变化审计日志 — 记录每次交互对人格状态的影响，可复盘/定位动力学问题。
# 条目结构: {event, intensity, signal, old_value, new_value, rule_id, uid, card_id, ts}

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from .persistence import _get_conn_from_db

logger = logging.getLogger("PersonalityAudit")

# 内存环形缓冲上限（同时镜像到 DB，重启后仍可查）
IN_MEMORY_LIMIT = 500
# DB 中保留最近多少条
DB_KEEP_RECENT = 1000


@dataclass
class AuditEntry:
    event_type: str
    intensity: str
    signal: str = ""           # 事件派生的数值信号（如亲和权重 +2.00）
    rule_id: str = ""          # 应用了哪条动力学规则
    old_value: float = 0.0     # 关键信号旧值（亲密度）
    new_value: float = 0.0     # 关键信号新值（亲密度）
    mood_before: dict = field(default_factory=dict)
    mood_after: dict = field(default_factory=dict)
    affinity_delta: float = 0.0
    mood_delta: dict = field(default_factory=dict)
    uid: int = 0
    card_id: str = ""
    ts: float = field(default_factory=time.time)
    analysis: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ts"] = self.ts
        return d


class AuditLogger:
    def __init__(self, db=None):
        self._db = db
        self._recent: deque[AuditEntry] = deque(maxlen=IN_MEMORY_LIMIT)
        self._lock = threading.Lock()

    def _get_conn(self):
        return _get_conn_from_db(self._db)

    def init_tables(self) -> None:
        if self._db is None:
            return
        try:
            conn = self._get_conn()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS personality_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uid INTEGER NOT NULL DEFAULT 0,
                    card_id TEXT NOT NULL DEFAULT '',
                    event_type TEXT NOT NULL DEFAULT '',
                    intensity TEXT NOT NULL DEFAULT '',
                    signal TEXT NOT NULL DEFAULT '',
                    rule_id TEXT NOT NULL DEFAULT '',
                    old_affinity REAL NOT NULL DEFAULT 0,
                    new_affinity REAL NOT NULL DEFAULT 0,
                    affinity_delta REAL NOT NULL DEFAULT 0,
                    mood_before_json TEXT NOT NULL DEFAULT '{}',
                    mood_after_json TEXT NOT NULL DEFAULT '{}',
                    mood_delta_json TEXT NOT NULL DEFAULT '{}',
                    analysis TEXT NOT NULL DEFAULT '',
                    ts REAL NOT NULL DEFAULT 0
                )
            """)
            conn.commit()
        except Exception as e:
            logger.error("创建审计表失败: %s", e)

    def record(self, entry: AuditEntry) -> None:
        with self._lock:
            self._recent.append(entry)
        self._persist(entry)

    def _persist(self, entry: AuditEntry) -> None:
        if self._db is None:
            return
        try:
            conn = self._get_conn()
            conn.execute(
                """INSERT INTO personality_audit
                   (uid, card_id, event_type, intensity, signal, rule_id,
                    old_affinity, new_affinity, affinity_delta,
                    mood_before_json, mood_after_json, mood_delta_json, analysis, ts)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (entry.uid, entry.card_id, entry.event_type, entry.intensity,
                 entry.signal, entry.rule_id,
                 entry.old_value, entry.new_value, entry.affinity_delta,
                 json.dumps(entry.mood_before, ensure_ascii=False),
                 json.dumps(entry.mood_after, ensure_ascii=False),
                 json.dumps(entry.mood_delta, ensure_ascii=False),
                 entry.analysis, entry.ts),
            )
            # 只保留最近 DB_KEEP_RECENT 条
            conn.execute(
                """DELETE FROM personality_audit
                   WHERE id NOT IN (
                       SELECT id FROM personality_audit
                       ORDER BY id DESC LIMIT ?)""",
                (DB_KEEP_RECENT,),
            )
            conn.commit()
        except Exception as e:
            logger.error("写入审计日志失败: %s", e)

    def recent(self, uid: int = 0, card_id: str = "", limit: int = 50) -> list[dict]:
        """优先返回内存中的最近事件，可叠加按用户/角色过滤。"""
        with self._lock:
            items = list(self._recent)
        result = []
        for it in reversed(items):
            if uid and it.uid != uid:
                continue
            if card_id and it.card_id != card_id:
                continue
            result.append(it.to_dict())
            if len(result) >= limit:
                break
        return result

    def flush(self) -> None:
        # 审计条目已同步写库（write-through），无需额外 flush
        pass
