# apps/dsn_study/context/store.py
# 上下文存储：原始轮次（context_turns）+ 派生事实（context_facts）。
#
# 为什么另起一张表（而不是复用 chat_rounds / memory_v2）：
#   现状同一段对话存了 5 份（chat_rounds / memory_v2 / study_topic_messages /
#   agent.conversations / compressed_chunks），写入时机各不相同，读路径各不相同。
#   新链路只认 context_turns 一份原文，context_facts 存派生事实（摘要/备忘/画像）。
#
# 存储实现要点：
#   - 走 db._get_connection()（dsn_study 的 QuestionBankDBManager 就是这个接口）；
#   - 建表用 CREATE TABLE IF NOT EXISTS（**幂等**），旧库缺列时用 PRAGMA table_info 补列；
#   - 写入**幂等**：record_turn 用 INSERT OR REPLACE（靠唯一键），
#     add_fact 在 ref_id 非空时先查后插（并有唯一索引兜底）。
#
# 依赖方向：只依赖 types，不反向 import budget / kernel。

from __future__ import annotations

import logging
import sqlite3
from .types import TurnContext

logger = logging.getLogger(__name__)


class ContextStore:
    """上下文存储（轮次 + 事实）。

    用法：
        store = ContextStore(db)          # db 需有 _get_connection()
        store.record_turn(turn, "问", "答")
        rows = store.recent_turns(uid, session_id, limit=3)
    """

    def __init__(self, db):
        self._db = db
        # 建表幂等：重复调用不会报错（旧库会自动补列）
        self.init_tables()

    # ── 建表 / 补列 ─────────────────────────────────────────────────

    def init_tables(self) -> None:
        """建表 + 建索引 + 旧库补列（全部幂等，可重复调用）。"""
        conn = self._conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS context_turns (
              id              INTEGER PRIMARY KEY AUTOINCREMENT,
              uid             INTEGER NOT NULL,
              session_id      TEXT    NOT NULL,
              round_index     INTEGER NOT NULL,
              user_msg        TEXT    NOT NULL,
              assistant_reply TEXT    NOT NULL,
              created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
              UNIQUE(uid, session_id, round_index)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS context_facts (
              id          INTEGER PRIMARY KEY AUTOINCREMENT,
              uid         INTEGER NOT NULL,
              scope       TEXT NOT NULL,
              kind        TEXT NOT NULL,
              text        TEXT NOT NULL,
              importance  REAL NOT NULL DEFAULT 0.5,
              source      TEXT NOT NULL DEFAULT '',
              ref_id      TEXT NOT NULL DEFAULT '',
              created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        # 旧库补列：CREATE TABLE IF NOT EXISTS 不会给已存在的表补字段
        self._ensure_columns(conn, "context_turns", {
            "user_msg": "TEXT NOT NULL DEFAULT ''",
            "assistant_reply": "TEXT NOT NULL DEFAULT ''",
            "created_at": "TEXT NOT NULL DEFAULT (datetime('now'))",
        })
        self._ensure_columns(conn, "context_facts", {
            "importance": "REAL NOT NULL DEFAULT 0.5",
            "source": "TEXT NOT NULL DEFAULT ''",
            "ref_id": "TEXT NOT NULL DEFAULT ''",
            "created_at": "TEXT NOT NULL DEFAULT (datetime('now'))",
        })

        # 索引**必须建在补列之后**：旧库缺列时建索引会直接报错
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ctx_turns_session
              ON context_turns(uid, session_id, round_index)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ctx_facts_lookup
              ON context_facts(uid, scope, kind, importance DESC, created_at DESC)
        """)
        # 幂等键唯一索引：ref_id 非空时 (uid, ref_id) 唯一。
        # 旧库里若已有重复数据，建索引会失败 —— 不致命，退化成 Python 层先查后插。
        try:
            conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_ctx_facts_refid
                  ON context_facts(uid, ref_id)
                  WHERE ref_id IS NOT NULL AND ref_id <> ''
            """)
        except sqlite3.Error:
            logger.warning("context_facts 唯一索引创建失败（退化为先查后插）", exc_info=True)
        conn.commit()

    @staticmethod
    def _ensure_columns(conn, table: str, columns: dict) -> None:
        """按 PRAGMA table_info 判断，给旧库补齐缺失的列。"""
        try:
            rows = conn.execute("PRAGMA table_info(%s)" % table).fetchall()
        except sqlite3.Error:
            logger.warning("读取 %s 表结构失败（跳过补列）", table, exc_info=True)
            return
        existing = {row[1] for row in rows}
        for name, ddl in columns.items():
            if name in existing:
                continue
            try:
                conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, name, ddl))
                logger.info("旧库补列：%s.%s", table, name)
            except sqlite3.Error:
                logger.warning("补列失败：%s.%s", table, name, exc_info=True)

    # ── 轮次 ────────────────────────────────────────────────────────

    def record_turn(self, turn: TurnContext, user_msg: str,
                    assistant_reply: str) -> int:
        """记录一轮对话（**幂等**：同 (uid, session_id, round_index) 覆盖写）。"""
        conn = self._conn()
        cursor = conn.execute(
            """INSERT OR REPLACE INTO context_turns
               (uid, session_id, round_index, user_msg, assistant_reply)
               VALUES (?, ?, ?, ?, ?)""",
            (int(turn.uid), turn.session_id or "", int(turn.round_index),
             user_msg or "", assistant_reply or ""),
        )
        conn.commit()
        return int(cursor.lastrowid or 0)

    def recent_turns(self, uid: int, session_id: str, limit: int = 5) -> list[dict]:
        """取最近 N 轮原文，**按轮次升序**返回（对话形态：先旧后新）。"""
        conn = self._conn()
        rows = _fetch_dicts(
            conn,
            """SELECT id, uid, session_id, round_index, user_msg,
                      assistant_reply, created_at
                 FROM context_turns
                WHERE uid = ? AND session_id = ?
                ORDER BY round_index DESC
                LIMIT ?""",
            (int(uid), session_id or "", max(1, int(limit))),
        )
        rows.reverse()   # DB 里是倒序取出来的，转回升序
        return rows

    def count_turns(self, uid: int, session_id: str) -> int:
        """该会话已记录的轮数。"""
        conn = self._conn()
        row = conn.execute(
            "SELECT COUNT(*) FROM context_turns WHERE uid = ? AND session_id = ?",
            (int(uid), session_id or ""),
        ).fetchone()
        return int(row[0]) if row else 0

    # ── 事实 ────────────────────────────────────────────────────────

    def add_fact(self, uid: int, scope: str, kind: str, text: str, *,
                 source: str = "", ref_id: str = "",
                 importance: float = 0.5) -> int:
        """写一条派生事实（摘要 / 备忘 / 画像）。

        **幂等**：ref_id 非空时，先查后插 —— 同一个 (uid, ref_id) 只会有一条。
        返回 fact id（已存在时返回既有 id；ref_id 为空时无法判重，允许重复）。
        """
        conn = self._conn()
        if ref_id:
            found = conn.execute(
                "SELECT id FROM context_facts WHERE uid = ? AND ref_id = ? LIMIT 1",
                (int(uid), ref_id),
            ).fetchone()
            if found:
                return int(found[0])
        try:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO context_facts
                   (uid, scope, kind, text, importance, source, ref_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (int(uid), scope or "", kind or "", text or "",
                 float(importance), source or "", ref_id or ""),
            )
            conn.commit()
            if cursor.rowcount and cursor.lastrowid:
                return int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            conn.rollback()
            logger.info("事实写入冲突（已按幂等处理）：uid=%s ref_id=%s", uid, ref_id)
        if ref_id:
            found = conn.execute(
                "SELECT id FROM context_facts WHERE uid = ? AND ref_id = ? LIMIT 1",
                (int(uid), ref_id),
            ).fetchone()
            if found:
                return int(found[0])
        return 0

    def facts(self, uid: int, scope: str, kind: str, limit: int = 20) -> list[dict]:
        """取事实（按重要度降序，同重要度按新到旧）。"""
        conn = self._conn()
        return _fetch_dicts(
            conn,
            """SELECT id, uid, scope, kind, text, importance, source, ref_id,
                      created_at
                 FROM context_facts
                WHERE uid = ? AND scope = ? AND kind = ?
                ORDER BY importance DESC, created_at DESC, id DESC
                LIMIT ?""",
            (int(uid), scope or "", kind or "", max(1, int(limit))),
        )

    # ── 内部 ────────────────────────────────────────────────────────

    def _conn(self):
        """取连接（db 需提供 _get_connection()，与 QuestionBankDBManager 一致）。"""
        return self._db._get_connection()


def _fetch_dicts(conn, sql: str, params: tuple) -> list[dict]:
    """执行查询并把结果转成 dict 列表。

    不依赖 conn.row_factory —— 有些连接没设 Row工厂（返回 tuple），
    这里按 cursor.description 自己映射列名，两种情况都能用。
    """
    cursor = conn.execute(sql, params)
    columns = [d[0] for d in (cursor.description or [])]
    result: list[dict] = []
    for row in cursor.fetchall():
        values = list(row)
        result.append(dict(zip(columns, values)))
    return result
