import json
import logging

logger = logging.getLogger("skill.quick_question")


class QuickQuestionTool:

    def __init__(self):
        self._store = None
        self._tm = None

    def add_question(self, subject: str, content: str, answer: str,
                     type_name: str = "解答题", subtype: str = "",
                     difficulty: int = 3, options: list = None,
                     explanation: str = "", knowledge_points: list = None,
                     tags: list = None, **kwargs) -> dict:
        if not self._store or not self._tm:
            return {"success": False, "error": "题库系统未就绪"}

        subject_info = self._tm.get_subject_by_code(subject)
        if not subject_info:
            return {"success": False, "error": f"学科 {subject} 不存在"}

        type_id = self._tm.get_type_id(type_name, subtype)
        if not type_id:
            type_id = self._tm.get_type_id(type_name)

        data = {
            "subject_id": subject_info["subject_id"],
            "type_id": type_id or 1,
            "source": "manual",
            "difficulty": difficulty,
            "content": content,
            "options": options or [],
            "answer": answer,
            "explanation": explanation or "",
            "tags": tags or [],
            "knowledge_points": knowledge_points or [],
        }
        try:
            qid = self._store.create_question(data)
            logger.info("快捷录入题目成功: id=%d, subject=%s", qid, subject)
            return {"success": True, "question_id": qid}
        except Exception as e:
            logger.exception("快捷录入题目失败")
            return {"success": False, "error": str(e)}
