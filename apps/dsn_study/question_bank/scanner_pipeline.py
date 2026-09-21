import json
import logging
from typing import Optional

logger = logging.getLogger("ScannerPipeline")


class ScannerPipeline:
    """
    扫描入题管线: Scanner → Vision → LLM → DB
    """

    def __init__(self, question_store=None, models_plugin=None):
        self._store = question_store
        self._models = models_plugin

    def process_scan(self, image_path: str, user_id: int, subject_code: str = "math") -> dict:
        """
        处理扫描图片，返回入库结果统计。
        """
        result = {
            "questions_found": 0,
            "questions_added": 0,
            "duplicates": 0,
            "errors": [],
        }
        if not self._models:
            result["errors"].append("ModelsPlugin 未注入")
            return result

        try:
            description = self._models.describe_image(image_path, "请详细识别图片中的所有题目，包括题目编号、内容、选项(如有)和答案。")
        except Exception as e:
            result["errors"].append(f"图片描述失败: {e}")
            return result

        extract_prompt = f"""
请从以下图片识别结果中提取所有题目，返回 JSON 数组格式。
每道题包含以下字段:
- content: 题目内容(字符串)
- answer: 参考答案(字符串)
- type_name: 题型(选择题/填空题/解答题/判断题)
- subtype: 子类型(单选/多选/填空/计算/证明/简答/判断)
- difficulty: 难度 1-5 (整数)
- options: 选项列表(选择题才有)
- tags: 标签列表

图片识别结果:
{description}

只返回纯 JSON 数组，不要包含其他内容。
"""
        if not self._models:
            return result

        try:
            text_response = self._models.send_message(extract_prompt)
        except Exception as e:
            result["errors"].append(f"LLM 提取失败: {e}")
            return result

        try:
            questions = self._parse_llm_questions(text_response)
        except Exception as e:
            result["errors"].append(f"解析 LLM 输出失败: {e}")
            return result

        result["questions_found"] = len(questions)

        for q in questions:
            try:
                subject_id = self._get_subject_id(subject_code)
                type_id = self._get_or_create_type_id(
                    q.get("type_name", "解答题"),
                    q.get("subtype", ""),
                )
                qid = self._store.create_question({
                    "subject_id": subject_id,
                    "type_id": type_id,
                    "source": "scan",
                    "difficulty": q.get("difficulty", 3),
                    "content": q.get("content", ""),
                    "options": q.get("options", []),
                    "answer": q.get("answer", ""),
                    "tags": q.get("tags", []),
                })
                result["questions_added"] += 1
            except Exception as e:
                result["errors"].append(f"题目入库失败: {e}")

        return result

    def process_text(self, text: str, user_id: int, subject_code: str = "math") -> dict:
        """从文本中提取题目并入库"""
        result = {
            "questions_found": 0,
            "questions_added": 0,
            "errors": [],
        }
        if not self._models:
            result["errors"].append("ModelsPlugin 未注入")
            return result

        extract_prompt = f"""
请从以下文本中提取所有题目，返回 JSON 数组格式。
每道题包含:
- content: 题目内容(字符串)
- answer: 参考答案(字符串)
- type_name: 题型(选择题/填空题/解答题/判断题)
- subtype: 子类型
- difficulty: 难度 1-5 (整数)
- options: 选项列表(选择题才有)
- tags: 标签列表

文本:
{text}

只返回纯 JSON 数组，不要包含其他内容。
"""
        try:
            text_response = self._models.send_message(extract_prompt)
        except Exception as e:
            result["errors"].append(f"LLM 提取失败: {e}")
            return result

        try:
            questions = self._parse_llm_questions(text_response)
        except Exception as e:
            result["errors"].append(f"解析失败: {e}")
            return result

        result["questions_found"] = len(questions)
        for q in questions:
            try:
                subject_id = self._get_subject_id(subject_code)
                type_id = self._get_or_create_type_id(
                    q.get("type_name", "解答题"),
                    q.get("subtype", ""),
                )
                self._store.create_question({
                    "subject_id": subject_id,
                    "type_id": type_id,
                    "source": "import",
                    "difficulty": q.get("difficulty", 3),
                    "content": q.get("content", ""),
                    "options": q.get("options", []),
                    "answer": q.get("answer", ""),
                    "tags": q.get("tags", []),
                })
                result["questions_added"] += 1
            except Exception as e:
                result["errors"].append(f"题目入库失败: {e}")

        return result

    def _get_subject_id(self, code: str) -> int:
        conn = self._store._db._get_connection()
        row = conn.execute(
            "SELECT subject_id FROM subjects WHERE code = ?", (code,)
        ).fetchone()
        if row:
            return row["subject_id"]
        # 如果没有找到科目，返回第一个科目
        row = conn.execute("SELECT subject_id FROM subjects LIMIT 1").fetchone()
        return row["subject_id"] if row else 1

    def _get_or_create_type_id(self, name: str, subtype: str) -> int:
        conn = self._store._db._get_connection()
        row = conn.execute(
            "SELECT type_id FROM question_types WHERE name = ? AND subtype = ?",
            (name, subtype),
        ).fetchone()
        if row:
            return row["type_id"]
        if not subtype:
            row = conn.execute(
                "SELECT type_id FROM question_types WHERE name = ? LIMIT 1",
                (name,),
            ).fetchone()
            if row:
                return row["type_id"]
        cursor = conn.execute(
            "INSERT INTO question_types (name, subtype, scoring_mode) VALUES (?, ?, 'llm')",
            (name, subtype),
        )
        conn.commit()
        return cursor.lastrowid

    @staticmethod
    def _parse_llm_questions(text: str) -> list[dict]:
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
        return json.loads(text)
