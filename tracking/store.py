# tracking/store.py
# TrackingStore — 用户跟踪系统的独立加密数据库数据层。
#
# 特点：
#   1. 独立数据库文件（默认 <root>/tracking.db），与主聊天库 chats.db 完全隔离；
#   2. **分天存储**：事件按天存放在独立的表 tracking_events_YYYYMMDD 中，
#      每天的日志落在不同的单元里（与媒体按天分目录一致）；
#   3. 所有模态数据（audio/image/video/file/text）统一写入当天表，
#      payload 与 meta 字段使用 MessageCipher（AES-256-GCM，按 user_id 派生密钥）加密；
#   4. 支持关键词搜索（解密后内存匹配）与时间范围搜索（按日期路由到相应天表）；
#   5. 全部按 user_id 隔离。
#
# 兼容：可注入 legacy_writer（回写旧 chats.db 的 sensing_events 表）保持旧查询可用。

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("tracking.store")

_EVENT_TYPES = {"audio", "image", "video", "text", "note", "file"}

# 默认数据库文件（独立于 chats.db）
DEFAULT_DB_FILENAME = "tracking.db"

_TABLE_PREFIX = "tracking_events_"


class TrackingStore:
    """独立加密数据库存取，线程安全（每线程独立连接），事件按天分表。

    用法：
        store = TrackingStore(db_path=".dsn/tracking/tracking.db", cipher=cipher)
        store.add_event(user_id=1, etype="audio", payload="...")
        store.search_events(user_id=1, keyword="说话", since="...", until="...")
    """

    def __init__(self, db_path: Optional[str] = None,
                 root: Optional[str] = None,
                 cipher=None, legacy_writer: Optional[Callable] = None):
        """初始化。

        :param db_path: 数据库文件路径（绝对/相对）。缺省时用 root/tracking.db。
        :param root:    media 根目录；db_path 缺省时数据库放在 <root>/tracking.db。
        :param cipher:  MessageCipher 实例；缺省时自动创建。
        :param legacy_writer: callable(user_id, text, rms_level, chat_id, source) -> None，
                              用于回写旧 sensing_events 等兼容写入。
        """
        from utils.crypto import MessageCipher  # 延迟导入避免循环
        self._cipher = cipher or MessageCipher()

        if db_path:
            self.db_path = str(db_path)
        else:
            base = Path(root) if root else Path(".dsn/tracking")
            base.mkdir(parents=True, exist_ok=True)
            self.db_path = str(base / DEFAULT_DB_FILENAME)

        self._legacy_writer = legacy_writer
        self._local = threading.local()
        self._init_lock = threading.Lock()
        self._ensure_base_tables()

    # ── 连接管理 ──
    def _get_connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    def close(self):
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                logger.debug("关闭 tracking 连接失败", exc_info=True)
            self._local.conn = None

    # ── 加密辅助 ──
    def _enc(self, user_id: int, text: str) -> str:
        return self._cipher.encrypt(user_id, text) if text else ""

    def _dec(self, user_id: int, text: str) -> str:
        try:
            return self._cipher.decrypt(user_id, text) if text else ""
        except Exception:
            return text or ""

    # ── schema ──
    @staticmethod
    def _day_str(dt: Optional[datetime] = None) -> str:
        return (dt or datetime.now()).strftime("%Y%m%d")

    @staticmethod
    def _day_table(day: str) -> str:
        """按天表名：tracking_events_YYYYMMDD。"""
        return f"{_TABLE_PREFIX}{day}"

    def _ensure_day_table(self, day: str) -> str:
        """确保某天的表存在并返回表名（线程安全）。"""
        table = self._day_table(day)
        conn = self._get_connection()
        with self._init_lock:
            try:
                conn.execute(f"""
                    CREATE TABLE IF NOT EXISTS {table} (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        chat_id INTEGER DEFAULT NULL,
                        etype TEXT NOT NULL DEFAULT 'text',
                        payload TEXT DEFAULT '',
                        source TEXT DEFAULT 'tracking',
                        meta TEXT DEFAULT '{{}}',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{table}_user_time "
                    f"ON {table}(user_id, created_at)"
                )
                conn.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{table}_user_type "
                    f"ON {table}(user_id, etype, created_at)"
                )
                conn.commit()
            except Exception:
                logger.exception("初始化按天表失败 %s", table)
                conn.rollback()
        return table

    def _ensure_base_tables(self) -> None:
        """创建基础表：tracking_models（建模产物，不分天）。"""
        with self._init_lock:
            conn = self._get_connection()
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS tracking_models (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        model_type TEXT NOT NULL,
                        title TEXT DEFAULT '',
                        content TEXT DEFAULT '',
                        meta TEXT DEFAULT '{}',
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(user_id, model_type, title)
                    )
                """)
                conn.commit()
            except Exception:
                logger.exception("初始化 tracking 独立库基础表失败")
                conn.rollback()

    def day_tables(self, since: str = "", until: str = "") -> list[str]:
        """列出（可用的）按天事件表，按日期升序。可选 since/until (YYYY-MM-DD) 过滤。"""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ?",
                (f"{_TABLE_PREFIX}%",),
            ).fetchall()
            tables = [r["name"] for r in rows]
        except Exception:
            logger.exception("列出按天表失败")
            return []
        tables.sort()
        since_c = (since or "")[:10].replace("-", "")
        until_c = (until or "")[:10].replace("-", "")
        out = []
        for t in tables:
            day = t[len(_TABLE_PREFIX):]
            if since_c and day < since_c:
                continue
            if until_c and day > until_c:
                continue
            out.append(t)
        return out

    # ── 事件写入（落到当天表）──
    def add_event(self, user_id: int, etype: str = "text", payload: str = "",
                  source: str = "tracking", chat_id: Optional[int] = None,
                  meta: Optional[dict] = None,
                  write_legacy_sensing: bool = False,
                  _day: Optional[str] = None) -> int:
        """写入一条多模态观察事件（全字段加密），落到指定/当天分表。

        :param _day: 可选，YYYYMMDD；缺省用当前日期（测试可指定历史日期验证分表）。
        """
        if etype not in _EVENT_TYPES:
            etype = "text"
        if meta is None:
            meta = {}
        day = _day or self._day_str()
        table = self._ensure_day_table(day)
        enc_payload = self._enc(user_id, payload or "")
        enc_meta = self._enc(user_id, json.dumps(meta, ensure_ascii=False)) if meta else ""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                f"INSERT INTO {table} (user_id, chat_id, etype, payload, source, meta) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, chat_id, etype, enc_payload, source, enc_meta),
            )
            new_id = cursor.lastrowid
            conn.commit()
        except Exception:
            logger.exception("写入 tracking 事件失败 (%s)", table)
            conn.rollback()
            raise

        # 兼容旧表：回写 sensing_events（通过 legacy_writer）
        if write_legacy_sensing and self._legacy_writer is not None and etype == "audio":
            try:
                self._legacy_writer(
                    user_id=user_id, text=payload or "",
                    rms_level=float((meta or {}).get("rms_level", 0.0) or 0.0),
                    chat_id=chat_id, source=source,
                )
            except Exception:
                logger.debug("回写 sensing_events 失败（可忽略）", exc_info=True)
        return new_id

    # ── 事件查询：跨天表聚合 + 关键词（解密后内存匹配）──
    def search_events(self, user_id: int, etype: Optional[str] = None,
                      since: str = "", until: str = "",
                      keyword: str = "", limit: int = 50,
                      offset: int = 0) -> list[dict]:
        """搜索当前用户的事件（跨全部/指定日期范围的分天表）。

        时间范围 (since/until) 在表路由层过滤（只查相关天表）；
        关键词 (keyword) 对解密后的 payload 做包含匹配。
        返回按时间倒序的记录，payload/meta 已解密。
        """
        tables = self.day_tables(since=since, until=until)
        conn = self._get_connection()
        results: list[dict] = []
        for table in tables:
            try:
                query = f"SELECT id, user_id, chat_id, etype, payload, source, meta, created_at " \
                        f"FROM {table} WHERE user_id = ?"
                params: list = [user_id]
                if etype:
                    query += " AND etype = ?"
                    params.append(etype)
                rows = conn.execute(query, params).fetchall()
            except Exception:
                logger.exception("搜索 tracking 事件失败 (%s)", table)
                continue

            keywords = [k for k in (keyword or "").split() if k]
            for r in rows:
                dec_payload = self._dec(user_id, r["payload"] or "")
                if keywords and not all(k in dec_payload for k in keywords):
                    continue
                dec_meta = self._dec(user_id, r["meta"] or "") if r["meta"] else "{}"
                try:
                    meta_obj = json.loads(dec_meta) if dec_meta else {}
                except Exception:
                    meta_obj = {}
                results.append({
                    "id": r["id"],
                    "user_id": r["user_id"],
                    "chat_id": r["chat_id"],
                    "etype": r["etype"],
                    "payload": dec_payload,
                    "source": r["source"],
                    "meta": meta_obj,
                    "created_at": r["created_at"],
                })

        # 按时间倒序 + 分页
        results.sort(key=lambda x: (x.get("created_at") or "", x.get("id") or 0), reverse=True)
        start = max(0, int(offset or 0))
        end = start + max(1, min(500, int(limit or 50)))
        return results[start:end]

    # 兼容旧接口：query_events 等同 search_events
    def query_events(self, user_id: int, etype: Optional[str] = None,
                     since: str = "", until: str = "",
                     keyword: str = "", limit: int = 20) -> list[dict]:
        return self.search_events(
            user_id, etype=etype, since=since, until=until, keyword=keyword, limit=limit,
        )

    def get_last_event_time(self, user_id: int, etype: Optional[str] = None) -> Optional[str]:
        """返回用户最近一条指定类型事件的时间戳，无记录返回 None。"""
        tables = self.day_tables()
        conn = self._get_connection()
        best: Optional[str] = None
        for table in reversed(tables):  # 从最新天表往前
            try:
                query = f"SELECT created_at FROM {table} WHERE user_id = ?"
                params: list = [user_id]
                if etype:
                    query += " AND etype = ?"
                    params.append(etype)
                query += " ORDER BY id DESC LIMIT 1"
                row = conn.execute(query, params).fetchone()
                if row and (best is None or row["created_at"] > best):
                    best = row["created_at"]
            except Exception:
                continue
            if best:
                break
        return best

    def count_events_by_day(self, user_id: int, days: int = 30) -> dict[str, int]:
        """统计最近 N 天每天的事件数（供"分天存储"验证/展示）。返回 {YYYY-MM-DD: count}。"""
        conn = self._get_connection()
        out: dict[str, int] = {}
        today = datetime.now().date()
        tables = self.day_tables()
        for table in tables:
            day = table[len(_TABLE_PREFIX):]
            try:
                dt = datetime.strptime(day, "%Y%m%d").date()
            except Exception:
                continue
            if (today - dt).days > max(1, days):
                continue
            try:
                row = conn.execute(
                    f"SELECT COUNT(*) AS n FROM {table} WHERE user_id=?", (user_id,)
                ).fetchone()
                out[day] = int(row["n"]) if row else 0
            except Exception:
                continue
        return out

    # ── 建模产物（不分天）──
    def upsert_model(self, user_id: int, model_type: str, title: str,
                     content: str, meta: Optional[dict] = None) -> int:
        """保存/更新一条建模结果（内容与 meta 加密）。"""
        if meta is None:
            meta = {}
        enc_content = self._enc(user_id, content or "")
        enc_meta = self._enc(user_id, json.dumps(meta, ensure_ascii=False)) if meta else ""
        conn = self._get_connection()
        try:
            conn.execute(
                "INSERT INTO tracking_models (user_id, model_type, title, content, meta, updated_at) "
                "VALUES (?, ?, ?, ?, ?, datetime('now')) "
                "ON CONFLICT(user_id, model_type, title) DO UPDATE SET "
                "content = excluded.content, meta = excluded.meta, updated_at = datetime('now')",
                (user_id, model_type, title, enc_content, enc_meta),
            )
            conn.commit()
            row = conn.execute(
                "SELECT id FROM tracking_models WHERE user_id=? AND model_type=? AND title=?",
                (user_id, model_type, title),
            ).fetchone()
            return row["id"] if row else 0
        except Exception:
            logger.exception("保存 tracking 建模结果失败")
            conn.rollback()
            return 0

    def query_models(self, user_id: int, model_type: Optional[str] = None) -> list[dict]:
        """查询当前用户的建模产物（解密）。"""
        conn = self._get_connection()
        try:
            query = ("SELECT id, user_id, model_type, title, content, meta, updated_at "
                     "FROM tracking_models WHERE user_id = ?")
            params: list = [user_id]
            if model_type:
                query += " AND model_type = ?"
                params.append(model_type)
            query += " ORDER BY updated_at DESC"
            rows = conn.execute(query, params).fetchall()
            result = []
            for r in rows:
                dec_meta = self._dec(user_id, r["meta"] or "") if r["meta"] else "{}"
                try:
                    meta_obj = json.loads(dec_meta) if dec_meta else {}
                except Exception:
                    meta_obj = {}
                result.append({
                    "id": r["id"], "user_id": r["user_id"],
                    "model_type": r["model_type"], "title": r["title"],
                    "content": self._dec(user_id, r["content"] or ""),
                    "meta": meta_obj, "updated_at": r["updated_at"],
                })
            return result
        except Exception:
            logger.exception("查询 tracking 建模结果失败")
            return []
