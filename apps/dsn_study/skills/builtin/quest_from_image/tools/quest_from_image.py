import json
import logging
import os

logger = logging.getLogger("skill.quest_from_image")


class QuestFromImageTool:

    def __init__(self):
        self._store = None
        self._tm = None

    def import_photo_questions(self, file_path: str, subject: str = "",
                               preview_only: bool = False) -> dict:
        """
        从单张图片直接入库（VisionModel 全权识别，不经主模型）。
        视觉模型直接输出完整 JSON：科目自动识别 + 逐题(题目原文/选项/答案/解析/题型/难度/标签/知识点)。
        :param file_path: 图片路径
        :param subject: 学科代码，可留空；留空由视觉模型自动识别
        :param preview_only: true=仅预览不入库
        """
        if not self._store or not self._tm:
            return {"success": False, "error": "题库系统未就绪"}

        file_path = os.path.expanduser(file_path)
        if not os.path.isfile(file_path):
            return {"success": False, "error": f"文件不存在: {file_path}"}

        try:
            from models import VisionModel
            data_url = VisionModel.encode_image(file_path)
        except Exception as e:
            return {"success": False, "error": f"读取图片失败: {e}"}

        prompt = self._build_photo_prompt(subject)

        try:
            from config import Config
            if Config.VISION_API_KEY:
                vm = VisionModel()
                raw = vm.ask(data_url, prompt, max_tokens=8192, temperature=0.1)
            else:
                from models import LMStudioChat
                chat = LMStudioChat(model_name=None)
                raw = chat.describe_image(data_url, prompt)
        except Exception as e:
            logger.exception("图片识别失败")
            return {"success": False, "error": f"图片识别失败: {e}"}

        questions, detected_subject = self._parse_page(raw)
        if not questions:
            return {"success": False, "error": "未能从图片中识别出题目"}

        subject_info, subject_code = self._resolve_subject(subject, detected_subject)
        if not subject_info:
            return {"success": False, "error": "无法确定科目，且题库中没有可用科目"}

        result = {
            "success": True,
            "subject": subject_code,
            "subject_detected": detected_subject,
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
                    "metadata": {
                        "source": "import_photo_questions",
                        "subject_detected": detected_subject,
                        "file": os.path.basename(file_path),
                    },
                })
                added_ids.append(qid)
            except Exception as e:
                errors.append(str(e))

        result["mode"] = "commit"
        result["added_count"] = len(added_ids)
        result["added_ids"] = added_ids
        result["errors"] = errors
        logger.info("图片识题: 识别 %d 题, 入库 %d 题, subject=%s",
                    len(questions), len(added_ids), subject_code)
        return result

    def import_photo_questions_batch(self, file_paths: list, subject: str = "",
                                     preview_only: bool = False) -> dict:
        if not file_paths:
            return {"success": False, "error": "文件列表为空"}

        all_questions = []
        total_found = 0
        total_added = 0
        all_added_ids = []
        all_errors = []

        for fp in file_paths:
            r = self.import_photo_questions(file_path=fp, subject=subject,
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

    # ── 辅助方法 ──

    @staticmethod
    def _build_photo_prompt(subject: str = "") -> str:
        subject_hint = ""
        if subject:
            subject_hint = "用户已指定科目：%s，请按此科目处理。\n" % subject
        return (
            "你是一个题目提取专家。请仔细识别这张图片中的所有题目。\n"
            + subject_hint +
            "请直接输出一个 JSON 对象：\n"
            "{\n"
            '  "subject": 科目代码（从 math/physics/chemistry/english/chinese/biology 中自动判断；无法判断填 "unknown"）,\n'
            '  "questions": [每道题的 JSON 对象数组]\n'
            "}\n"
            "每道题字段:\n"
            "- content: 题目原文\n"
            "- options: 选项列表，如[\"A. xxx\", \"B. xxx\"]；非选择题填 []\n"
            "- answer: 参考答案\n"
            "- type_name: 题型(选择题/填空题/解答题/判断题)\n"
            "- subtype: 子类型(单选/多选/填空/计算/证明/简答/判断)\n"
            "- difficulty: 难度 1-5\n"
            "- explanation: 题目解析(选填)\n"
            "- knowledge_points: 知识点列表(选填)\n"
            "- notes: 图片中的手写备注(无则填\"\")\n"
            "只返回这一个 JSON 对象，不要包含其他任何内容。"
        )

    @staticmethod
    def _parse_page(text: str) -> tuple:
        """解析 VisionModel 回复，兼容包裹对象和纯数组。返回 (questions, subject)。"""
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
            text = text.strip()
            if text.startswith("json"):
                text = text[4:].strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return [], ""
        if isinstance(data, dict):
            qs = data.get("questions") or data.get("items") or []
            if isinstance(qs, dict):
                qs = [qs]
            return (qs if isinstance(qs, list) else []), str(data.get("subject", "") or "").strip()
        if isinstance(data, list):
            return data, ""
        return [], ""

    def _resolve_subject(self, provided: str, detected: str) -> tuple:
        """依次尝试: 视觉模型识别 → 用户提供 → 题库第一个活跃科目。返回 (subject_info, code)。"""
        for code in (detected, provided):
            if not code:
                continue
            info = self._tm.get_subject_by_code(code.strip())
            if info:
                return info, code.strip()
        subjects = self._tm.get_active_subjects()
        if subjects:
            return subjects[0], subjects[0].get("code", "")
        return None, None

    @staticmethod
    def _parse_json(text: str) -> list:
        """兼容旧格式的纯数组解析（保留）。"""
        questions, _ = QuestFromImageTool._parse_page(text)
        return questions

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
