import json
import logging

logger = logging.getLogger("skill.text_extract")


class TextExtractTool:

    def __init__(self):
        self._store = None
        self._tm = None
        self._models = None

    def extract_preview(self, text: str, subject: str = "math") -> dict:
        if not self._models:
            return {"success": False, "error": "LLM 模型未就绪，无法提取"}

        prompt = (
            "请从以下文本中提取所有题目，返回 JSON 数组格式。\n"
            "每道题包含以下字段:\n"
            "- content: 题目内容\n"
            "- answer: 参考答案\n"
            "- type_name: 题型(选择题/填空题/解答题/判断题)\n"
            "- subtype: 子类型(单选/多选/填空/计算/证明/简答/判断)\n"
            "- difficulty: 难度 1-5\n"
            "- options: 选项列表(选择题才有)\n"
            "- explanation: 题目解析(选填)\n"
            "- knowledge_points: 知识点列表(选填)\n"
            "- tags: 标签列表(选填)\n"
            f"学科: {subject}\n\n"
            "文本:\n"
            f"{text}\n\n"
            "只返回纯 JSON 数组，不要包含其他内容。"
        )

        try:
            raw = self._call_llm(prompt)
        except Exception as e:
            logger.exception("LLM 提取失败")
            return {"success": False, "error": f"提取失败: {e}"}

        questions = self._parse_json(raw)
        if not questions:
            return {"success": False, "error": "未能从文本中识别出题目，请检查文本格式"}

        return {
            "success": True,
            "questions_found": len(questions),
            "questions": [
                {
                    "content": q.get("content", "")[:200],
                    "type_name": q.get("type_name", "解答题"),
                    "difficulty": q.get("difficulty", 3),
                    "has_answer": bool(q.get("answer")),
                }
                for q in questions
            ],
            "raw_questions": questions,
        }

    def confirm_import(self, questions: list, subject: str = "math") -> dict:
        if not self._store or not self._tm:
            return {"success": False, "error": "题库系统未就绪"}

        if not questions:
            return {"success": False, "error": "题目列表为空"}

        subject_info = self._tm.get_subject_by_code(subject)
        if not subject_info:
            return {"success": False, "error": f"学科 {subject} 不存在"}

        added_ids = []
        errors = []
        for i, q in enumerate(questions):
            try:
                type_name = q.get("type_name", "解答题")
                subtype = q.get("subtype", "")
                type_id = self._tm.get_type_id(type_name, subtype)
                if not type_id:
                    type_id = self._tm.get_type_id(type_name)
                qid = self._store.create_question({
                    "subject_id": subject_info["subject_id"],
                    "type_id": type_id or 1,
                    "source": "text_extract",
                    "difficulty": q.get("difficulty", 3),
                    "content": q.get("content", ""),
                    "options": q.get("options", []),
                    "answer": q.get("answer", ""),
                    "explanation": q.get("explanation", ""),
                    "tags": q.get("tags", []),
                    "knowledge_points": q.get("knowledge_points", []),
                })
                added_ids.append(qid)
            except Exception as e:
                errors.append({"index": i, "error": str(e)})

        logger.info("文本提取确认入库: 成功 %d 题, 失败 %d 题",
                     len(added_ids), len(errors))
        return {
            "success": len(added_ids) > 0,
            "added_count": len(added_ids),
            "added_ids": added_ids,
            "error_count": len(errors),
            "errors": errors,
        }

    def _call_llm(self, prompt: str) -> str:
        if hasattr(self._models, "send_message"):
            return self._models.send_message(prompt)
        if hasattr(self._models, "invoke"):
            from plugins.base import PluginContext
            ctx = PluginContext()
            return self._models.invoke(
                messages=[{"role": "user", "content": prompt}],
                ctx=ctx,
            )
        from models import OpenAIChat
        chat = OpenAIChat()
        return chat.send_message(prompt)

    @staticmethod
    def _parse_json(text: str) -> list:
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
            data = json.loads(text)
            if isinstance(data, dict):
                data = data.get("questions", data)
                return [data] if isinstance(data, dict) else data
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []
