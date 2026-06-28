# db/question_bank.py
# 题库专属数据库管理器 — 独立、不加密、可移植

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger("QuestionBankDB")

DEFAULT_DB_DIR = ".dsn"
DEFAULT_DB_NAME = "question_bank.db"


class QuestionBankDBManager:
    """
    题库专属数据库管理器。

    - 独立 SQLite 文件，不依赖主聊天数据库
    - 不加密，便于移植和调试
    - 线程安全（每线程独立连接）
    """

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            project_root = Path(__file__).resolve().parent.parent
            db_path = str(project_root / DEFAULT_DB_DIR / DEFAULT_DB_NAME)
        self.db_path = db_path
        self._local = threading.local()
        self._init_lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            self._local.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def close_connection(self):
        if hasattr(self._local, "conn"):
            self._local.conn.close()
            del self._local.conn

    def _init_db(self):
        with self._init_lock:
            conn = self._get_connection()
            try:
                # ── 科目表 ──
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS subjects (
                        subject_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                        name          TEXT UNIQUE NOT NULL,
                        code          TEXT UNIQUE NOT NULL,
                        icon          TEXT DEFAULT '',
                        typical_score INTEGER DEFAULT 100,
                        exam_duration INTEGER DEFAULT 120,
                        is_active     INTEGER DEFAULT 1,
                        created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                # ── 题型表 ──
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS question_types (
                        type_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                        name         TEXT NOT NULL,
                        subtype      TEXT DEFAULT '',
                        scoring_mode TEXT DEFAULT 'exact',
                        created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(name, subtype)
                    )
                """)
                # ── 科目模板表 ──
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS subject_templates (
                        template_id   INTEGER PRIMARY KEY AUTOINCREMENT,
                        name          TEXT UNIQUE NOT NULL,
                        description   TEXT DEFAULT '',
                        content       TEXT NOT NULL,
                        is_builtin    INTEGER DEFAULT 0,
                        created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                # ── 题目表 ──
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS questions (
                        question_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                        subject_id       INTEGER NOT NULL,
                        type_id          INTEGER NOT NULL,
                        source           TEXT DEFAULT '',
                        difficulty       INTEGER DEFAULT 3,
                        content          TEXT NOT NULL,
                        options          TEXT DEFAULT '[]',
                        answer           TEXT NOT NULL,
                        explanation      TEXT DEFAULT '',
                        tags             TEXT DEFAULT '[]',
                        knowledge_points TEXT DEFAULT '[]',
                        metadata         TEXT DEFAULT '{}',
                        created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        version          INTEGER DEFAULT 1,
                        FOREIGN KEY (subject_id) REFERENCES subjects(subject_id),
                        FOREIGN KEY (type_id)    REFERENCES question_types(type_id)
                    )
                """)
                # ── 知识点引用表 ──
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS knowledge_point_refs (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        question_id INTEGER NOT NULL,
                        kp_code     TEXT NOT NULL,
                        weight      REAL DEFAULT 1.0,
                        FOREIGN KEY (question_id) REFERENCES questions(question_id)
                    )
                """)
                # ── 错题记录表 (user_id 为纯整数，不引用 users 表) ──
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS error_logs (
                        log_id        INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id       INTEGER NOT NULL,
                        question_id   INTEGER NOT NULL,
                        attempt_count INTEGER DEFAULT 1,
                        user_answer   TEXT DEFAULT '',
                        error_type    TEXT DEFAULT '',
                        error_reason  TEXT DEFAULT '',
                        created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        mastered      INTEGER DEFAULT 0,
                        mastered_at   TIMESTAMP NULL,
                        FOREIGN KEY (question_id) REFERENCES questions(question_id)
                    )
                """)
                # ── 试卷表 ──
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS exam_papers (
                        paper_id       INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id        INTEGER NOT NULL,
                        title          TEXT NOT NULL,
                        subject_id     INTEGER NOT NULL,
                        difficulty     INTEGER DEFAULT 3,
                        question_ids   TEXT NOT NULL,
                        total_score    INTEGER DEFAULT 100,
                        time_limit_min INTEGER DEFAULT 120,
                        source         TEXT DEFAULT 'composed',
                        status         TEXT DEFAULT 'draft',
                        created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (subject_id) REFERENCES subjects(subject_id)
                    )
                """)
                # ── 考试结果表 ──
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS exam_results (
                        result_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                        exam_id      INTEGER NOT NULL,
                        user_id      INTEGER NOT NULL,
                        answers      TEXT NOT NULL,
                        score        REAL NOT NULL,
                        max_score    REAL NOT NULL,
                        duration_sec INTEGER DEFAULT 0,
                        started_at   TIMESTAMP,
                        submitted_at TIMESTAMP,
                        details      TEXT DEFAULT '{}'
                    )
                """)
                # ── 考试会话表 ──
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS exam_sessions (
                        session_id      TEXT PRIMARY KEY,
                        user_id         INTEGER NOT NULL,
                        paper_id        INTEGER,
                        status          TEXT DEFAULT 'idle',
                        config          TEXT DEFAULT '{}',
                        answers         TEXT DEFAULT '{}',
                        score           REAL,
                        max_score       REAL,
                        started_at      TIMESTAMP,
                        submitted_at    TIMESTAMP,
                        time_limit_sec  INTEGER,
                        remaining_sec   INTEGER,
                        auto_submitted  INTEGER DEFAULT 0,
                        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (paper_id) REFERENCES exam_papers(paper_id)
                    )
                """)
                # ── 知识图谱节点表 ──
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS knowledge_nodes (
                        kp_code     TEXT PRIMARY KEY,
                        subject     TEXT NOT NULL,
                        name        TEXT NOT NULL,
                        aliases     TEXT DEFAULT '[]',
                        level       INTEGER DEFAULT 0,
                        parent_code TEXT,
                        description TEXT DEFAULT '',
                        metadata    TEXT DEFAULT '{}',
                        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                # ── 知识图谱边表 ──
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS knowledge_edges (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        source      TEXT NOT NULL,
                        target      TEXT NOT NULL,
                        edge_type   TEXT NOT NULL,
                        weight      REAL DEFAULT 1.0,
                        description TEXT DEFAULT '',
                        UNIQUE(source, target, edge_type),
                        FOREIGN KEY (source) REFERENCES knowledge_nodes(kp_code),
                        FOREIGN KEY (target) REFERENCES knowledge_nodes(kp_code)
                    )
                """)
                # ── 用户知识点掌握状态表 ──
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS user_knowledge_state (
                        id               INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id          INTEGER NOT NULL,
                        kp_code          TEXT NOT NULL,
                        total_attempts   INTEGER DEFAULT 0,
                        correct_attempts INTEGER DEFAULT 0,
                        correct_rate     REAL DEFAULT 0.0,
                        last_practiced   TIMESTAMP,
                        confidence       REAL DEFAULT 0.0,
                        next_review_at   TIMESTAMP,
                        UNIQUE(user_id, kp_code),
                        FOREIGN KEY (kp_code) REFERENCES knowledge_nodes(kp_code)
                    )
                """)
                # ── 索引 ──
                conn.execute("CREATE INDEX IF NOT EXISTS idx_q_subject   ON questions(subject_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_q_type      ON questions(type_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_el_user     ON error_logs(user_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_el_question ON error_logs(question_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_ep_user     ON exam_papers(user_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_er_exam     ON exam_results(exam_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_ke_source   ON knowledge_edges(source)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_ke_target   ON knowledge_edges(target)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_ks_user     ON user_knowledge_state(user_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_ks_kp       ON user_knowledge_state(kp_code)")
                # ── 预置题型 ──
                conn.execute("""
                    INSERT OR IGNORE INTO question_types (name, subtype, scoring_mode) VALUES
                        ('选择题', '单选', 'exact'),
                        ('选择题', '多选', 'exact'),
                        ('填空题', '填空', 'keyword'),
                        ('解答题', '计算', 'llm'),
                        ('解答题', '证明', 'llm'),
                        ('解答题', '简答', 'llm'),
                        ('判断题', '判断', 'exact'),
                        ('作文题', '作文', 'llm'),
                        ('阅读理解', '阅读', 'llm')
                """)
                conn.commit()
                logger.info("题库数据库初始化完成: %s", self.db_path)
            except Exception as e:
                logger.error("题库数据库初始化失败: %s", e)
                conn.rollback()
                raise

    # ── 数据迁移 ──

    def migrate_from_main_db(self, main_db_path: str) -> dict:
        """
        从主聊天数据库迁移题库数据到当前独立数据库。
        已存在的数据不会重复插入（基于主键去重）。
        返回各表迁移的行数。
        """
        if not os.path.exists(main_db_path):
            return {"error": f"主数据库不存在: {main_db_path}"}

        old_conn = sqlite3.connect(main_db_path)
        old_conn.row_factory = sqlite3.Row
        new_conn = self._get_connection()

        # (表名, 是否有自增主键, 主键列名)
        QB_TABLES = [
            ("subjects",             True,  "subject_id"),
            ("question_types",       True,  "type_id"),
            ("subject_templates",    True,  "template_id"),
            ("questions",            True,  "question_id"),
            ("knowledge_point_refs", True,  "id"),
            ("error_logs",           True,  "log_id"),
            ("exam_papers",          True,  "paper_id"),
            ("exam_results",         True,  "result_id"),
            ("exam_sessions",        False, "session_id"),
            ("knowledge_nodes",      False, "kp_code"),
            ("knowledge_edges",      True,  "id"),
            ("user_knowledge_state", True,  "id"),
        ]

        stats = {}
        try:
            for table, has_auto_pk, pk_col in QB_TABLES:
                try:
                    old_rows = old_conn.execute(f"SELECT * FROM {table}").fetchall()
                except sqlite3.OperationalError:
                    stats[table] = "表不存在，跳过"
                    continue

                if not old_rows:
                    stats[table] = 0
                    continue

                # 获取列名
                columns = [desc[0] for desc in old_conn.execute(f"SELECT * FROM {table} LIMIT 0").description]
                placeholders = ",".join(["?"] * len(columns))
                col_names = ",".join(columns)

                migrated = 0
                for row in old_rows:
                    values = [row[col] for col in columns]
                    try:
                        if has_auto_pk:
                            # 自增主键：检查是否已存在
                            exists = new_conn.execute(
                                f"SELECT 1 FROM {table} WHERE {pk_col} = ?", (row[pk_col],)
                            ).fetchone()
                            if exists:
                                continue
                            new_conn.execute(
                                f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})",
                                values,
                            )
                        else:
                            # 非自增主键：用 INSERT OR IGNORE
                            new_conn.execute(
                                f"INSERT OR IGNORE INTO {table} ({col_names}) VALUES ({placeholders})",
                                values,
                            )
                        migrated += 1
                    except sqlite3.IntegrityError:
                        pass  # 跳过重复数据

                new_conn.commit()
                stats[table] = migrated

            old_conn.close()
            logger.info("题库数据迁移完成: %s", stats)
            return stats

        except Exception as e:
            old_conn.close()
            logger.error("迁移失败: %s", e)
            return {"error": str(e)}
