import json
import logging
from typing import Optional

logger = logging.getLogger("QuestionStore")


class QuestionStore:

    def __init__(self, db):
        self._db = db

    def create_question(self, data: dict) -> int:
        conn = self._db._get_connection()
        try:
            cursor = conn.execute(
                """INSERT INTO questions
                   (subject_id, type_id, source, difficulty, content, options,
                    answer, explanation, tags, knowledge_points, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    data.get("subject_id", 0),
                    data.get("type_id", 0),
                    data.get("source", "manual"),
                    data.get("difficulty", 3),
                    data.get("content", ""),
                    json.dumps(data.get("options", []), ensure_ascii=False),
                    json.dumps(data.get("answer", ""), ensure_ascii=False),
                    data.get("explanation", ""),
                    json.dumps(data.get("tags", []), ensure_ascii=False),
                    json.dumps(data.get("knowledge_points", []), ensure_ascii=False),
                    json.dumps(data.get("metadata", {}), ensure_ascii=False),
                ),
            )
            conn.commit()
            qid = cursor.lastrowid
            logger.info("题目创建成功: id=%d", qid)
            return qid
        except Exception as e:
            logger.error("创建题目失败: %s", e)
            conn.rollback()
            raise

    def get_question(self, question_id: int) -> Optional[dict]:
        conn = self._db._get_connection()
        row = conn.execute(
            "SELECT * FROM questions WHERE question_id = ?", (question_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_question(row)

    def update_question(self, question_id: int, data: dict) -> bool:
        conn = self._db._get_connection()
        try:
            fields = []
            values = []
            for key in ["subject_id", "type_id", "source", "difficulty", "content",
                         "explanation"]:
                if key in data:
                    fields.append(f"{key} = ?")
                    values.append(data[key])
            for key in ["options", "tags", "knowledge_points", "metadata"]:
                if key in data:
                    fields.append(f"{key} = ?")
                    values.append(json.dumps(data[key], ensure_ascii=False))
            if "answer" in data:
                fields.append("answer = ?")
                values.append(json.dumps(data["answer"], ensure_ascii=False))
            if not fields:
                return False
            fields.append("updated_at = CURRENT_TIMESTAMP")
            fields.append("version = version + 1")
            values.append(question_id)
            conn.execute(
                f"UPDATE questions SET {', '.join(fields)} WHERE question_id = ?",
                values,
            )
            conn.commit()
            return conn.total_changes > 0
        except Exception as e:
            logger.error("更新题目失败: %s", e)
            conn.rollback()
            return False

    def delete_question(self, question_id: int) -> bool:
        conn = self._db._get_connection()
        try:
            conn.execute("DELETE FROM questions WHERE question_id = ?", (question_id,))
            conn.execute(
                "DELETE FROM knowledge_point_refs WHERE question_id = ?", (question_id,)
            )
            conn.execute(
                "DELETE FROM error_logs WHERE question_id = ?", (question_id,)
            )
            conn.commit()
            return conn.total_changes > 0
        except Exception as e:
            logger.error("删除题目失败: %s", e)
            conn.rollback()
            return False

    def search_questions(
        self,
        subject: str = None,
        type_id: int = None,
        difficulty: int = None,
        tags: list[str] = None,
        knowledge_points: list[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]:
        conn = self._db._get_connection()
        query = "SELECT q.* FROM questions q"
        conditions = []
        params = []

        if subject:
            query += " JOIN subjects s ON q.subject_id = s.subject_id"
            conditions.append("s.code = ?")
            params.append(subject)

        if type_id:
            conditions.append("q.type_id = ?")
            params.append(type_id)

        if difficulty:
            conditions.append("q.difficulty = ?")
            params.append(difficulty)

        if tags:
            tag_conditions = []
            for tag in tags:
                tag_conditions.append("q.tags LIKE ?")
                params.append(f'%"{tag}"%')
            conditions.append("(" + " OR ".join(tag_conditions) + ")")

        if knowledge_points:
            kp_conditions = []
            for kp in knowledge_points:
                kp_conditions.append("q.knowledge_points LIKE ?")
                params.append(f'%"{kp}"%')
            conditions.append("(" + " OR ".join(kp_conditions) + ")")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY q.question_id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        return [self._row_to_question(r) for r in rows]

    def get_questions_by_ids(self, ids: list[int]) -> list[dict]:
        if not ids:
            return []
        conn = self._db._get_connection()
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT * FROM questions WHERE question_id IN ({placeholders})",
            ids,
        ).fetchall()
        result = [self._row_to_question(r) for r in rows]
        id_order = {qid: i for i, qid in enumerate(ids)}
        result.sort(key=lambda q: id_order.get(q["question_id"], 999))
        return result

    def find_by_content(self, content: str, subject: str = None) -> Optional[dict]:
        """按题目内容精确查重（供批量导入去重）。"""
        conn = self._db._get_connection()
        if subject:
            row = conn.execute(
                "SELECT q.* FROM questions q "
                "JOIN subjects s ON q.subject_id = s.subject_id "
                "WHERE q.content = ? AND s.code = ? LIMIT 1",
                (content, subject),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM questions WHERE content = ? LIMIT 1",
                (content,),
            ).fetchone()
        return self._row_to_question(row) if row else None

    def count_questions(self, subject: str = None) -> int:
        conn = self._db._get_connection()
        if subject:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM questions q "
                "JOIN subjects s ON q.subject_id = s.subject_id WHERE s.code = ?",
                (subject,),
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) as cnt FROM questions").fetchone()
        return row["cnt"] if row else 0

    # ── 错题记录 ──

    def add_error_log(
        self, user_id: int, question_id: int, user_answer: str = "",
        error_type: str = "", error_reason: str = ""
    ) -> int:
        conn = self._db._get_connection()
        try:
            # 检查是否已有未掌握的记录
            existing = conn.execute(
                "SELECT log_id, attempt_count FROM error_logs "
                "WHERE user_id = ? AND question_id = ? AND mastered = 0",
                (user_id, question_id),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE error_logs SET attempt_count = ?, user_answer = ?, "
                    "error_type = ?, error_reason = ?, created_at = CURRENT_TIMESTAMP "
                    "WHERE log_id = ?",
                    (
                        existing["attempt_count"] + 1,
                        user_answer,
                        error_type,
                        error_reason,
                        existing["log_id"],
                    ),
                )
                conn.commit()
                return existing["log_id"]
            cursor = conn.execute(
                "INSERT INTO error_logs (user_id, question_id, user_answer, error_type, error_reason) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, question_id, user_answer, error_type, error_reason),
            )
            conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error("添加错题记录失败: %s", e)
            conn.rollback()
            raise

    def get_error_logs(
        self, user_id: int, subject: str = None, mastered: bool = False
    ) -> list[dict]:
        conn = self._db._get_connection()
        query = """
            SELECT e.*, q.content as question_content, q.answer as question_answer,
                   q.difficulty, q.subject_id, s.name as subject_name
            FROM error_logs e
            JOIN questions q ON e.question_id = q.question_id
            JOIN subjects s ON q.subject_id = s.subject_id
            WHERE e.user_id = ?
        """
        params = [user_id]
        if not mastered:
            query += " AND e.mastered = 0"
        else:
            query += " AND e.mastered = 1"
        if subject:
            query += " AND s.code = ?"
            params.append(subject)
        query += " ORDER BY e.created_at DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def mark_mastered(self, log_id: int) -> bool:
        conn = self._db._get_connection()
        try:
            conn.execute(
                "UPDATE error_logs SET mastered = 1, mastered_at = CURRENT_TIMESTAMP "
                "WHERE log_id = ?",
                (log_id,),
            )
            conn.commit()
            return conn.total_changes > 0
        except Exception as e:
            logger.error("标记掌握失败: %s", e)
            conn.rollback()
            return False

    def get_total_errors(self, user_id: int, subject: str = None) -> int:
        conn = self._db._get_connection()
        query = "SELECT COUNT(*) as cnt FROM error_logs e WHERE e.user_id = ? AND e.mastered = 0"
        params = [user_id]
        if subject:
            query += (" JOIN questions q ON e.question_id = q.question_id "
                       "JOIN subjects s ON q.subject_id = s.subject_id WHERE s.code = ?")
            params.append(subject)
        row = conn.execute(query, params).fetchone()
        return row["cnt"] if row else 0

    # ── 试卷管理 ──

    def create_exam_paper(
        self, user_id: int, title: str, subject_id: int,
        question_ids: list[int], difficulty: int = 3,
        total_score: int = 100, time_limit_min: int = 120,
    ) -> int:
        conn = self._db._get_connection()
        try:
            cursor = conn.execute(
                "INSERT INTO exam_papers (user_id, title, subject_id, difficulty, "
                "question_ids, total_score, time_limit_min) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    user_id, title, subject_id, difficulty,
                    json.dumps(question_ids), total_score, time_limit_min,
                ),
            )
            conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error("创建试卷失败: %s", e)
            conn.rollback()
            raise

    def get_exam_paper(self, paper_id: int) -> Optional[dict]:
        conn = self._db._get_connection()
        row = conn.execute(
            "SELECT * FROM exam_papers WHERE paper_id = ?", (paper_id,)
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        try:
            result["question_ids"] = json.loads(result["question_ids"])
        except (json.JSONDecodeError, TypeError):
            result["question_ids"] = []
        return result

    def list_exam_papers(self, user_id: int, limit: int = 20) -> list[dict]:
        conn = self._db._get_connection()
        rows = conn.execute(
            "SELECT p.*, s.name as subject_name FROM exam_papers p "
            "JOIN subjects s ON p.subject_id = s.subject_id "
            "WHERE p.user_id = ? ORDER BY p.created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def save_exam_result(
        self, exam_id: int, user_id: int, answers: dict,
        score: float, max_score: float, duration_sec: int = 0,
        details: dict = None,
    ) -> int:
        conn = self._db._get_connection()
        try:
            cursor = conn.execute(
                "INSERT INTO exam_results (exam_id, user_id, answers, score, max_score, "
                "duration_sec, started_at, submitted_at, details) "
                "VALUES (?, ?, ?, ?, ?, ?, datetime('now', ?), datetime('now'), ?)",
                (
                    exam_id, user_id,
                    json.dumps(answers, ensure_ascii=False),
                    score, max_score, duration_sec,
                    f"-{duration_sec} seconds",
                    json.dumps(details or {}, ensure_ascii=False),
                ),
            )
            conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error("保存考试结果失败: %s", e)
            conn.rollback()
            raise

    def get_exam_results(self, user_id: int, limit: int = 10) -> list[dict]:
        conn = self._db._get_connection()
        rows = conn.execute(
            "SELECT r.*, p.title as paper_title, s.name as subject_name "
            "FROM exam_results r "
            "LEFT JOIN exam_papers p ON r.exam_id = p.paper_id "
            "LEFT JOIN subjects s ON p.subject_id = s.subject_id "
            "WHERE r.user_id = ? ORDER BY r.submitted_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── 辅助 ──

    @staticmethod
    def _row_to_question(row) -> dict:
        result = dict(row)
        for field in ["options", "answer", "tags", "knowledge_points", "metadata"]:
            if field in result and isinstance(result[field], str):
                try:
                    result[field] = json.loads(result[field])
                except (json.JSONDecodeError, TypeError):
                    pass
        return result
