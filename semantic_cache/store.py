import json
import logging
import os
import sqlite3
import struct
import threading
from pathlib import Path
from typing import Optional

import numpy as np

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

    # ── 表初始化 ──

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
        conn.commit()

    # ── 向量序列化 ──

    @staticmethod
    def _vec_to_blob(vec: list[float]) -> bytes:
        return struct.pack(f"{len(vec)}f", *vec)

    @staticmethod
    def _blob_to_vec(blob: bytes) -> list[float]:
        return list(struct.unpack(f"{len(blob) // 4}f", blob))

    # ── 向量索引 ──

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
                pass
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
                self._index_norm = np.delete(self._index_norm, idx, axis=0) if self._index_norm is not None else None
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

    # ── 缓存条目 CRUD ──

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
        total = conn.execute("SELECT COUNT(*) as cnt FROM sc_cache_entries").fetchone()["cnt"]
        hits = conn.execute("SELECT COALESCE(SUM(hit_count), 0) as cnt FROM sc_cache_entries").fetchone()["cnt"]
        avg_score = conn.execute(
            "SELECT COALESCE(AVG(score), 0) as s FROM sc_cache_entries"
        ).fetchone()["s"]
        return {
            "total_entries": total,
            "total_hits": hits,
            "avg_score": round(avg_score, 3),
            "index_vectors": len(self._index_keys),
        }

    # ── L1 静态语素 ──

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

    # ── TTS 文件缓存 ──

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
