# apps/dsn_study/scripts/migrate_context_v2.py
"""把旧记忆表迁到新的 context_turns / context_facts。

用法：
    python -m apps.dsn_study.scripts.migrate_context_v2 --dry-run   # 只看会迁多少
    python -m apps.dsn_study.scripts.migrate_context_v2 --apply     # 真迁

设计要点：
  * **幂等**：靠 ``context_facts.ref_id`` 唯一（脚本先查后插），重复跑不会重复迁。
  * **旧表只读**：不删不改 ``chat_rounds`` / ``memory_v2``，观察期（≥30 天）后
    再由单独的清理动作处理。
  * **原始轮次**用合成 session_id（``legacy:{chat_id}``）：旧表里没有 session 标识，
    硬造一个比丢掉强 —— 数据仍在、仍可检索，只是与新会话的 session_id 不同源。

来源 → 目标：
    memory_v2(type='memo')  → context_facts(kind='memo',   scope='user')
    memory_v2(type='exp')   → context_facts(kind='summary', scope='session')
    chat_rounds             → context_turns(session_id='legacy:{chat_id}')
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys

DEFAULT_DB = os.environ.get("QUESTION_BANK_DB_PATH",
                            ".dsn/study_question_bank.db")

DDL_TURNS = """
CREATE TABLE IF NOT EXISTS context_turns (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  uid             INTEGER NOT NULL,
  session_id      TEXT    NOT NULL,
  round_index     INTEGER NOT NULL,
  user_msg        TEXT    NOT NULL,
  assistant_reply TEXT    NOT NULL,
  created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE(uid, session_id, round_index)
);
CREATE INDEX IF NOT EXISTS idx_ctx_turns_session
  ON context_turns(uid, session_id, round_index);
"""

DDL_FACTS = """
CREATE TABLE IF NOT EXISTS context_facts (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  uid        INTEGER NOT NULL,
  scope      TEXT NOT NULL,
  kind       TEXT NOT NULL,
  text       TEXT NOT NULL,
  importance REAL NOT NULL DEFAULT 0.5,
  source     TEXT NOT NULL DEFAULT '',
  ref_id     TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ctx_facts_lookup
  ON context_facts(uid, scope, kind, importance DESC, created_at DESC);
"""


def _table_exists(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,)).fetchone()
    return bool(row)


def needs_migration(db_path: str) -> bool:
    """是否还有旧数据没迁。boot 用它决定要不要跑一次迁移。"""
    if not os.path.exists(db_path):
        return False
    try:
        conn = sqlite3.connect(db_path)
        try:
            if not _table_exists(conn, "memory_v2"):
                return False
            old = conn.execute("SELECT COUNT(*) FROM memory_v2").fetchone()[0]
            if not old:
                return False
            if _table_exists(conn, "context_facts"):
                new = conn.execute(
                    "SELECT COUNT(*) FROM context_facts WHERE ref_id != ''").fetchone()[0]
                if new >= old:
                    return False
            return True
        finally:
            conn.close()
    except Exception:
        return False


def migrate(db_path: str, apply: bool = False) -> int:
    if not os.path.exists(db_path):
        print(f"[跳过] 数据库不存在: {db_path}")
        return 0
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if apply:
            conn.executescript(DDL_TURNS)
            conn.executescript(DDL_FACTS)
            conn.commit()
        else:
            # dry-run 也要能写，所以先在内存里建表结构再看
            pass

        moved = {"memo": 0, "summary": 0, "turn": 0}

        # ── 备忘 / 摘要 → context_facts ──
        if _table_exists(conn, "memory_v2"):
            rows = conn.execute(
                "SELECT id, user_id, chat_id, type, round, content, created_at "
                "FROM memory_v2 ORDER BY id").fetchall()
            existing = set()
            if apply and _table_exists(conn, "context_facts"):
                existing = {r[0] for r in conn.execute(
                    "SELECT ref_id FROM context_facts WHERE ref_id != ''")}
            for r in rows:
                if r["type"] == "memo":
                    kind, scope = "memo", "user"
                    ref = f"memo:{r['id']}"
                    source = "user"
                elif r["type"] == "exp":
                    kind, scope = "summary", "session"
                    ref = f"summary:{r['chat_id']}:{r['round']}"
                    source = "llm_summary"
                else:
                    continue
                if apply:
                    if ref in existing:
                        continue
                    conn.execute(
                        "INSERT INTO context_facts "
                        "(uid, scope, kind, text, importance, source, ref_id, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE(?, datetime('now')))",
                        (r["user_id"], scope, kind, r["content"],
                         0.5, source, ref, r["created_at"]))
                    existing.add(ref)
                moved[kind] += 1
            if apply:
                conn.commit()

        # ── 原始轮次 → context_turns ──
        if _table_exists(conn, "chat_rounds"):
            rows = conn.execute(
                "SELECT user_id, chat_id, round_index, user_msg, assistant_reply, "
                "created_at FROM chat_rounds ORDER BY user_id, chat_id, round_index"
            ).fetchall()
            for r in rows:
                if apply:
                    conn.execute(
                        "INSERT OR REPLACE INTO context_turns "
                        "(uid, session_id, round_index, user_msg, assistant_reply, created_at) "
                        "VALUES (?, ?, ?, ?, ?, COALESCE(?, datetime('now')))",
                        (r["user_id"], f"legacy:{r['chat_id']}", r["round_index"],
                         r["user_msg"], r["assistant_reply"], r["created_at"]))
                moved["turn"] += 1
            if apply:
                conn.commit()

        mode = "已写入" if apply else "将要写入"
        print(f"[{mode}] {db_path}")
        print(f"  备忘 memo      : {moved['memo']}")
        print(f"  摘要 summary   : {moved['summary']}")
        print(f"  原始轮次 turn  : {moved['turn']}")
        if not apply:
            print("  （这是 dry-run，加 --apply 才会真正写入）")
        return 0
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="把旧记忆表迁到 context_turns / context_facts")
    parser.add_argument("--db", default=DEFAULT_DB, help="题库库路径")
    parser.add_argument("--apply", action="store_true", help="真正写入（默认 dry-run）")
    args = parser.parse_args(argv)
    return migrate(args.db, apply=args.apply)


if __name__ == "__main__":
    sys.exit(main())
