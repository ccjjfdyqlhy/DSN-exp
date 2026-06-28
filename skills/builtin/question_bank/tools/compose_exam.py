# skills/builtin/question_bank/tools/compose_exam.py

class ComposeExamTool:

    def __init__(self, question_store=None):
        self._store = question_store

    def _composer(self):
        from question_bank.composer import ExamComposer
        return ExamComposer(question_store=self._store)

    def compose_exam(self, **kwargs) -> dict:
        return self.compose(**kwargs)

    def compose(self, subject: str, count: int = 10, difficulty: int = 3,
                knowledge_points: list = None, **kwargs) -> dict:
        from question_bank.composer import ComposeParams
        composer = self._composer()
        params = ComposeParams(
            subject=subject,
            count=count,
            difficulty_dist=kwargs.get("difficulty_dist") or {difficulty: 1.0},
            type_dist=kwargs.get("type_dist"),
            knowledge_points=knowledge_points,
        )
        result = composer.compose(params)
        if result.get("success"):
            return {
                "success": True,
                "question_ids": result["question_ids"],
                "total_score": result["total_score"],
                "estimated_min": result["estimated_min"],
                "question_count": len(result["questions"]),
                "preview": [self._format_preview(q) for q in result["questions"][:5]],
            }
        return result

    def adaptive_compose(self, user_id: int, subject: str,
                         count: int = 10) -> dict:
        result = self._composer.compose_adaptive(user_id, subject, count)
        if result.get("success"):
            return {
                "success": True,
                "question_ids": result["question_ids"],
                "question_count": len(result["questions"]),
                "preview": [self._format_preview(q) for q in result["questions"][:5]],
            }
        return result

    @staticmethod
    def _format_preview(q: dict) -> dict:
        return {
            "question_id": q.get("question_id"),
            "content": q.get("content", "")[:100],
            "difficulty": q.get("difficulty"),
            "type_name": q.get("type_name", ""),
        }
