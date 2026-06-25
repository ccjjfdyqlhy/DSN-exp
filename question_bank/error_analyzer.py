import json
import logging

logger = logging.getLogger("ErrorAnalyzer")


class ErrorAnalyzer:

    def __init__(self, question_store=None, models_plugin=None):
        self._store = question_store
        self._models = models_plugin

    def analyze_error(
        self, user_id: int, question_id: int, user_answer: str
    ) -> dict:
        question = self._store.get_question(question_id) if self._store else None
        if not question:
            return {
                "error_type": "未知",
                "error_reason": "题目未找到",
                "related_kps": [],
            }

        if self._models:
            return self._llm_analyze(user_id, question, user_answer)

        return self._simple_analyze(question, user_answer)

    def _llm_analyze(self, user_id: int, question: dict, user_answer: str) -> dict:
        correct_answer = question.get("answer", "")
        if isinstance(correct_answer, (list, dict)):
            correct_answer = json.dumps(correct_answer, ensure_ascii=False)

        prompt = f"""
请分析以下错题，判断错误类型并给出原因。

题目: {question.get('content', '')}
正确答案: {correct_answer}
用户答案: {user_answer}

请返回 JSON:
{{
    "error_type": "粗心" / "知识点不清" / "审题错误" / "计算错误" / "概念混淆",
    "error_reason": "详细错误原因",
    "related_kps": ["相关知识点1", "相关知识点2"]
}}

只返回 JSON，不要其他内容。
"""
        try:
            response = self._models.send_message(prompt)
            return self._parse_json_response(response)
        except Exception as e:
            logger.error("LLM 错题分析失败: %s", e)
            return self._simple_analyze(question, user_answer)

    def _simple_analyze(self, question: dict, user_answer: str) -> dict:
        return {
            "error_type": "未分类",
            "error_reason": "无法进行深度分析",
            "related_kps": question.get("knowledge_points", []) if isinstance(
                question.get("knowledge_points"), list
            ) else [],
        }

    def get_weak_points(self, user_id: int, subject: str = None) -> list[dict]:
        if not self._store:
            return []
        errors = self._store.get_error_logs(user_id, subject=subject)
        kp_counts = {}
        for e in errors:
            qid = e.get("question_id")
            if not qid:
                continue
            q = self._store.get_question(qid)
            if not q:
                continue
            kps = q.get("knowledge_points", [])
            if isinstance(kps, str):
                try:
                    kps = json.loads(kps)
                except Exception:
                    kps = []
            for kp in kps:
                kp = str(kp)
                if kp not in kp_counts:
                    kp_counts[kp] = {"code": kp, "error_count": 0}
                kp_counts[kp]["error_count"] += 1
        return sorted(kp_counts.values(), key=lambda x: x["error_count"], reverse=True)

    def recommend_questions(self, user_id: int, kp_code: str, count: int = 5) -> list[dict]:
        if not self._store:
            return []
        return self._store.search_questions(
            knowledge_points=[kp_code],
            limit=count,
        )

    @staticmethod
    def _parse_json_response(text: str) -> dict:
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
        except json.JSONDecodeError:
            return {
                "error_type": "解析失败",
                "error_reason": text[:200],
                "related_kps": [],
            }
