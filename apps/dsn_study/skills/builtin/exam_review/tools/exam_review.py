import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("skill.exam_review")


class ExamReviewTool:

    def __init__(self):
        self._store = None
        self._db = None

    def get_exam_history(self, user_id: int = 0, subject: str = None,
                         limit: int = 10) -> dict:
        if not self._store:
            return {"success": False, "error": "题库未就绪"}

        history = []
        if self._db:
            try:
                conn = self._db._get_connection()

                # 从 exam_sessions 查模拟考试记录
                sess_query = (
                    "SELECT session_id, user_id, status, score, max_score, "
                    "started_at, submitted_at, config, created_at "
                    "FROM exam_sessions WHERE status = 'report'"
                )
                sess_params = []
                if user_id:
                    sess_query += " AND user_id = ?"
                    sess_params.append(user_id)
                sess_query += " ORDER BY created_at DESC LIMIT ?"
                sess_params.append(limit)
                rows = conn.execute(sess_query, sess_params).fetchall()
                for r in rows:
                    d = dict(r)
                    cfg = d.get("config", "{}")
                    if isinstance(cfg, str):
                        try:
                            cfg = json.loads(cfg)
                        except (json.JSONDecodeError, TypeError):
                            cfg = {}
                    subj = cfg.get("subject", "")
                    if subject and subj != subject:
                        continue
                    history.append({
                        "source": "模拟考试",
                        "session_id": d["session_id"],
                        "result_id": None,
                        "user_id": d["user_id"],
                        "score": d["score"],
                        "max_score": d["max_score"],
                        "subject": subj,
                        "question_count": len(cfg.get("question_ids", [])),
                        "duration_min": cfg.get("time_limit_min", 0),
                        "submitted_at": d.get("submitted_at"),
                        "created_at": d.get("created_at"),
                    })

                # 从 exam_results 查扫描试卷批改记录
                res_query = (
                    "SELECT r.result_id, r.user_id, r.score, r.max_score, "
                    "r.duration_sec, r.submitted_at, r.details, r.created_at "
                    "FROM exam_results r"
                )
                res_params = []
                if user_id:
                    res_query += " WHERE r.user_id = ?"
                    res_params.append(user_id)
                res_query += " ORDER BY r.created_at DESC LIMIT ?"
                res_params.append(limit)
                res_rows = conn.execute(res_query, res_params).fetchall()
                for r in res_rows:
                    d = dict(r)
                    det = d.get("details", "{}")
                    if isinstance(det, str):
                        try:
                            det = json.loads(det)
                        except (json.JSONDecodeError, TypeError):
                            det = {}
                    subj = det.get("subject", "") if isinstance(det, dict) else ""
                    if subject and subj != subject:
                        continue
                    history.append({
                        "source": "扫描批改",
                        "session_id": None,
                        "result_id": d.get("result_id"),
                        "user_id": d["user_id"],
                        "score": d["score"],
                        "max_score": d["max_score"],
                        "subject": subj,
                        "question_count": det.get("per_question", []) if isinstance(det, dict) else 0,
                        "duration_min": d.get("duration_sec", 0) // 60,
                        "submitted_at": d.get("submitted_at"),
                        "created_at": d.get("created_at"),
                    })

                history.sort(key=lambda x: x.get("created_at") or "", reverse=True)
                history = history[:limit]
            except Exception as e:
                logger.warning("查询考试历史失败: %s", e)

        return {"success": True, "history": history, "count": len(history)}

    def get_exam_detail(self, result_id: int = None, session_id: str = None) -> dict:
        if not self._store:
            return {"success": False, "error": "题库未就绪"}

        if not result_id and not session_id:
            return {"success": False, "error": "请提供 result_id 或 session_id"}

        if not self._db:
            return {"success": False, "error": "数据库未就绪"}

        conn = self._db._get_connection()

        # 按 result_id 查询（扫描批改记录）
        if result_id:
            row = conn.execute(
                "SELECT * FROM exam_results WHERE result_id = ?", (result_id,)
            ).fetchone()
            if row:
                d = dict(row)
                det = d.get("details", "{}")
                if isinstance(det, str):
                    try:
                        det = json.loads(det)
                    except (json.JSONDecodeError, TypeError):
                        det = {}
                per_question = det.get("per_question", []) if isinstance(det, dict) else []
                # 补充题目原文
                enriched = []
                for pq in per_question:
                    qid = pq.get("question_id")
                    if qid:
                        q = self._store.get_question(qid)
                        if q:
                            pq["question_text"] = pq.get("question_text", q.get("content", ""))
                            pq["correct_answer"] = pq.get("correct_answer", q.get("answer", ""))
                            pq["knowledge_points"] = q.get("knowledge_points", [])
                    enriched.append(pq)
                return {
                    "success": True,
                    "source": "扫描批改",
                    "exam": {
                        "result_id": d["result_id"],
                        "score": d["score"],
                        "max_score": d["max_score"],
                        "submitted_at": d.get("submitted_at"),
                    },
                    "details": enriched,
                    "error_analyses": det.get("error_analyses", []) if isinstance(det, dict) else [],
                }

        # 按 session_id 查询（模拟考试记录）
        if session_id:
            row = conn.execute(
                "SELECT * FROM exam_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if row:
                d = dict(row)
                cfg = d.get("config", "{}")
                if isinstance(cfg, str):
                    try:
                        cfg = json.loads(cfg)
                    except (json.JSONDecodeError, TypeError):
                        cfg = {}
                q_ids = cfg.get("question_ids", [])
                questions = []
                if q_ids and hasattr(self._store, "get_questions_by_ids"):
                    questions = self._store.get_questions_by_ids(q_ids)

                # 尝试从 exam_results 找关联的详细判分
                extra = conn.execute(
                    "SELECT * FROM exam_results WHERE exam_id = ? AND user_id = ?"
                    " ORDER BY created_at DESC LIMIT 1",
                    (d.get("paper_id", 0) or 0, d["user_id"]),
                ).fetchone()
                details = []
                if extra:
                    extra_det = dict(extra).get("details", "{}")
                    if isinstance(extra_det, str):
                        try:
                            extra_det = json.loads(extra_det)
                        except (json.JSONDecodeError, TypeError):
                            extra_det = {}
                    details = extra_det.get("per_question", []) if isinstance(extra_det, dict) else []

                return {
                    "success": True,
                    "source": "模拟考试",
                    "exam": {
                        "session_id": d["session_id"],
                        "status": d["status"],
                        "score": d["score"],
                        "max_score": d["max_score"],
                        "subject": cfg.get("subject", ""),
                        "started_at": d.get("started_at"),
                        "submitted_at": d.get("submitted_at"),
                    },
                    "questions": [
                        {
                            "question_id": q.get("question_id"),
                            "content": q.get("content", ""),
                            "type_name": q.get("type_name", ""),
                            "difficulty": q.get("difficulty"),
                            "correct_answer": q.get("answer", ""),
                            "knowledge_points": q.get("knowledge_points", []),
                        }
                        for q in questions
                    ],
                    "details": details,
                }

        return {"success": False, "error": "未找到考试记录"}

    def get_error_summary(self, user_id: int = 0, subject: str = None) -> dict:
        if not self._store:
            return {"success": False, "error": "题库未就绪"}

        logs = self._store.get_error_logs(user_id=user_id, subject=subject, mastered=False)
        if not logs:
            return {"success": True, "total_errors": 0, "by_type": {}, "by_subject": {}}

        by_type = {}
        by_subject = {}
        for e in logs:
            etype = e.get("error_type", "未分类")
            by_type[etype] = by_type.get(etype, 0) + 1

            sname = e.get("subject_name", "未知")
            by_subject[sname] = by_subject.get(sname, 0) + 1

        return {
            "success": True,
            "total_errors": len(logs),
            "by_type": by_type,
            "by_subject": by_subject,
            "error_types": sorted(by_type.items(), key=lambda x: -x[1]),
        }

    def get_wrong_questions(self, subject: str = None, error_type: str = None,
                            user_id: int = 0, limit: int = 20) -> dict:
        if not self._store:
            return {"success": False, "error": "题库未就绪"}

        logs = self._store.get_error_logs(user_id=user_id, subject=subject, mastered=False)
        if not logs:
            return {"success": True, "questions": [], "count": 0}

        results = []
        for e in logs:
            if error_type and e.get("error_type") != error_type:
                continue
            qid = e.get("question_id")
            q = self._store.get_question(qid) if qid else None
            results.append({
                "log_id": e.get("log_id"),
                "question_id": qid,
                "content": (q.get("content", "")[:200] if q else "(已删除)"),
                "type_name": q.get("type_name", "") if q else "",
                "difficulty": q.get("difficulty") if q else "",
                "user_answer": e.get("user_answer", ""),
                "correct_answer": q.get("answer", "") if q else "",
                "error_type": e.get("error_type", ""),
                "error_reason": e.get("error_reason", ""),
                "attempt_count": e.get("attempt_count", 1),
                "subject_name": e.get("subject_name", ""),
                "created_at": e.get("created_at"),
            })
            if len(results) >= limit:
                break

        return {"success": True, "questions": results, "count": len(results)}

    def mark_mastered(self, log_id: int) -> dict:
        if not self._store:
            return {"success": False, "error": "题库未就绪"}

        try:
            ok = self._store.mark_mastered(log_id)
            return {"success": ok, "message": "已标记为掌握" if ok else "操作失败"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_weakness_trend(self, subject: str = None, user_id: int = 0,
                           days: int = 30) -> dict:
        if not self._store:
            return {"success": False, "error": "题库未就绪"}

        logs = self._store.get_error_logs(user_id=user_id, subject=subject, mastered=False)
        if not logs:
            return {"success": True, "trend": [], "summary": "无错题数据"}

        cutoff = datetime.now() - timedelta(days=days)
        by_date = {}
        by_type_trend = {}

        for e in logs:
            created = e.get("created_at", "")
            try:
                dt = datetime.strptime(str(created)[:10], "%Y-%m-%d")
            except (ValueError, TypeError):
                continue
            if dt < cutoff:
                continue

            date_key = dt.strftime("%Y-%m-%d")
            by_date[date_key] = by_date.get(date_key, 0) + 1

            etype = e.get("error_type", "未分类")
            if etype not in by_type_trend:
                by_type_trend[etype] = {}
            by_type_trend[etype][date_key] = by_type_trend[etype].get(date_key, 0) + 1

        trend = sorted(
            [{"date": d, "count": c} for d, c in by_date.items()],
            key=lambda x: x["date"],
        )
        type_trends = {}
        for etype, dates in by_type_trend.items():
            type_trends[etype] = sorted(
                [{"date": d, "count": c} for d, c in dates.items()],
                key=lambda x: x["date"],
            )

        return {
            "success": True,
            "trend": trend,
            "total_in_period": sum(t["count"] for t in trend),
            "by_type": type_trends,
            "summary": f"近 {days} 天共 {sum(t['count'] for t in trend)} 道错题",
        }
