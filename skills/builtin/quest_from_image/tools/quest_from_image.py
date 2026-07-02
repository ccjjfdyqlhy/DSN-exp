import json
import logging
import os

logger = logging.getLogger("skill.quest_from_image")


class QuestFromImageTool:

    def __init__(self):
        self._store = None
        self._tm = None

    def snap_question(self, file_path: str, subject: str,
                      preview_only: bool = False) -> dict:
        if not self._store or not self._tm:
            return {"success": False, "error": "题库系统未就绪"}

        file_path = os.path.expanduser(file_path)
        if not os.path.isfile(file_path):
            return {"success": False, "error": f"文件不存在: {file_path}"}

        subject_info = self._tm.get_subject_by_code(subject)
        if not subject_info:
            return {"success": False, "error": f"学科 {subject} 不存在"}

        try:
            from models import VisionModel
            data_url = VisionModel.encode_image(file_path)
        except Exception as e:
            return {"success": False, "error": f"读取图片失败: {e}"}

        prompt = (
            "请仔细识别这张图片中的所有题目，返回 JSON 数组。\n"
            "每道题包含以下字段:\n"
            "- content: 题目内容\n"
            "- answer: 参考答案\n"
            "- type_name: 题型(选择题/填空题/解答题/判断题)\n"
            "- subtype: 子类型(单选/多选/填空/计算/证明/简答/判断)\n"
            "- difficulty: 难度 1-5\n"
            "- options: 选项列表(选择题才有)\n"
            "- explanation: 题目解析(选填)\n"
            "- knowledge_points: 知识点列表(选填)\n"
            "只返回纯 JSON 数组，不要包含其他内容。"
        )

        try:
            from config import Config
            if Config.VISION_API_KEY:
                vm = VisionModel()
                raw = vm.ask(data_url, prompt, max_tokens=4096, temperature=0.1)
            else:
                from models import LMStudioChat
                chat = LMStudioChat(model_name=None)
                raw = chat.describe_image(data_url, prompt)
        except Exception as e:
            logger.exception("图片识别失败")
            return {"success": False, "error": f"图片识别失败: {e}"}

        questions = self._parse_json(raw)
        if not questions:
            return {"success": False, "error": "未能从图片中识别出题目"}

        result = {
            "success": True,
            "questions_found": len(questions),
            "questions": self._summarize(questions),
        }

        if preview_only:
            result["mode"] = "preview"
            return result

        added_ids = []
        errors = []
        for q in questions:
            try:
                type_name = q.get("type_name", "解答题")
                subtype = q.get("subtype", "")
                type_id = self._tm.get_type_id(type_name, subtype)
                if not type_id:
                    type_id = self._tm.get_type_id(type_name)
                qid = self._store.create_question({
                    "subject_id": subject_info["subject_id"],
                    "type_id": type_id or 1,
                    "source": "image_snap",
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
                errors.append(str(e))

        result["mode"] = "commit"
        result["added_count"] = len(added_ids)
        result["added_ids"] = added_ids
        result["errors"] = errors
        logger.info("图片识题: 识别 %d 题, 入库 %d 题", len(questions), len(added_ids))
        return result

    def snap_batch(self, file_paths: list, subject: str,
                   preview_only: bool = False) -> dict:
        if not file_paths:
            return {"success": False, "error": "文件列表为空"}

        all_questions = []
        total_found = 0
        total_added = 0
        all_added_ids = []
        all_errors = []

        for fp in file_paths:
            r = self.snap_question(file_path=fp, subject=subject,
                                   preview_only=preview_only)
            if r.get("success"):
                total_found += r.get("questions_found", 0)
                all_questions.extend(r.get("questions", []))
                if not preview_only:
                    total_added += r.get("added_count", 0)
                    all_added_ids.extend(r.get("added_ids", []))
            else:
                all_errors.append({"file": fp, "error": r.get("error")})

        result = {
            "success": total_found > 0,
            "files_processed": len(file_paths),
            "questions_found": total_found,
            "questions": all_questions,
            "errors": all_errors,
        }
        if not preview_only:
            result["added_count"] = total_added
            result["added_ids"] = all_added_ids
        return result

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
                return [data]
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []

    @staticmethod
    def _summarize(questions: list) -> list:
        return [
            {
                "content": q.get("content", "")[:120],
                "type_name": q.get("type_name", "解答题"),
                "difficulty": q.get("difficulty", 3),
            }
            for q in questions
        ]
