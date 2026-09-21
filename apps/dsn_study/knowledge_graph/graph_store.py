import json
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("GraphStore")

_SPACING_INTERVALS = [1, 2, 4, 7, 15, 30, 60]  # 间隔复习: 天


class GraphStore:

    def __init__(self, db):
        self._db = db

    # ── 节点 CRUD ──

    def add_node(self, kp_code: str, subject: str, name: str,
                 level: int = 0, parent_code: str = None,
                 aliases: list[str] = None, description: str = "",
                 metadata: dict = None) -> bool:
        conn = self._db._get_connection()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO knowledge_nodes
                   (kp_code, subject, name, aliases, level, parent_code, description, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (kp_code, subject, name,
                 json.dumps(aliases or [], ensure_ascii=False),
                 level, parent_code, description,
                 json.dumps(metadata or {}, ensure_ascii=False)),
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error("添加知识点节点失败: %s", e)
            conn.rollback()
            return False

    def get_node(self, kp_code: str) -> Optional[dict]:
        conn = self._db._get_connection()
        row = conn.execute(
            "SELECT * FROM knowledge_nodes WHERE kp_code = ?", (kp_code,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_node(row)

    def update_node(self, kp_code: str, data: dict) -> bool:
        conn = self._db._get_connection()
        allowed = {"name", "subject", "aliases", "level", "parent_code",
                    "description", "metadata"}
        updates = {k: v for k, v in data.items() if k in allowed}
        if not updates:
            return False
        set_parts = []
        values = []
        for k, v in updates.items():
            if k in ("aliases", "metadata"):
                set_parts.append(f"{k} = ?")
                values.append(json.dumps(v, ensure_ascii=False))
            else:
                set_parts.append(f"{k} = ?")
                values.append(v)
        values.append(kp_code)
        try:
            conn.execute(
                f"UPDATE knowledge_nodes SET {', '.join(set_parts)} WHERE kp_code = ?",
                values,
            )
            conn.commit()
            return conn.total_changes > 0
        except Exception as e:
            logger.error("更新知识点节点失败: %s", e)
            conn.rollback()
            return False

    def delete_node(self, kp_code: str) -> bool:
        conn = self._db._get_connection()
        try:
            conn.execute("DELETE FROM knowledge_edges WHERE source = ? OR target = ?",
                         (kp_code, kp_code))
            conn.execute("DELETE FROM knowledge_nodes WHERE kp_code = ?", (kp_code,))
            conn.execute("DELETE FROM user_knowledge_state WHERE kp_code = ?", (kp_code,))
            conn.commit()
            return conn.total_changes > 0
        except Exception as e:
            logger.error("删除知识点节点失败: %s", e)
            conn.rollback()
            return False

    def get_nodes_by_subject(self, subject: str) -> list[dict]:
        conn = self._db._get_connection()
        rows = conn.execute(
            "SELECT * FROM knowledge_nodes WHERE subject = ? ORDER BY level, name",
            (subject,),
        ).fetchall()
        return [self._row_to_node(r) for r in rows]

    # ── 边 CRUD ──

    def add_edge(self, source: str, target: str, edge_type: str = "related",
                 weight: float = 1.0, description: str = "") -> bool:
        conn = self._db._get_connection()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO knowledge_edges (source, target, edge_type, weight, description) "
                "VALUES (?, ?, ?, ?, ?)",
                (source, target, edge_type, weight, description),
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error("添加知识点边失败: %s", e)
            conn.rollback()
            return False

    def get_edges(self, kp_code: str, edge_type: str = None) -> list[dict]:
        conn = self._db._get_connection()
        query = "SELECT * FROM knowledge_edges WHERE source = ? OR target = ?"
        params = [kp_code, kp_code]
        if edge_type:
            query += " AND edge_type = ?"
            params.append(edge_type)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def delete_edge(self, source: str, target: str, edge_type: str) -> bool:
        conn = self._db._get_connection()
        try:
            conn.execute(
                "DELETE FROM knowledge_edges WHERE source = ? AND target = ? AND edge_type = ?",
                (source, target, edge_type),
            )
            conn.commit()
            return conn.total_changes > 0
        except Exception as e:
            logger.error("删除知识点边失败: %s", e)
            conn.rollback()
            return False

    def get_children(self, kp_code: str) -> list[dict]:
        conn = self._db._get_connection()
        rows = conn.execute(
            "SELECT n.* FROM knowledge_nodes n "
            "JOIN knowledge_edges e ON n.kp_code = e.target "
            "WHERE e.source = ? AND e.edge_type = 'parent_of' "
            "ORDER BY n.level, n.name",
            (kp_code,),
        ).fetchall()
        return [self._row_to_node(r) for r in rows]

    def get_parents(self, kp_code: str) -> list[dict]:
        conn = self._db._get_connection()
        rows = conn.execute(
            "SELECT n.* FROM knowledge_nodes n "
            "JOIN knowledge_edges e ON n.kp_code = e.source "
            "WHERE e.target = ? AND e.edge_type = 'parent_of' "
            "ORDER BY n.level, n.name",
            (kp_code,),
        ).fetchall()
        return [self._row_to_node(r) for r in rows]

    def get_related(self, kp_code: str) -> list[dict]:
        conn = self._db._get_connection()
        kp_codes = set()
        rows = conn.execute(
            "SELECT target as other FROM knowledge_edges WHERE source = ? AND edge_type != 'parent_of' "
            "UNION "
            "SELECT source as other FROM knowledge_edges WHERE target = ? AND edge_type != 'parent_of'",
            (kp_code, kp_code),
        ).fetchall()
        for r in rows:
            kp_codes.add(r["other"])
        if not kp_codes:
            return []
        placeholders = ",".join("?" for _ in kp_codes)
        rows = conn.execute(
            f"SELECT * FROM knowledge_nodes WHERE kp_code IN ({placeholders})",
            list(kp_codes),
        ).fetchall()
        return [self._row_to_node(r) for r in rows]

    # ── 用户知识状态 ──

    def update_user_state(self, user_id: int, kp_code: str, correct: bool) -> None:
        conn = self._db._get_connection()
        try:
            existing = conn.execute(
                "SELECT * FROM user_knowledge_state WHERE user_id = ? AND kp_code = ?",
                (user_id, kp_code),
            ).fetchone()
            if existing:
                total = existing["total_attempts"] + 1
                correct_c = existing["correct_attempts"] + (1 if correct else 0)
                rate = correct_c / total if total > 0 else 0.0
                confidence = min(1.0, rate * (1 + total * 0.1))
                interval_days = _SPACING_INTERVALS[min(total - 1, len(_SPACING_INTERVALS) - 1)]
                next_review = (datetime.now() + timedelta(days=interval_days)).strftime("%Y-%m-%d %H:%M:%S")
                conn.execute(
                    """UPDATE user_knowledge_state SET
                       total_attempts = ?, correct_attempts = ?, correct_rate = ?,
                       confidence = ?, last_practiced = datetime('now'),
                       next_review_at = ?
                       WHERE user_id = ? AND kp_code = ?""",
                    (total, correct_c, rate, confidence, next_review, user_id, kp_code),
                )
            else:
                confidence = 0.8 if correct else 0.2
                interval_days = _SPACING_INTERVALS[0]
                next_review = (datetime.now() + timedelta(days=interval_days)).strftime("%Y-%m-%d %H:%M:%S")
                conn.execute(
                    """INSERT INTO user_knowledge_state
                       (user_id, kp_code, total_attempts, correct_attempts, correct_rate,
                        confidence, last_practiced, next_review_at)
                       VALUES (?, ?, 1, ?, ?, ?, datetime('now'), ?)""",
                    (user_id, kp_code, 1 if correct else 0, 1.0 if correct else 0.0,
                     confidence, next_review),
                )
            conn.commit()
        except Exception as e:
            logger.error("更新用户知识状态失败: %s", e)
            conn.rollback()

    def get_user_state(self, user_id: int, kp_code: str) -> Optional[dict]:
        conn = self._db._get_connection()
        row = conn.execute(
            "SELECT * FROM user_knowledge_state WHERE user_id = ? AND kp_code = ?",
            (user_id, kp_code),
        ).fetchone()
        return dict(row) if row else None

    def get_user_states(self, user_id: int, subject: str = None) -> list[dict]:
        conn = self._db._get_connection()
        query = ("SELECT s.*, n.name as kp_name, n.subject, n.level "
                 "FROM user_knowledge_state s "
                 "JOIN knowledge_nodes n ON s.kp_code = n.kp_code "
                 "WHERE s.user_id = ?")
        params = [user_id]
        if subject:
            query += " AND n.subject = ?"
            params.append(subject)
        query += " ORDER BY s.confidence ASC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_due_reviews(self, user_id: int, limit: int = 10) -> list[dict]:
        conn = self._db._get_connection()
        rows = conn.execute(
            """SELECT s.*, n.name as kp_name, n.subject
               FROM user_knowledge_state s
               JOIN knowledge_nodes n ON s.kp_code = n.kp_code
               WHERE s.user_id = ?
                 AND (s.next_review_at IS NULL OR s.next_review_at <= datetime('now'))
               ORDER BY s.next_review_at ASC LIMIT ?""",
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── 辅助 ──

    @staticmethod
    def _row_to_node(row) -> dict:
        result = dict(row)
        for field in ["aliases", "metadata"]:
            if isinstance(result.get(field), str):
                try:
                    result[field] = json.loads(result[field])
                except (json.JSONDecodeError, TypeError):
                    pass
        return result
