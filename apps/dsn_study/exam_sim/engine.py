import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("ExamEngine")

STATUSES = ["idle", "configuring", "in_progress", "scoring", "report", "finished"]


class ExamEngine:

    def __init__(self, db=None, question_store=None, scorer: Optional['ExamScorer'] = None):
        self._db = db
        self._store = question_store
        self._scorer = scorer

    def _conn(self):
        return self._db._get_connection()

    def create_session(self, user_id: int, config: dict) -> dict:
        conn = self._conn()
        session_id = str(uuid.uuid4())
        time_limit_sec = config.get("time_limit_min", 120) * 60
        try:
            conn.execute(
                """INSERT INTO exam_sessions
                   (session_id, user_id, status, config, time_limit_sec, remaining_sec)
                   VALUES (?, ?, 'configuring', ?, ?, ?)""",
                (session_id, user_id,
                 json.dumps(config, ensure_ascii=False),
                 time_limit_sec, time_limit_sec),
            )
            conn.commit()
            logger.info("考试会话创建: session_id=%s user_id=%d", session_id[:8], user_id)
            return {"success": True, "session_id": session_id}
        except Exception as e:
            logger.error("创建考试会话失败: %s", e)
            conn.rollback()
            return {"success": False, "error": str(e)}

    def start_session(self, session_id: str) -> dict:
        conn = self._conn()
        session = self.get_session(session_id)
        if not session:
            return {"success": False, "error": "会话不存在"}
        if session["status"] not in ("configuring", "idle"):
            return {"success": False, "error": f"当前状态无法开始: {session['status']}"}

        config = session.get("config", {})
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except (json.JSONDecodeError, TypeError):
                config = {}

        # 如果配置文件中有 question_ids，直接使用
        q_ids = config.get("question_ids", [])
        if not q_ids and self._store:
            # 自动组卷
            from question_bank.composer import ExamComposer, ComposeParams
            composer = ExamComposer(question_store=self._store)
            params = ComposeParams(
                subject=config.get("subject", "math"),
                count=config.get("total_count", 10),
            )
            result = composer.compose(params)
            if not result.get("success"):
                return {"success": False, "error": "组卷失败"}
            q_ids = result.get("question_ids", [])
            # 更新 config 中的 question_ids
            config["question_ids"] = q_ids
            conn.execute(
                "UPDATE exam_sessions SET config = ? WHERE session_id = ?",
                (json.dumps(config, ensure_ascii=False), session_id),
            )

        time_limit = config.get("time_limit_min", 120)
        time_limit_sec = time_limit * 60
        conn.execute(
            """UPDATE exam_sessions SET
               status = 'in_progress', started_at = datetime('now'),
               time_limit_sec = ?, remaining_sec = ?
               WHERE session_id = ?""",
            (time_limit_sec, time_limit_sec, session_id),
        )
        conn.commit()

        questions = []
        if self._store and q_ids:
            questions = self._store.get_questions_by_ids(q_ids)

        return {
            "success": True,
            "session_id": session_id,
            "questions": questions,
            "time_limit_sec": time_limit_sec,
        }

    def submit_answer(self, session_id: str, question_index: int, answer: str) -> dict:
        conn = self._conn()
        session = self.get_session(session_id)
        if not session:
            return {"success": False, "error": "会话不存在"}
        if session["status"] != "in_progress":
            return {"success": False, "error": "考试未在进行中"}

        answers = session.get("answers", {})
        if isinstance(answers, str):
            try:
                answers = json.loads(answers)
            except (json.JSONDecodeError, TypeError):
                answers = {}
        answers[str(question_index)] = answer
        conn.execute(
            "UPDATE exam_sessions SET answers = ? WHERE session_id = ?",
            (json.dumps(answers, ensure_ascii=False), session_id),
        )
        conn.commit()
        return {"success": True}

    def submit_session(self, session_id: str) -> dict:
        conn = self._conn()
        session = self.get_session(session_id)
        if not session:
            return {"success": False, "error": "会话不存在"}

        now = datetime.now()
        started = session.get("started_at")
        duration_sec = 0
        if started:
            try:
                started_dt = datetime.strptime(str(started), "%Y-%m-%d %H:%M:%S")
                duration_sec = int((now - started_dt).total_seconds())
            except ValueError:
                pass

        config = session.get("config", {})
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except (json.JSONDecodeError, TypeError):
                config = {}

        q_ids = config.get("question_ids", [])
        questions = []
        if self._store and q_ids:
            questions = self._store.get_questions_by_ids(q_ids)

        if self._scorer and questions:
            # 优先使用 AnswerSheet 统一判分入口
            from .answer_sheet import AnswerSheetMatcher
            matcher = AnswerSheetMatcher(question_store=self._store)
            answer_sheet = matcher.from_session(session)

            if answer_sheet:
                scoring_result = self._scorer.score_answer_sheet(
                    matched_answers=answer_sheet,
                    user_id=session.get("user_id", 0),
                    subject=config.get("subject"),
                )
                score = scoring_result["score"]
                max_score = scoring_result["max_score"]
                details = scoring_result["details"]
                error_analyses = scoring_result.get("error_analyses", [])
            else:
                scoring_result = self._scorer.score_session(session, questions)
                score = scoring_result["score"]
                max_score = scoring_result["max_score"]
                details = scoring_result["details"]
                error_analyses = []
        else:
            score = 0
            max_score = len(questions)
            details = []
            error_analyses = []

        conn.execute(
            """UPDATE exam_sessions SET
               status = 'report', score = ?, max_score = ?,
               submitted_at = datetime('now'), remaining_sec = 0
               WHERE session_id = ?""",
            (score, max_score, session_id),
        )
        conn.commit()

        # 保存 exam_results
        result_id = None
        if self._store and hasattr(self._store, "save_exam_result"):
            try:
                user_id = session.get("user_id", 0)
                paper_id = config.get("paper_id", session.get("paper_id", 0)) or 0
                result_id = self._store.save_exam_result(
                    exam_id=paper_id,
                    user_id=user_id,
                    answers={str(d["question_id"]): d["user_answer"] for d in details},
                    score=score,
                    max_score=max_score,
                    duration_sec=duration_sec,
                    details={
                        "per_question": details,
                        "error_analyses": error_analyses,
                        "session_id": session_id,
                    },
                )
                logger.info("考试结果已保存: result_id=%s", result_id)
            except Exception as e:
                logger.warning("save_exam_result 失败: %s", e)

        return {
            "success": True,
            "session_id": session_id,
            "score": score,
            "max_score": max_score,
            "correct_count": sum(1 for d in details if d.get("correct")),
            "total_count": len(questions),
            "duration_sec": duration_sec,
            "details": details,
            "error_analyses": error_analyses,
            "result_id": result_id,
        }

    def auto_submit(self, session_id: str) -> dict:
        conn = self._conn()
        result = self.submit_session(session_id)
        if result.get("success"):
            conn.execute(
                "UPDATE exam_sessions SET auto_submitted = 1 WHERE session_id = ?",
                (session_id,),
            )
            conn.commit()
        return result

    def get_session(self, session_id: str) -> Optional[dict]:
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM exam_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        for field in ["config", "answers"]:
            if isinstance(result.get(field), str):
                try:
                    result[field] = json.loads(result[field])
                except (json.JSONDecodeError, TypeError):
                    pass
        return result

    def get_remaining_time(self, session_id: str) -> int:
        session = self.get_session(session_id)
        if not session:
            return 0
        started = session.get("started_at")
        if not started:
            return session.get("time_limit_sec", 0)
        try:
            started_dt = datetime.strptime(str(started), "%Y-%m-%d %H:%M:%S")
            elapsed = int((datetime.now() - started_dt).total_seconds())
            remaining = session.get("time_limit_sec", 0) - elapsed
            return max(0, remaining)
        except ValueError:
            return 0

    def is_timeout(self, session_id: str) -> bool:
        return self.get_remaining_time(session_id) <= 0

    def get_user_sessions(self, user_id: int, limit: int = 10) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM exam_sessions WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            for field in ["config", "answers"]:
                if isinstance(d.get(field), str):
                    try:
                        d[field] = json.loads(d[field])
                    except (json.JSONDecodeError, TypeError):
                        pass
            result.append(d)
        return result
