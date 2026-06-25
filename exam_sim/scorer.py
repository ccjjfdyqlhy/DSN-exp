import json
import logging
from typing import Optional

logger = logging.getLogger("ExamScorer")


class ExamScorer:

    def __init__(self, question_store=None, models_plugin=None):
        self._store = question_store
        self._models = models_plugin

    def score_question(self, question: dict, user_answer: str) -> dict:
        correct = question.get("answer", "")
        qtype = question.get("type_name", "")

        if qtype in ("选择题", "判断题"):
            return self._score_exact(question, user_answer, correct)
        elif qtype == "填空题":
            return self._score_keyword(question, user_answer, correct)
        else:
            return self._score_llm(question, user_answer, correct)

    def _score_exact(self, question: dict, user_answer: str, correct) -> dict:
        if isinstance(correct, (list, dict)):
            correct_str = json.dumps(correct, ensure_ascii=False)
        else:
            correct_str = str(correct).strip()
        user_str = str(user_answer).strip()
        is_correct = user_str.lower() == correct_str.lower()
        return {
            "correct": is_correct,
            "score": 1.0 if is_correct else 0.0,
            "max_score": 1.0,
            "explanation": "精确匹配" if is_correct else f"期望: {correct_str}",
        }

    def _score_keyword(self, question: dict, user_answer: str, correct) -> dict:
        if isinstance(correct, str):
            keywords = [kw.strip().lower() for kw in correct.replace("，", ",").split(",") if kw.strip()]
        else:
            keywords = [str(correct).lower()]
        user_str = str(user_answer).lower()
        matched = sum(1 for kw in keywords if kw and kw in user_str)
        ratio = matched / len(keywords) if keywords else 0.0
        return {
            "correct": ratio >= 0.8,
            "score": ratio,
            "max_score": 1.0,
            "explanation": f"关键词命中 {matched}/{len(keywords)}",
        }

    def _score_llm(self, question: dict, user_answer: str, correct) -> dict:
        if not self._models:
            return {
                "correct": False,
                "score": 0.0,
                "max_score": 1.0,
                "explanation": "LLM 判分不可用",
            }

        correct_str = correct
        if isinstance(correct, (list, dict)):
            correct_str = json.dumps(correct, ensure_ascii=False)

        prompt = f"""
请评判以下主观题的答案。

题目: {question.get('content', '')}
参考答案: {correct_str}
用户答案: {user_answer}

返回 JSON:
{{
    "score": 0.0-1.0,
    "correct": true/false,
    "reason": "判分理由"
}}
"""
        try:
            response = self._models.send_message(prompt)
            result = self._parse_json(response)
            return {
                "correct": result.get("correct", False),
                "score": float(result.get("score", 0)),
                "max_score": 1.0,
                "explanation": result.get("reason", ""),
            }
        except Exception as e:
            logger.error("LLM 判分失败: %s", e)
            return {
                "correct": False,
                "score": 0.0,
                "max_score": 1.0,
                "explanation": f"LLM 判分异常: {e}",
            }

    def score_session(self, session: dict, questions: list[dict]) -> dict:
        answers = session.get("answers", {})
        if isinstance(answers, str):
            try:
                answers = json.loads(answers)
            except (json.JSONDecodeError, TypeError):
                answers = {}

        total_score = 0.0
        max_score = len(questions)
        details = []
        for i, q in enumerate(questions):
            qid = str(q.get("question_id", i))
            user_answer = answers.get(qid, answers.get(i, ""))
            result = self.score_question(q, user_answer)
            details.append({
                "question_id": q.get("question_id"),
                "index": i,
                "user_answer": user_answer,
                "correct": result["correct"],
                "score": result["score"],
                "max_score": result["max_score"],
                "explanation": result["explanation"],
            })
            total_score += result["score"]

        correct_count = sum(1 for d in details if d["correct"])
        return {
            "score": total_score,
            "max_score": max_score,
            "correct_count": correct_count,
            "total_count": len(questions),
            "details": details,
        }

    def analyze_errors(self, session: dict, results: dict) -> list[dict]:
        errors = []
        for d in results.get("details", []):
            if not d["correct"]:
                errors.append({
                    "question_id": d["question_id"],
                    "user_answer": d["user_answer"],
                    "error_type": "未分类",
                    "error_reason": d.get("explanation", ""),
                })
        return errors

    @staticmethod
    def _parse_json(text: str) -> dict:
        text = text.strip()
        if "```" in text:
            lines = text.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                if line.strip().startswith("```"):
                    if in_block:
                        break
                    in_block = True
                    continue
                if in_block:
                    json_lines.append(line)
            text = "\n".join(json_lines)
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return {"score": 0, "correct": False, "reason": text[:200]}
