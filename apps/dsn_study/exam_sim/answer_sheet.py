# exam_sim/answer_sheet.py
# 答题卡匹配器 — 将 GradingModel 提取的题目与题库匹配，产生可判分的键值对

import json
import logging
import re
from typing import Optional

logger = logging.getLogger("AnswerSheetMatcher")


class AnswerSheetMatcher:
    """
    答题卡匹配器。

    职责:
    1. 将 GradingModel 从扫描试卷中提取的题目文本与题库中的题目做匹配
    2. 从已有考试会话中构建 AnswerSheet 格式
    3. 输出统一的可判分格式
    """

    def __init__(self, question_store=None):
        self._store = question_store

    def match(self, extracted_questions: list[dict], subject: str = None) -> dict:
        """
        将提取的题目列表与题库匹配。

        :param extracted_questions: [
            {"question_index": 0, "question_text": "...", "student_answer": "..."},
            ...
        ]
        :param subject: 学科代码（可选，缩小搜索范围）
        :return: {
            "matched": [{question_id, question_index, question_text, student_answer, match_confidence}],
            "unmatched": [{question_index, question_text, student_answer}],
            "matched_count": N,
            "unmatched_count": N,
            "total": N,
        }
        """
        matched = []
        unmatched = []

        for eq in extracted_questions:
            qtext = eq.get("question_text", "").strip()
            if not qtext:
                continue

            found = self._find_match(qtext, subject)
            if found:
                matched.append({
                    "question_index": eq.get("question_index", 0),
                    "question_id": found["question_id"],
                    "question_text": found.get("content", qtext),
                    "student_answer": eq.get("student_answer", ""),
                    "match_confidence": found.get("_match_confidence", 0.0),
                })
            else:
                unmatched.append({
                    "question_index": eq.get("question_index", 0),
                    "question_text": qtext,
                    "student_answer": eq.get("student_answer", ""),
                })

        logger.info("AnswerSheet 匹配: 成功 %d / 未匹配 %d / 总计 %d",
                     len(matched), len(unmatched), len(extracted_questions))
        return {
            "matched": matched,
            "unmatched": unmatched,
            "total": len(extracted_questions),
            "matched_count": len(matched),
            "unmatched_count": len(unmatched),
        }

    def from_session(self, session: dict) -> list[dict]:
        """
        从 exam_session 的 answers 和 config 构建 AnswerSheet 格式。

        用于模拟考试路径，产出与 GradingModel.extract_answer_sheet()
        相同的格式，方便统一判分入口。

        :param session: exam_sessions 行（含 config, answers）
        :return: [{question_id, question_text, student_answer}, ...]
        """
        config = session.get("config", {})
        answers = session.get("answers", {})

        q_ids = config.get("question_ids", []) if isinstance(config, dict) else []
        if not q_ids or not self._store:
            return []

        questions = self._store.get_questions_by_ids(q_ids) if hasattr(self._store, "get_questions_by_ids") else []
        result = []
        for i, q in enumerate(questions):
            qid = q.get("question_id")
            student_answer = answers.get(str(i), answers.get(str(qid), ""))
            result.append({
                "question_index": i,
                "question_id": qid,
                "question_text": q.get("content", ""),
                "student_answer": student_answer,
            })
        return result

    def _find_match(self, question_text: str, subject: str = None) -> Optional[dict]:
        """在题库中查找匹配的题目"""
        if not self._store:
            return None

        norm_q = self._normalize(question_text)
        if len(norm_q) < 10:
            return None

        questions = self._store.search_questions(subject=subject, limit=100)
        if not questions:
            return None

        # Step 1: 精确匹配（去空格、去标点后完全一致）
        for q in questions:
            stored = self._normalize(q.get("content", ""))
            if stored == norm_q:
                q["_match_confidence"] = 1.0
                return q

        # Step 2: 前缀匹配（前 50 个字符）
        prefix = norm_q[:50]
        if len(prefix) > 15:
            for q in questions:
                stored = self._normalize(q.get("content", ""))[:50]
                if stored == prefix:
                    q["_match_confidence"] = 0.9
                    return q

        # Step 3: 包含匹配（题目文本包含存储文本或反之）
        for q in questions:
            stored = self._normalize(q.get("content", ""))
            if len(stored) > 20 and (stored in norm_q or norm_q in stored):
                overlap = len(stored) / max(len(norm_q), 1)
                if overlap > 0.7:
                    q["_match_confidence"] = round(overlap, 2)
                    return q

        return None

    @staticmethod
    def _normalize(text: str) -> str:
        text = re.sub(r'\s+', '', text)
        text = text.lower()
        text = re.sub(r'[^\w\u4e00-\u9fff]', '', text)
        return text
