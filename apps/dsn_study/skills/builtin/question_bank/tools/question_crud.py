# skills/builtin/question_bank/tools/question_crud.py

import json


class QuestionCRUDTool:

    def __init__(self, question_store=None, template_manager=None):
        self._store = question_store
        self._tm = template_manager

    def create(self, subject: str, content: str, answer: str,
               difficulty: int = 3, tags: list = None,
               type_name: str = "解答题", options: list = None,
               **kwargs) -> dict:
        subject_info = self._tm.get_subject_by_code(subject)
        if not subject_info:
            return {"error": f"学科 {subject} 不存在，请先应用模板"}

        type_id = self._tm.get_type_id(type_name, kwargs.get("subtype", ""))
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
            "tags": tags or [],
            "knowledge_points": kwargs.get("knowledge_points", []),
        }
        try:
            qid = self._store.create_question(data)
            return {"success": True, "question_id": qid}
        except Exception as e:
            return {"error": str(e)}

    def search(self, subject: str = None, difficulty: int = None,
               tags: list = None, limit: int = 10, **kwargs) -> list:
        results = self._store.search_questions(
            subject=subject,
            difficulty=difficulty,
            tags=tags,
            limit=limit,
            knowledge_points=kwargs.get("knowledge_points"),
        )
        return results

    def update(self, question_id: int, **kwargs) -> dict:
        success = self._store.update_question(question_id, kwargs)
        return {"success": success}

    def delete(self, question_id: int) -> dict:
        success = self._store.delete_question(question_id)
        return {"success": success}

    def get(self, question_id: int) -> dict:
        q = self._store.get_question(question_id)
        if q:
            return q
        return {"error": f"题目 {question_id} 不存在"}

    def create_question(self, **kwargs) -> dict:
        return self.create(**kwargs)

    def search_questions(self, **kwargs) -> list:
        return self.search(**kwargs)

    def delete_question(self, question_id: int) -> dict:
        return self.delete(question_id=question_id)
