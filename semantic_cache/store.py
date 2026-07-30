import logging
import struct
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("CacheStore")

DEFAULT_EMBEDDING_DIMS = 768


class CacheStore:

    def __init__(self, db, cache_dir: str):
        self._db = db
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._vectors_dir = self._cache_dir / "vectors"
        self._vectors_dir.mkdir(parents=True, exist_ok=True)
        self._tts_dir = self._cache_dir / "tts"
        self._tts_dir.mkdir(parents=True, exist_ok=True)
        self._dims = DEFAULT_EMBEDDING_DIMS
        self._index: Optional[np.ndarray] = None
        self._index_norm: Optional[np.ndarray] = None
        self._index_keys: list[str] = []
        self._index_lock = threading.Lock()
        self._init_tables()
        self._load_index()

    def _conn(self):
        return self._db._get_connection()

    def _init_tables(self):
        conn = self._conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sc_cache_entries (
                cache_key       TEXT PRIMARY KEY,
                user_id         INTEGER NOT NULL DEFAULT 0,
                intent_class    TEXT NOT NULL DEFAULT '',
                query_text      TEXT NOT NULL,
                query_embedding BLOB,
                reply_text      TEXT NOT NULL,
                reply_tts_path  TEXT DEFAULT '',
                hit_count       INTEGER DEFAULT 0,
                score           REAL DEFAULT 1.0,
                model_version   TEXT DEFAULT '',
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_hit_at     TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_sc_entries_intent
            ON sc_cache_entries(intent_class)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_sc_entries_score
            ON sc_cache_entries(score)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sc_cache_l1 (
                intent_id       TEXT NOT NULL,
                speech_act_type TEXT NOT NULL,
                text            TEXT NOT NULL,
                tts_path        TEXT DEFAULT '',
                hit_count       INTEGER DEFAULT 0,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (intent_id, speech_act_type)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sc_l2_dags (
                action_signature TEXT PRIMARY KEY,
                intent_id        TEXT NOT NULL DEFAULT '',
                dag_json         TEXT NOT NULL,
                model_version    TEXT DEFAULT '',
                hit_count        INTEGER DEFAULT 0,
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_hit_at      TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_l2_dags_intent
            ON sc_l2_dags(intent_id)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sc_l2_results (
                result_id        INTEGER PRIMARY KEY AUTOINCREMENT,
                action_signature TEXT NOT NULL,
                slot_hash        TEXT NOT NULL,
                result_text      TEXT NOT NULL,
                reply_tts_path   TEXT DEFAULT '',
                response_json    TEXT DEFAULT '',
                hit_count        INTEGER DEFAULT 0,
                executed_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                duration_ms      INTEGER DEFAULT 0,
                FOREIGN KEY (action_signature) REFERENCES sc_l2_dags(action_signature)
            )
        """)
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_l2_results_sig_slot
            ON sc_l2_results(action_signature, slot_hash)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sc_l3_slots (
                session_id   TEXT NOT NULL,
                slot_name    TEXT NOT NULL,
                slot_type    TEXT NOT NULL DEFAULT 'str',
                value_json   TEXT NOT NULL,
                confidence   REAL DEFAULT 1.0,
                source       TEXT DEFAULT 'extracted',
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at   TIMESTAMP DEFAULT '',
                PRIMARY KEY (session_id, slot_name)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_l3_slots_session
            ON sc_l3_slots(session_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_l3_slots_expires
            ON sc_l3_slots(expires_at)
        """)
        conn.commit()

    @staticmethod
    def _vec_to_blob(vec: list[float]) -> bytes:
        return struct.pack(f"{len(vec)}f", *vec)

    @staticmethod
    def _blob_to_vec(blob: bytes) -> list[float]:
        return list(struct.unpack(f"{len(blob) // 4}f", blob))

    def _load_index(self):
        conn = self._conn()
        rows = conn.execute(
            "SELECT cache_key, query_embedding FROM sc_cache_entries "
            "WHERE query_embedding IS NOT NULL AND score >= 0.35"
        ).fetchall()
        vecs = []
        keys = []
        for r in rows:
            try:
                vec = self._blob_to_vec(r["query_embedding"])
                if len(vec) == self._dims:
                    vecs.append(vec)
                    keys.append(r["cache_key"])
            except Exception:
                logger.warning("Operation failed", exc_info=True)
        with self._index_lock:
            self._index = np.array(vecs, dtype=np.float32) if vecs else None
            self._index_norm = (
                self._index / (np.linalg.norm(self._index, axis=1, keepdims=True) + 1e-8)
                if self._index is not None else None
            )
            self._index_keys = keys
        logger.info("向量索引加载: %d 条", len(keys))

    def _add_to_index(self, cache_key: str, vec: list[float]):
        if len(vec) != self._dims:
            return
        with self._index_lock:
            if cache_key in self._index_keys:
                return
            v = np.array([vec], dtype=np.float32)
            v_norm = v / (np.linalg.norm(v) + 1e-8)
            if self._index is None:
                self._index = v
                self._index_norm = v_norm
            else:
                self._index = np.vstack([self._index, v])
                self._index_norm = np.vstack([self._index_norm, v_norm])
            self._index_keys.append(cache_key)

    def _remove_from_index(self, cache_key: str):
        with self._index_lock:
            if self._index is None:
                return
            try:
                idx = self._index_keys.index(cache_key)
                self._index = np.delete(self._index, idx, axis=0)
                self._index_norm = (
                    np.delete(self._index_norm, idx, axis=0)
                    if self._index_norm is not None else None
                )
                self._index_keys.pop(idx)
            except (ValueError, IndexError):
                pass

    def search_index(self, query_vec: list[float], threshold: float = 0.80,
                     intent_filter: str = "", top_k: int = 5) -> list[tuple[str, float]]:
        with self._index_lock:
            if self._index is None or self._index.shape[0] == 0:
                return []

            q = np.array([query_vec], dtype=np.float32)
            q_norm = q / (np.linalg.norm(q) + 1e-8)
            sims = np.dot(q_norm, self._index_norm.T)[0]

            sorted_indices = np.argsort(sims)[::-1]
            results = []
            for i in sorted_indices:
                sim = float(sims[i])
                if sim < threshold:
                    break
                key = self._index_keys[i]
                if intent_filter:
                    conn = self._conn()
                    row = conn.execute(
                        "SELECT intent_class FROM sc_cache_entries WHERE cache_key=?",
                        (key,),
                    ).fetchone()
                    if not row or row["intent_class"] != intent_filter:
                        continue
                results.append((key, sim))
                if len(results) >= top_k:
                    break
            return results

    def put_entry(self, cache_key: str, user_id: int, intent_class: str,
                  query_text: str, query_embedding: Optional[list[float]],
                  reply_text: str, reply_tts_path: str = "") -> bool:
        conn = self._conn()
        try:
            blob = self._vec_to_blob(query_embedding) if query_embedding else None
            conn.execute(
                """INSERT INTO sc_cache_entries
                   (cache_key, user_id, intent_class, query_text, query_embedding,
                    reply_text, reply_tts_path, hit_count, score, model_version)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1.0, '')
                   ON CONFLICT(cache_key) DO UPDATE SET
                     user_id=excluded.user_id,
                     reply_text=excluded.reply_text,
                     reply_tts_path=excluded.reply_tts_path,
                     query_embedding=excluded.query_embedding,
                     last_hit_at=CURRENT_TIMESTAMP""",
                (cache_key, user_id, intent_class, query_text, blob,
                 reply_text, reply_tts_path),
            )
            conn.commit()
            if query_embedding and blob:
                self._add_to_index(cache_key, query_embedding)
            return True
        except Exception as e:
            logger.error("写入缓存失败: %s", e)
            conn.rollback()
            return False

    def get_entry(self, cache_key: str) -> Optional[dict]:
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM sc_cache_entries WHERE cache_key=?",
            (cache_key,),
        ).fetchone()
        if not row:
            return None
        return dict(row)

    def update_hit(self, cache_key: str):
        conn = self._conn()
        conn.execute(
            "UPDATE sc_cache_entries SET hit_count = hit_count + 1, "
            "last_hit_at = CURRENT_TIMESTAMP WHERE cache_key=?",
            (cache_key,),
        )
        conn.commit()

    def update_score(self, cache_key: str, score: float):
        conn = self._conn()
        conn.execute(
            "UPDATE sc_cache_entries SET score = ? WHERE cache_key=?",
            (score, cache_key),
        )
        conn.commit()
        if score < 0.35:
            self._remove_from_index(cache_key)

    def get_entry_count(self, intent_filter: str = "") -> int:
        conn = self._conn()
        if intent_filter:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM sc_cache_entries WHERE intent_class=?",
                (intent_filter,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM sc_cache_entries"
            ).fetchone()
        return row["cnt"] if row else 0

    def get_stats(self) -> dict:
        conn = self._conn()
        total = conn.execute(
            "SELECT COUNT(*) as cnt FROM sc_cache_entries"
        ).fetchone()["cnt"]
        hits = conn.execute(
            "SELECT COALESCE(SUM(hit_count), 0) as cnt FROM sc_cache_entries"
        ).fetchone()["cnt"]
        avg_score = conn.execute(
            "SELECT COALESCE(AVG(score), 0) as s FROM sc_cache_entries"
        ).fetchone()["s"]
        l2_dags = conn.execute(
            "SELECT COUNT(*) as cnt FROM sc_l2_dags"
        ).fetchone()["cnt"]
        l2_results = conn.execute(
            "SELECT COUNT(*) as cnt FROM sc_l2_results"
        ).fetchone()["cnt"]
        l3_slots = conn.execute(
            "SELECT COUNT(*) as cnt FROM sc_l3_slots"
        ).fetchone()["cnt"]
        return {
            "total_entries": total,
            "total_hits": hits,
            "avg_score": round(avg_score, 3),
            "index_vectors": len(self._index_keys),
            "l2_dags": l2_dags,
            "l2_results": l2_results,
            "l3_slots": l3_slots,
        }

    def put_l1(self, intent_id: str, speech_act_type: str,
               text: str, tts_path: str = "") -> bool:
        conn = self._conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO sc_cache_l1 "
                "(intent_id, speech_act_type, text, tts_path) "
                "VALUES (?, ?, ?, ?)",
                (intent_id, speech_act_type, text, tts_path),
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error("写入 L1 缓存失败: %s", e)
            conn.rollback()
            return False

    def get_l1(self, intent_id: str, speech_act_type: str) -> Optional[dict]:
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM sc_cache_l1 WHERE intent_id=? AND speech_act_type=?",
            (intent_id, speech_act_type),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE sc_cache_l1 SET hit_count = hit_count + 1 "
            "WHERE intent_id=? AND speech_act_type=?",
            (intent_id, speech_act_type),
        )
        conn.commit()
        return dict(row)

    def list_l1_intents(self) -> list[str]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT DISTINCT intent_id FROM sc_cache_l1 ORDER BY intent_id"
        ).fetchall()
        return [r["intent_id"] for r in rows]

    def list_l1_all(self) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM sc_cache_l1 ORDER BY hit_count DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def save_tts(self, cache_key: str, audio_bytes: bytes) -> str:
        tts_path = self._tts_dir / f"{cache_key}.wav"
        tts_path.write_bytes(audio_bytes)
        return str(tts_path)

    def load_tts(self, tts_path: str) -> Optional[bytes]:
        path = Path(tts_path)
        if path.exists():
            return path.read_bytes()
        return None

    def save_tts_l1(self, intent_id: str, speech_act_type: str,
                     audio_bytes: bytes) -> str:
        tts_path = self._tts_dir / f"l1_{intent_id}_{speech_act_type}.wav"
        tts_path.write_bytes(audio_bytes)
        return str(tts_path)

    def put_l2_dag(self, action_signature: str, intent_id: str,
                   dag_json: str, model_version: str = "") -> bool:
        conn = self._conn()
        try:
            conn.execute(
                """INSERT INTO sc_l2_dags
                   (action_signature, intent_id, dag_json, model_version)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(action_signature) DO UPDATE SET
                     dag_json=excluded.dag_json,
                     model_version=excluded.model_version,
                     last_hit_at=CURRENT_TIMESTAMP""",
                (action_signature, intent_id, dag_json, model_version),
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error("写入 L2 DAG 失败: %s", e)
            conn.rollback()
            return False

    def get_l2_dag(self, action_signature: str) -> Optional[dict]:
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM sc_l2_dags WHERE action_signature=?",
            (action_signature,),
        ).fetchone()
        return dict(row) if row else None

    def update_l2_hit(self, action_signature: str):
        conn = self._conn()
        conn.execute(
            "UPDATE sc_l2_dags SET hit_count = hit_count + 1, "
            "last_hit_at = CURRENT_TIMESTAMP WHERE action_signature=?",
            (action_signature,),
        )
        conn.commit()

    def put_l2_result(self, action_signature: str, slot_hash: str,
                      result_text: str, tts_path: str = "",
                      response_json: str = "", duration_ms: int = 0) -> bool:
        conn = self._conn()
        try:
            conn.execute(
                """INSERT INTO sc_l2_results
                   (action_signature, slot_hash, result_text, reply_tts_path,
                    response_json, hit_count, duration_ms)
                   VALUES (?, ?, ?, ?, ?, 1, ?)
                   ON CONFLICT(action_signature, slot_hash) DO UPDATE SET
                     result_text=excluded.result_text,
                     reply_tts_path=excluded.reply_tts_path,
                     response_json=excluded.response_json,
                     hit_count=hit_count + 1,
                     duration_ms=excluded.duration_ms""",
                (action_signature, slot_hash, result_text, tts_path,
                 response_json, duration_ms),
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error("写入 L2 结果失败: %s", e)
            conn.rollback()
            return False

    def get_l2_result(self, action_signature: str, slot_hash: str) -> Optional[dict]:
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM sc_l2_results WHERE action_signature=? AND slot_hash=?",
            (action_signature, slot_hash),
        ).fetchone()
        return dict(row) if row else None

    def put_l3_slot(self, session_id: str, slot_name: str, slot_type: str,
                    value_json: str, confidence: float = 1.0,
                    source: str = "extracted", expires_at: str = "") -> bool:
        conn = self._conn()
        try:
            conn.execute(
                """INSERT INTO sc_l3_slots
                   (session_id, slot_name, slot_type, value_json,
                    confidence, source, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(session_id, slot_name) DO UPDATE SET
                     slot_type=excluded.slot_type,
                     value_json=excluded.value_json,
                     confidence=excluded.confidence,
                     source=excluded.source,
                     expires_at=excluded.expires_at""",
                (session_id, slot_name, slot_type, value_json,
                 confidence, source, expires_at),
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error("写入 L3 槽位失败: %s", e)
            conn.rollback()
            return False

    def get_l3_slot(self, session_id: str, slot_name: str) -> Optional[dict]:
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM sc_l3_slots WHERE session_id=? AND slot_name=?",
            (session_id, slot_name),
        ).fetchone()
        return dict(row) if row else None

    def list_l3_slots(self, session_id: str) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM sc_l3_slots WHERE session_id=?",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_l3_slot(self, session_id: str, slot_name: str) -> bool:
        conn = self._conn()
        try:
            conn.execute(
                "DELETE FROM sc_l3_slots WHERE session_id=? AND slot_name=?",
                (session_id, slot_name),
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error("删除 L3 槽位失败: %s", e)
            conn.rollback()
            return False

    def clear_l3_session(self, session_id: str) -> int:
        conn = self._conn()
        try:
            cursor = conn.execute(
                "DELETE FROM sc_l3_slots WHERE session_id=?",
                (session_id,),
            )
            conn.commit()
            return cursor.rowcount
        except Exception as e:
            logger.error("清除 L3 会话失败: %s", e)
            conn.rollback()
            return 0

    def cleanup_expired_l3_slots(self) -> int:
        conn = self._conn()
        try:
            now = datetime.now().isoformat()
            cursor = conn.execute(
                "DELETE FROM sc_l3_slots WHERE expires_at != '' AND expires_at < ?",
                (now,),
            )
            conn.commit()
            count = cursor.rowcount
            if count > 0:
                logger.info("清理过期 L3 槽位: %d 条", count)
            return count
        except Exception as e:
            logger.error("清理过期 L3 槽位失败: %s", e)
            conn.rollback()
            return 0
