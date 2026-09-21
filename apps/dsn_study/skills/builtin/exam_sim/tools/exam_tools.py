# skills/builtin/exam_sim/tools/exam_tools.py

from __future__ import annotations


class ExamSimTool:

    def __init__(self, exam_engine=None, exam_scorer=None,
                 question_store=None):
        self._engine = exam_engine
        self._scorer = exam_scorer
        self._store = question_store

    def create_exam(self, subject: str, question_count: int = 10,
                    time_limit_min: int = 120, difficulty: int = 3,
                    user_id: int = 0, **kwargs) -> dict:
        if not self._engine:
            return {"error": "ExamEngine 未初始化"}
        config = {
            "subject": subject,
            "total_count": question_count,
            "time_limit_min": time_limit_min,
            "difficulty": difficulty,
        }
        result = self._engine.create_session(user_id, config)
        return result

    def start_exam(self, session_id: str, **kwargs) -> dict:
        if not self._engine:
            return {"error": "ExamEngine 未初始化"}
        result = self._engine.start_session(session_id)
        if result.get("success"):
            questions = result.get("questions", [])
            return {
                "success": True,
                "session_id": session_id,
                "time_limit_sec": result.get("time_limit_sec", 0),
                "question_count": len(questions),
                "questions": [
                    {
                        "index": i,
                        "content": q.get("content", ""),
                        "type_name": q.get("type_name", ""),
                        "difficulty": q.get("difficulty"),
                    }
                    for i, q in enumerate(questions)
                ],
            }
        return result

    def submit_answer(self, session_id: str, question_index: int,
                      answer: str, **kwargs) -> dict:
        if not self._engine:
            return {"error": "ExamEngine 未初始化"}
        return self._engine.submit_answer(session_id, question_index, answer)

    def finish_exam(self, session_id: str, **kwargs) -> dict:
        if not self._engine:
            return {"error": "ExamEngine 未初始化"}
        result = self._engine.submit_session(session_id)
        if result.get("success"):
            total = result.get("total_count", 0)
            return {
                "success": True,
                "session_id": session_id,
                "score": result.get("score", 0),
                "max_score": result.get("max_score", 0),
                "correct_count": result.get("correct_count", 0),
                "total_count": total,
                "duration_sec": result.get("duration_sec", 0),
                "correct_rate": round(
                    result.get("correct_count", 0)
                    / max(total, 1) * 100, 1
                ),
            }
        return result
