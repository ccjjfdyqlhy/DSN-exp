
# DSN-exp/chatdbmgr.py
# UPD v3_260328

import sqlite3
import logging
import re
import threading
from typing import List, Dict, Optional, Any

from crypto_utils import MessageCipher

# Config.py 优先于下面这个，没填配置的时候fallback
DEFAULT_DB_FILE = "chats.db"


def _tokenize(text: str) -> list[str]:
    """混合分词：中文逐字 + 英文按词，过滤停用字符"""
    tokens = []
    for part in re.split(r"(\w+)", text.lower().strip()):
        part = part.strip()
        if not part:
            continue
        if re.match(r"^\w+$", part):
            tokens.append(part)
        else:
            for ch in part:
                if ch.strip() and not re.match(r"^[\s\d\W_]+$", ch):
                    tokens.append(ch)
    return tokens


class ChatDBManager:
    """
    聊天记录数据库管理器，线程安全（每个线程独立连接）。
    所有方法需传入 user_id 以隔离用户数据。
    消息内容使用 AES-256-GCM 加密，密钥由 SHA-256(主密钥 + user_id) 派生。
    """

    def __init__(
        self,
        db_path: str = DEFAULT_DB_FILE,
        logger: Optional[logging.Logger] = None,
    ):
        self.db_path = db_path
        self._local = threading.local()
        self._cipher = MessageCipher()  # 主密钥从 /.dsn/ 自动加载或创建

        # 日志
        if logger:
            self.logger = logger
        else:
            self.logger = logging.getLogger("ChatDBManager")
            # 不再添加StreamHandler，因为根日志记录器已经配置了处理器
            self.logger.setLevel(logging.INFO)

        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """获取当前线程的数据库连接（自动创建）"""
        if not hasattr(self._local, "conn"):
            self._local.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._local.conn.execute("PRAGMA foreign_keys = ON")
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def close_connection(self):
        """关闭当前线程的连接（应在请求结束时调用）"""
        if hasattr(self._local, "conn"):
            self._local.conn.close()
            del self._local.conn

    @staticmethod
    def _migrate_add_column(conn: sqlite3.Connection, table: str, column: str, col_def: str) -> None:
        """安全添加列：仅当列不存在时执行 ALTER TABLE"""
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
            logging.getLogger("ChatDBManager").info("迁移: %s.%s 添加成功", table, column)
        except sqlite3.OperationalError:
            pass  # 列已存在

    @staticmethod
    def _migrate_messages_role(conn: sqlite3.Connection) -> None:
        """迁移: 如果 messages 表 role 列有 CHECK 约束阻止 'system'，则重建表"""
        try:
            conn.execute("INSERT INTO messages (chat_id, role, content) VALUES (-1, 'system', '_migration_test')")
            conn.execute("DELETE FROM messages WHERE chat_id = -1 AND content = '_migration_test'")
            conn.commit()
        except sqlite3.IntegrityError:
            # 旧约束存在，需要迁移
            logger = logging.getLogger("ChatDBManager")
            logger.info("迁移 messages 表: 移除 role CHECK 约束...")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages_new (
                    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    round_index INTEGER DEFAULT NULL,
                    FOREIGN KEY (chat_id) REFERENCES chats(chat_id) ON DELETE CASCADE
                )
            """)
            conn.execute("INSERT INTO messages_new SELECT * FROM messages ORDER BY message_id")
            conn.execute("DROP TABLE messages")
            conn.execute("ALTER TABLE messages_new RENAME TO messages")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages(chat_id)")
            conn.commit()
            logger.info("迁移完成: messages 表现在接受 'system' role")

    def _init_db(self):
        """初始化表结构（线程安全，使用锁）"""
        with threading.Lock():
            conn = self._get_connection()
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        uid INTEGER PRIMARY KEY,
                        nickname TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                # 认证系统扩展列
                self._migrate_add_column(conn, "users", "display_name", "TEXT DEFAULT ''")
                self._migrate_add_column(conn, "users", "is_admin", "INTEGER DEFAULT 0")
                self._migrate_add_column(conn, "users", "littleskin_uid", "INTEGER DEFAULT NULL")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS chats (
                        chat_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        chat_name TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(uid) ON DELETE CASCADE
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS messages (
                        message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (chat_id) REFERENCES chats(chat_id) ON DELETE CASCADE
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_chats_user_id ON chats(user_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages(chat_id)")

                # 任务通知表
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS task_notifications (
                        notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        task_id TEXT NOT NULL,
                        user_id INTEGER NOT NULL,
                        chat_id INTEGER NOT NULL,
                        result TEXT NOT NULL,
                        status TEXT DEFAULT 'unread' CHECK(status IN ('unread', 'read')),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (chat_id) REFERENCES chats(chat_id) ON DELETE CASCADE
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_task_notifications_task_id ON task_notifications(task_id)")
                
                # 迁移: messages 表 round_index 列
                self._migrate_add_column(conn, "messages", "round_index", "INTEGER DEFAULT NULL")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat_round ON messages(chat_id, round_index)")
                
                # 迁移: 移除 messages 表 role 列的 CHECK 约束，允许 'system' role
                self._migrate_messages_role(conn)

                # 人格系统 v2 状态表
                from prompt.personality_v2.persistence import CREATE_PERSONALITY_TABLE
                conn.execute(CREATE_PERSONALITY_TABLE)

                # 人格系统 v3 持久层表
                try:
                    from prompt.personality_v3.persistence import ALL_TABLES as V3_TABLES
                    for _name, _sql in V3_TABLES:
                        conn.execute(_sql)
                except Exception:
                    pass  # V3 可能未完全部署

                # 用户印象表
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS user_impressions (
                        impression_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        uid INTEGER NOT NULL,
                        category TEXT NOT NULL DEFAULT '其他',
                        content TEXT NOT NULL,
                        confidence REAL NOT NULL DEFAULT 0.5,
                        source TEXT NOT NULL DEFAULT 'inferred',
                        evidence TEXT DEFAULT '',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (uid) REFERENCES users(uid) ON DELETE CASCADE
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_impressions_uid ON user_impressions(uid)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_impressions_category ON user_impressions(category)")

                # 分层认证系统表
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS auth_credentials (
                        credential_id TEXT PRIMARY KEY,
                        uid INTEGER NOT NULL,
                        public_key BLOB NOT NULL DEFAULT '',
                        sign_count INTEGER DEFAULT 0,
                        transports TEXT DEFAULT '',
                        device_name TEXT DEFAULT '',
                        created_at TEXT DEFAULT (datetime('now')),
                        FOREIGN KEY (uid) REFERENCES users(uid) ON DELETE CASCADE
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS auth_sessions (
                        session_id TEXT PRIMARY KEY,
                        uid INTEGER NOT NULL,
                        device_token_hash TEXT NOT NULL DEFAULT '',
                        device_name TEXT DEFAULT '',
                        user_agent TEXT DEFAULT '',
                        is_trusted INTEGER DEFAULT 0,
                        ip_address TEXT DEFAULT '',
                        created_at TEXT DEFAULT (datetime('now')),
                        last_used_at TEXT DEFAULT (datetime('now')),
                        expires_at TEXT,
                        revoked INTEGER DEFAULT 0,
                        FOREIGN KEY (uid) REFERENCES users(uid) ON DELETE CASCADE
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS auth_totp (
                        uid INTEGER PRIMARY KEY,
                        secret TEXT NOT NULL DEFAULT '',
                        enabled INTEGER DEFAULT 0,
                        created_at TEXT DEFAULT (datetime('now')),
                        FOREIGN KEY (uid) REFERENCES users(uid) ON DELETE CASCADE
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS auth_pairing_codes (
                        code TEXT PRIMARY KEY,
                        uid INTEGER,
                        expires_at TEXT NOT NULL DEFAULT '',
                        used INTEGER DEFAULT 0,
                        created_at TEXT DEFAULT (datetime('now'))
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS auth_api_keys (
                        key_hash TEXT PRIMARY KEY,
                        uid INTEGER NOT NULL,
                        name TEXT NOT NULL DEFAULT '',
                        scopes TEXT NOT NULL DEFAULT 'read',
                        ip_whitelist TEXT DEFAULT '',
                        created_at TEXT DEFAULT (datetime('now')),
                        last_used_at TEXT,
                        expires_at TEXT,
                        revoked INTEGER DEFAULT 0,
                        FOREIGN KEY (uid) REFERENCES users(uid) ON DELETE CASCADE
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS system_kv (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL DEFAULT '',
                        updated_at TEXT DEFAULT (datetime('now'))
                    )
                """)
                
                conn.commit()
                self.logger.info("数据库表初始化完成")
            except sqlite3.Error as e:
                self.logger.error("初始化数据库表失败: %s", e)
                conn.rollback()
                raise

    # ═══════════════════════════════════════════
    # 用户印象系统 (User Impressions)
    # ═══════════════════════════════════════════

    def add_impression(self, uid: int, category: str, content: str,
                       confidence: float = 0.5, source: str = "inferred",
                       evidence: str = "") -> int:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "INSERT INTO user_impressions (uid, category, content, confidence, source, evidence) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (uid, category, content, confidence, source, evidence),
            )
            conn.commit()
            return cursor.lastrowid
        except sqlite3.Error as e:
            self.logger.error("添加印象失败: %s", e)
            conn.rollback()
            raise

    def update_impression(self, impression_id: int, **fields) -> bool:
        conn = self._get_connection()
        allowed = {"category", "content", "confidence", "source", "evidence"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        updates["updated_at"] = "datetime('now')"
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [impression_id]
        try:
            conn.execute(
                f"UPDATE user_impressions SET {set_clause} WHERE impression_id = ?",
                values,
            )
            conn.commit()
            return conn.total_changes > 0
        except sqlite3.Error as e:
            self.logger.error("更新印象失败: %s", e)
            conn.rollback()
            return False

    def delete_impression(self, impression_id: int) -> bool:
        conn = self._get_connection()
        try:
            conn.execute("DELETE FROM user_impressions WHERE impression_id = ?", (impression_id,))
            conn.commit()
            return conn.total_changes > 0
        except sqlite3.Error as e:
            self.logger.error("删除印象失败: %s", e)
            conn.rollback()
            return False

    def get_impressions(self, uid: int, category: str = None,
                        min_confidence: float = 0.0, limit: int = 50) -> list[dict]:
        conn = self._get_connection()
        try:
            query = "SELECT impression_id, uid, category, content, confidence, source, evidence, created_at, updated_at FROM user_impressions WHERE uid = ?"
            params: list = [uid]
            if category:
                query += " AND category = ?"
                params.append(category)
            if min_confidence > 0.0:
                query += " AND confidence >= ?"
                params.append(min_confidence)
            query += " ORDER BY confidence DESC, updated_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.Error as e:
            self.logger.error("查询印象失败: %s", e)
            return []

    def count_impressions(self, uid: int) -> int:
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM user_impressions WHERE uid = ?", (uid,)
            ).fetchone()
            return row["cnt"] if row else 0
        except sqlite3.Error as e:
            self.logger.error("统计印象失败: %s", e)
            return 0

    def get_impression_categories(self, uid: int) -> list[str]:
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT DISTINCT category FROM user_impressions WHERE uid = ? ORDER BY category",
                (uid,)
            ).fetchall()
            return [r["category"] for r in rows]
        except sqlite3.Error as e:
            self.logger.error("获取印象分类失败: %s", e)
            return []

    def add_or_update_user(self, uid: int, nickname: str) -> None:
        """添加或更新用户信息"""
        conn = self._get_connection()
        try:
            conn.execute(
                "INSERT INTO users (uid, nickname) VALUES (?, ?) "
                "ON CONFLICT(uid) DO UPDATE SET nickname = excluded.nickname",
                (uid, nickname),
            )
            conn.commit()
            self.logger.info("用户 %d (%s) 已同步", uid, nickname)
        except sqlite3.Error as e:
            self.logger.error("添加/更新用户失败: %s", e)
            conn.rollback()
            raise

    def save_memory(self, user_id: int, chat_id: int, round_index: int, summary: str,
                    keywords: str = "", message_start_id: int = None, message_end_id: int = None) -> int:
        """保存摘要记忆到 memory_v2（兼容旧接口）"""
        conn = self._get_connection()
        try:
            encrypted = self._cipher.encrypt(user_id, summary)
            cursor = conn.execute(
                "INSERT INTO memory_v2 (user_id, chat_id, type, round, content) "
                "VALUES (?, ?, 'exp', ?, ?)",
                (user_id, chat_id, round_index, encrypted),
            )
            conn.commit()
            self.logger.info("保存记忆(v2): chat_id=%d round=%d", chat_id, round_index)
            return cursor.lastrowid
        except sqlite3.Error as e:
            self.logger.error("保存记忆失败: %s", e)
            conn.rollback()
            raise

    def get_memories(self, user_id: int, chat_id: int) -> list[dict]:
        """获取会话的记忆条目（基于 memory_v2），按轮次升序"""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT id, round, content, created_at FROM memory_v2 "
                "WHERE user_id = ? AND chat_id = ? AND type = 'exp' ORDER BY round ASC, id ASC",
                (user_id, chat_id),
            ).fetchall()
            return [{
                "memory_id": r["id"],
                "round_index": r["round"],
                "summary": self._cipher.decrypt(user_id, r["content"]),
                "keywords": "",
                "message_start_id": None,
                "message_end_id": None,
                "created_at": r["created_at"],
            } for r in rows]
        except sqlite3.Error as e:
            self.logger.error("获取记忆条目失败: %s", e)
            raise

    def get_messages_by_rounds(self, user_id: int, chat_id: int,
                               round_indices: list[int]) -> dict[int, list[dict]]:
        """
        按轮次还原原始对话消息。
        返回 {round_index: [{role, content, timestamp}, ...]}。
        """
        conn = self._get_connection()
        try:
            result: dict[int, list[dict]] = {}
            if not round_indices:
                return result

            placeholders = ",".join("?" for _ in round_indices)
            rows = conn.execute(
                f"SELECT round_index, role, content, timestamp FROM messages "
                f"WHERE chat_id = ? AND round_index IN ({placeholders}) "
                f"ORDER BY round_index ASC, message_id ASC",
                [chat_id] + list(round_indices),
            ).fetchall()

            for r in rows:
                ri = r["round_index"]
                if ri is None:
                    continue
                if ri not in result:
                    result[ri] = []
                result[ri].append({
                    "role": r["role"],
                    "content": self._cipher.decrypt(user_id, r["content"]),
                    "timestamp": r["timestamp"],
                })

            return result
        except sqlite3.Error as e:
            self.logger.error("按轮次获取消息失败: %s", e)
            raise

    def get_last_message_ids(self, chat_id: int, count: int = 2) -> tuple[int | None, int | None]:
        """获取指定聊天最近 N 条消息的 message_id 范围 (min_id, max_id)"""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT message_id FROM messages WHERE chat_id = ? ORDER BY message_id DESC LIMIT ?",
                (chat_id, count),
            ).fetchall()
            if not rows:
                return None, None
            ids = [r["message_id"] for r in rows]
            return min(ids), max(ids)
        except sqlite3.Error as e:
            self.logger.error("获取最后消息ID失败: %s", e)
            raise

    def get_next_round_index(self, chat_id: int) -> int:
        """获取下一个可用的 round_index（基于消息表中最大 round_index 计算）"""
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT MAX(round_index) FROM messages WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
            max_ri = row[0] if row and row[0] is not None else 0
            return max_ri + 1
        except sqlite3.Error as e:
            self.logger.error("获取下一个 round_index 失败: %s", e)
            raise

    def create_chat(self, user_id: int, chat_name: str) -> int:
        """创建新聊天会话"""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "INSERT INTO chats (user_id, chat_name) VALUES (?, ?)",
                (user_id, chat_name),
            )
            conn.commit()
            return cursor.lastrowid
        except sqlite3.Error as e:
            self.logger.error("创建聊天会话失败: %s", e)
            conn.rollback()
            raise

    def save_chat_history(
        self,
        user_id: int,
        chat_name: str,
        messages: List[Dict[str, str]],
    ) -> int:
        """保存完整聊天历史（自动创建新会话）"""
        conn = self._get_connection()
        try:
            conn.execute("BEGIN")
            cursor = conn.execute(
                "INSERT INTO chats (user_id, chat_name) VALUES (?, ?)",
                (user_id, chat_name),
            )
            chat_id = cursor.lastrowid
            batch = []
            for msg in messages:
                role = msg.get("role")
                content = msg.get("content")
                if role not in ("user", "assistant", "system") or not isinstance(content, str):
                    self.logger.warning("跳过无效消息: %s", msg)
                    continue
                encrypted = self._cipher.encrypt(user_id, content)
                batch.append((chat_id, role, encrypted))
            if batch:
                conn.executemany(
                    "INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)",
                    batch,
                )
            conn.commit()
            self.logger.info("已保存聊天会话 %d (用户 %d, 消息数: %d)", chat_id, user_id, len(messages))
            return chat_id
        except sqlite3.Error as e:
            self.logger.error("保存聊天历史失败: %s", e)
            conn.rollback()
            raise

    def get_chat_history(self, user_id: int, chat_id: int) -> List[Dict[str, str]]:
        """获取指定聊天会话的所有消息（需验证用户所有权，系统内部聊天拒绝）"""
        conn = self._get_connection()
        try:
            # 先验证该聊天属于该用户且非系统聊天
            row = conn.execute(
                "SELECT 1 FROM chats WHERE chat_id = ? AND user_id = ? AND chat_name != '__steward__'",
                (chat_id, user_id),
            ).fetchone()
            if not row:
                self.logger.warning("用户 %d 无权访问聊天 %d", user_id, chat_id)
                return []

            rows = conn.execute(
                "SELECT role, content FROM messages WHERE chat_id = ? ORDER BY timestamp ASC",
                (chat_id,),
            ).fetchall()
            return [{"role": r["role"], "content": self._cipher.decrypt(user_id, r["content"])} for r in rows]
        except sqlite3.Error as e:
            self.logger.error("获取聊天历史失败: %s", e)
            raise

    def list_chats(self, user_id: int) -> List[Dict[str, Any]]:
        """列出用户的所有聊天会话（排除系统内部聊天）"""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                """
                SELECT c.chat_id, c.chat_name, c.created_at,
                       COUNT(m.message_id) AS message_count
                FROM chats c
                LEFT JOIN messages m ON c.chat_id = m.chat_id
                WHERE c.user_id = ? AND c.chat_name != '__steward__'
                GROUP BY c.chat_id
                ORDER BY c.created_at DESC
                """,
                (user_id,),
            ).fetchall()
            return [
                {
                    "chat_id": r["chat_id"],
                    "chat_name": r["chat_name"],
                    "created_at": r["created_at"],
                    "message_count": r["message_count"],
                }
                for r in rows
            ]
        except sqlite3.Error as e:
            self.logger.error("列出聊天会话失败: %s", e)
            raise

    def replace_last_assistant(self, user_id: int, chat_id: int, new_content: str) -> bool:
        """用新内容替换聊天中最后一条助手消息（用于 Agent 循环更新回复）"""
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT message_id FROM messages WHERE chat_id = ? AND role = 'assistant' "
                "ORDER BY message_id DESC LIMIT 1",
                (chat_id,),
            ).fetchone()
            if not row:
                return False
            encrypted = self._cipher.encrypt(user_id, new_content)
            conn.execute(
                "UPDATE messages SET content = ? WHERE message_id = ?",
                (encrypted, row["message_id"]),
            )
            conn.commit()
            return True
        except sqlite3.Error as e:
            self.logger.error("替换最后助手消息失败: %s", e)
            conn.rollback()
            return False

    def delete_chat(self, user_id: int, chat_id: int) -> bool:
        """删除聊天会话（需验证所有权）"""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM chats WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            self.logger.error("删除聊天会话失败: %s", e)
            conn.rollback()
            raise

    def append_messages(self, user_id: int, chat_id: int, messages: List[Dict[str, str]],
                        skip_memory_check: bool = False, round_index: int = None,
                        skip_ownership_check: bool = False) -> None:
        """
        向指定聊天会话追加消息（需验证用户所有权）。

        :param user_id: 用户ID
        :param chat_id: 聊天会话ID
        :param messages: 消息列表，格式 [{"role": "user"/"assistant", "content": "..."}]
        :param skip_memory_check: 是否跳过记忆化检查（用于系统触发的AI提醒消息）
        :param round_index: 当前对话轮次索引，用于记忆召回时的消息定位
        :param skip_ownership_check: 跳过所有权验证（用于系统内部调用）
        :raises ValueError: 如果聊天不属于该用户
        :raises sqlite3.Error: 数据库错误
        """
        conn = self._get_connection()
        try:
            # 验证聊天属于该用户（系统内部调用可跳过）
            if not skip_ownership_check:
                row = conn.execute(
                    "SELECT 1 FROM chats WHERE chat_id = ? AND user_id = ?",
                    (chat_id, user_id),
                ).fetchone()
                if not row:
                    raise ValueError(f"聊天 {chat_id} 不存在或不属于用户 {user_id}")

            for msg in messages:
                role = msg.get("role")
                content = msg.get("content")
                skip_memory = msg.get("skip_memory", False) or skip_memory_check

                if role not in ("user", "assistant", "system") or not isinstance(content, str):
                    self.logger.warning("跳过无效消息: %s", msg)
                    continue

                # 加密内容后插入数据库，含 round_index
                encrypted = self._cipher.encrypt(user_id, content)
                conn.execute(
                    "INSERT INTO messages (chat_id, role, content, round_index) VALUES (?, ?, ?, ?)",
                    (chat_id, role, encrypted, round_index),
                )

                # 如果消息标记为跳过记忆化，记录日志
                if skip_memory:
                    self.logger.info("消息标记为跳过记忆化: role=%s, content_preview=%s", role, content[:50])

            conn.commit()
            self.logger.info("向聊天 %d 追加 %d 条消息 (round=%s)", chat_id, len(messages), round_index)
        except sqlite3.Error as e:
            self.logger.error("追加消息失败: %s", e)
            conn.rollback()
            raise

    def save_kv(self, key: str, value: str) -> bool:
        conn = self._get_connection()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO system_kv (key, value, updated_at) VALUES (?, ?, datetime('now'))",
                (key, value),
            )
            conn.commit()
            return True
        except sqlite3.Error as e:
            self.logger.error("保存 KV 失败: %s", e)
            conn.rollback()
            return False

    def load_kv(self, key: str) -> str:
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT value FROM system_kv WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else ""
        except sqlite3.Error as e:
            self.logger.error("加载 KV 失败: %s", e)
            return ""
