# skills/builtin/question_bank/tools/error_analysis.py

from question_bank.error_analyzer import ErrorAnalyzer


class ErrorAnalysisTool:

    def __init__(self, question_store=None, models_plugin=None):
        self._store = question_store
        self._analyzer = ErrorAnalyzer(
            question_store=question_store,
            models_plugin=models_plugin,
        )

    def analyze(self, question_id: int, user_answer: str, user_id: int = 0) -> dict:
        analysis = self._analyzer.analyze_error(user_id, question_id, user_answer)
        return {
            "error_type": analysis.get("error_type"),
            "error_reason": analysis.get("error_reason"),
            "related_kps": analysis.get("related_kps", []),
        }

    def stats(self, user_id: int, subject: str = None) -> dict:
        if not self._store:
            return {"error": "QuestionStore 未初始化"}

        errors = self._store.get_error_logs(user_id, subject=subject)
        weak_points = self._analyzer.get_weak_points(user_id, subject)

        by_type = {}
        for e in errors:
            et = e.get("error_type", "未分类")
            by_type[et] = by_type.get(et, 0) + 1

        return {
            "total_errors": len(errors),
            "by_type": by_type,
            "weak_points": weak_points[:5],
        }

    def recommend(self, user_id: int, subject: str, count: int = 5) -> dict:
        weak_points = self._analyzer.get_weak_points(user_id, subject)
        if not weak_points:
            return {"error": "没有找到薄弱知识点"}

        recommendations = []
        for wp in weak_points[:3]:
            questions = self._analyzer.recommend_questions(
                user_id, wp["code"], count // 3 or 1
            )
            for q in questions:
                recommendations.append({
                    "question_id": q.get("question_id"),
                    "content": q.get("content", "")[:100],
                    "knowledge_point": wp["code"],
                })

        return {
            "success": True,
            "recommendations": recommendations[:count],
        }
