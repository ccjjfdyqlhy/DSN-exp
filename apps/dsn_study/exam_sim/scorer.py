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

    def score_answer_sheet(self, matched_answers: list[dict], user_id: int,
                           subject: str = None) -> dict:
        """
        统一判分入口。

        接受 AnswerSheet 格式（含 question_id 的已匹配条目），
        判分后自动进行错题分析并记录到 error_logs。

        :param matched_answers: [
            {"question_id": int, "student_answer": str, "question_text": str},
            ...
        ]
        :param user_id: 用户 ID
        :param subject: 学科代码
        :return: {
            "success": bool,
            "score": float, "max_score": float,
            "correct_count": int, "total_count": int,
            "details": [{每道题得分详情}],
            "error_analyses": [{错题分析结果}],
            "result_id": int or None,
        }
        """
        if not self._store:
            return {"success": False, "error": "题库未就绪"}

        total_score = 0.0
        max_score = float(len(matched_answers))
        details = []
        error_analyses = []

        for item in matched_answers:
            qid = item.get("question_id")
            student_answer = item.get("student_answer", "")
            question = self._store.get_question(qid) if qid else None

            if not question:
                details.append({
                    "question_id": qid,
                    "index": item.get("question_index", 0),
                    "user_answer": student_answer,
                    "correct": False,
                    "score": 0.0,
                    "max_score": 1.0,
                    "explanation": "题目未找到或已删除",
                })
                continue

            result = self.score_question(question, student_answer)
            entry = {
                "question_id": qid,
                "index": item.get("question_index", 0),
                "question_text": item.get("question_text", question.get("content", "")),
                "user_answer": student_answer,
                "correct_answer": question.get("answer", ""),
                "correct": result["correct"],
                "score": result["score"],
                "max_score": result["max_score"],
                "explanation": result["explanation"],
            }
            details.append(entry)
            total_score += result["score"]

            # 自动错题分析（只处理 error_logs，不涉及 exam_results）
            if not result["correct"] and student_answer:
                try:
                    analysis = self._analyze_single_error(
                        user_id, qid, student_answer, question,
                    )
                    error_analyses.append(analysis)
                except Exception as e:
                    logger.warning("单题错题分析失败: qid=%s, %s", qid, e)

        correct_count = sum(1 for d in details if d["correct"])
        return {
            "success": True,
            "score": total_score,
            "max_score": max_score,
            "correct_count": correct_count,
            "total_count": len(details),
            "details": details,
            "error_analyses": error_analyses,
        }

    def analyze_errors(self, user_id: int, details: list[dict]) -> list[dict]:
        """
        对得分详情中所有错题进行错误分析并记录到 error_logs。

        替代原有的死代码，真实调用 ErrorAnalyzer。

        :param user_id: 用户 ID
        :param details: [{"question_id", "user_answer", ...}, ...]
        :return: [{"question_id", "error_type", "error_reason", "log_id"}, ...]
        """
        errors = []
        for d in details:
            if d.get("correct"):
                continue
            qid = d.get("question_id")
            user_answer = d.get("user_answer", "")
            if not qid or not user_answer:
                continue
            try:
                question = self._store.get_question(qid) if self._store else None
                analysis = self._analyze_single_error(user_id, qid, user_answer, question)
                errors.append(analysis)
            except Exception as e:
                logger.warning("analyze_errors 中单题分析失败: qid=%s, %s", qid, e)
                errors.append({
                    "question_id": qid,
                    "error_type": "分析异常",
                    "error_reason": str(e),
                })
        return errors

    def _analyze_single_error(self, user_id: int, question_id: int,
                               user_answer: str, question: dict = None) -> dict:
        """分析单题错误原因并记录到 error_logs"""
        analysis = {"error_type": "未分类", "error_reason": ""}

        if self._models:
            from question_bank.error_analyzer import ErrorAnalyzer
            try:
                analyzer = ErrorAnalyzer(
                    question_store=self._store,
                    models_plugin=self._models,
                )
                analysis = analyzer.analyze_error(user_id, question_id, user_answer)
            except Exception as e:
                logger.warning("ErrorAnalyzer 调用失败: %s", e)

        # 记录到 error_logs
        if self._store and hasattr(self._store, "add_error_log"):
            try:
                log_id = self._store.add_error_log(
                    user_id=user_id,
                    question_id=question_id,
                    user_answer=user_answer,
                    error_type=analysis.get("error_type", "未分类"),
                    error_reason=analysis.get("error_reason", ""),
                )
                analysis["log_id"] = log_id
                logger.info("错题已记录: qid=%s, type=%s, log_id=%s",
                            question_id, analysis.get("error_type"), log_id)
            except Exception as e:
                logger.warning("add_error_log 失败: %s", e)

        analysis["question_id"] = question_id
        return analysis

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
