
# DSN-exp/chatdbmgr.py
# UPD v3_260328

import sqlite3
import logging
import threading
from typing import List, Dict, Optional, Any

DEFAULT_DB_FILE = "chats.db"


class ChatDBManager:
    """
    聊天记录数据库管理器，线程安全（每个线程独立连接）。
    所有方法需传入 user_id 以隔离用户数据。
    """

    def __init__(
        self,
        db_path: str = DEFAULT_DB_FILE,
        logger: Optional[logging.Logger] = None,
    ):
        self.db_path = db_path
        self._local = threading.local()

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
                        role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                        content TEXT NOT NULL,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (chat_id) REFERENCES chats(chat_id) ON DELETE CASCADE
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_chats_user_id ON chats(user_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages(chat_id)")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS memories (
                        memory_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        chat_id INTEGER NOT NULL,
                        round_index INTEGER NOT NULL,
                        summary TEXT NOT NULL,
                        keywords TEXT DEFAULT '',
                        message_start_id INTEGER DEFAULT NULL,
                        message_end_id INTEGER DEFAULT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (chat_id) REFERENCES chats(chat_id) ON DELETE CASCADE
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_chat_id ON memories(chat_id)")
                
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
                conn.execute("CREATE INDEX IF NOT EXISTS idx_task_notifications_user_id ON task_notifications(user_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_task_notifications_task_id ON task_notifications(task_id)")
                
                # 迁移: 为旧数据库补充新列 (v4 memory recall)
                self._migrate_add_column(conn, "memories", "keywords", "TEXT DEFAULT ''")
                self._migrate_add_column(conn, "memories", "message_start_id", "INTEGER DEFAULT NULL")
                self._migrate_add_column(conn, "memories", "message_end_id", "INTEGER DEFAULT NULL")
                self._migrate_add_column(conn, "messages", "round_index", "INTEGER DEFAULT NULL")
                
                conn.commit()
                self.logger.info("数据库表初始化完成")
            except sqlite3.Error as e:
                self.logger.error("初始化数据库表失败: %s", e)
                conn.rollback()
                raise

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
        """保存某轮对话的摘要记忆（含关键词索引和消息范围链接）"""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "INSERT INTO memories (user_id, chat_id, round_index, summary, keywords, message_start_id, message_end_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, chat_id, round_index, summary, keywords, message_start_id, message_end_id),
            )
            conn.commit()
            self.logger.info("保存记忆: chat_id=%d round=%d keywords=%s", chat_id, round_index, keywords[:50] if keywords else "")
            return cursor.lastrowid
        except sqlite3.Error as e:
            self.logger.error("保存记忆失败: %s", e)
            conn.rollback()
            raise

    def get_memories(self, user_id: int, chat_id: int):
        """获取会话的记忆条目，按轮次升序"""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT round_index, summary, keywords, message_start_id, message_end_id, created_at FROM memories "
                "WHERE user_id = ? AND chat_id = ? ORDER BY round_index ASC",
                (user_id, chat_id),
            ).fetchall()
            return [{
                "round_index": r["round_index"],
                "summary": r["summary"],
                "keywords": r["keywords"] or "",
                "message_start_id": r["message_start_id"],
                "message_end_id": r["message_end_id"],
                "created_at": r["created_at"],
            } for r in rows]
        except sqlite3.Error as e:
            self.logger.error("获取记忆条目失败: %s", e)
            raise

    def search_memories(self, user_id: int, chat_id: int, keywords: list[str],
                        count: int = 5, threshold: float = 0.3) -> list[dict]:
        """
        关键词检索记忆，按匹配分数降序返回。
        每个 keyword 对 summary + keywords 字段做 LIKE 匹配，加权计分。
        """
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT memory_id, round_index, summary, keywords, message_start_id, message_end_id, created_at "
                "FROM memories WHERE user_id = ? AND chat_id = ?",
                (user_id, chat_id),
            ).fetchall()

            if not rows:
                return []

            # 计算评分
            total_rounds = max(r["round_index"] for r in rows) if rows else 1
            scored = []
            search_terms = [kw.lower().strip() for kw in keywords if kw.strip()]

            for r in rows:
                summary_lower = (r["summary"] or "").lower()
                kw_lower = (r["keywords"] or "").lower()
                hit_score = 0.0

                for term in search_terms:
                    if term in summary_lower:
                        hit_score += 1.0
                    elif term in kw_lower:
                        hit_score += 0.8

                if hit_score > 0:
                    recency_bonus = 1.0 - (r["round_index"] / (total_rounds + 1))
                    final_score = hit_score * 0.7 + recency_bonus * 0.3
                    if final_score >= threshold:
                        scored.append({
                            "memory_id": r["memory_id"],
                            "round_index": r["round_index"],
                            "summary": r["summary"],
                            "keywords": r["keywords"],
                            "message_start_id": r["message_start_id"],
                            "message_end_id": r["message_end_id"],
                            "created_at": r["created_at"],
                            "score": round(final_score, 3),
                        })

            scored.sort(key=lambda x: x["score"], reverse=True)
            return scored[:count]
        except sqlite3.Error as e:
            self.logger.error("搜索记忆失败: %s", e)
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
                    "content": r["content"],
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

    def get_memory_count(self, user_id: int, chat_id: int) -> int:
        """统计会话记忆条数"""
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM memories WHERE user_id = ? AND chat_id = ?",
                (user_id, chat_id),
            ).fetchone()
            return row["cnt"] if row else 0
        except sqlite3.Error as e:
            self.logger.error("统计记忆条目失败: %s", e)
            raise

    def delete_oldest_memory(self, user_id: int, chat_id: int, n: int = 1) -> int:
        """删除最旧n条记忆"""
        conn = self._get_connection()
        try:
            conn.execute(
                '''DELETE FROM memories WHERE memory_id IN (
                    SELECT memory_id FROM memories WHERE user_id = ? AND chat_id = ? ORDER BY round_index ASC LIMIT ?
                )''',
                (user_id, chat_id, n),
            )
            conn.commit()
            return conn.total_changes
        except sqlite3.Error as e:
            self.logger.error("删除旧记忆失败: %s", e)
            conn.rollback()
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
            for msg in messages:
                role = msg.get("role")
                content = msg.get("content")
                if role not in ("user", "assistant") or not isinstance(content, str):
                    self.logger.warning("跳过无效消息: %s", msg)
                    continue
                conn.execute(
                    "INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)",
                    (chat_id, role, content),
                )
            conn.commit()
            self.logger.info("已保存聊天会话 %d (用户 %d, 消息数: %d)", chat_id, user_id, len(messages))
            return chat_id
        except sqlite3.Error as e:
            self.logger.error("保存聊天历史失败: %s", e)
            conn.rollback()
            raise

    def get_chat_history(self, user_id: int, chat_id: int) -> List[Dict[str, str]]:
        """获取指定聊天会话的所有消息（需验证用户所有权）"""
        conn = self._get_connection()
        try:
            # 先验证该聊天属于该用户
            row = conn.execute(
                "SELECT 1 FROM chats WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id),
            ).fetchone()
            if not row:
                self.logger.warning("用户 %d 无权访问聊天 %d", user_id, chat_id)
                return []

            rows = conn.execute(
                "SELECT role, content FROM messages WHERE chat_id = ? ORDER BY timestamp ASC",
                (chat_id,),
            ).fetchall()
            return [{"role": r["role"], "content": r["content"]} for r in rows]
        except sqlite3.Error as e:
            self.logger.error("获取聊天历史失败: %s", e)
            raise

    def list_chats(self, user_id: int) -> List[Dict[str, Any]]:
        """列出用户的所有聊天会话"""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                """
                SELECT c.chat_id, c.chat_name, c.created_at,
                       COUNT(m.message_id) AS message_count
                FROM chats c
                LEFT JOIN messages m ON c.chat_id = m.chat_id
                WHERE c.user_id = ?
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
                        skip_memory_check: bool = False, round_index: int = None) -> None:
        """
        向指定聊天会话追加消息（需验证用户所有权）。

        :param user_id: 用户ID
        :param chat_id: 聊天会话ID
        :param messages: 消息列表，格式 [{"role": "user"/"assistant", "content": "..."}]
        :param skip_memory_check: 是否跳过记忆化检查（用于系统触发的AI提醒消息）
        :param round_index: 当前对话轮次索引，用于记忆召回时的消息定位
        :raises ValueError: 如果聊天不属于该用户
        :raises sqlite3.Error: 数据库错误
        """
        conn = self._get_connection()
        try:
            # 验证聊天属于该用户
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

                if role not in ("user", "assistant") or not isinstance(content, str):
                    self.logger.warning("跳过无效消息: %s", msg)
                    continue

                # 插入消息到数据库，含 round_index
                conn.execute(
                    "INSERT INTO messages (chat_id, role, content, round_index) VALUES (?, ?, ?, ?)",
                    (chat_id, role, content, round_index),
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
