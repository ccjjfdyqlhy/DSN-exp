# apps/dsn_study/document/grading.py
# 视觉判分模型 — 从已作答的试卷图片中分离题目原文、题图描述与学生答案。
#
# 移植自参考实现 DSN-exp models/clients.py 的 GradingModel（该类继承 VisionModel）。
# dsn_study 的 VisionModel 已下沉 infra/orchestrator/vision.py，
# 这里同样以子类形式复用，保持 extract_answer_sheet / _parse_answer_sheet 契约不变。

from __future__ import annotations

import json as _json
import logging

from apps.dsn_study.models.clients import VisionModel

logger = logging.getLogger("GradingModel")


class GradingModel(VisionModel):
    """视觉判分模型 — 试卷批改场景专用。"""

    def extract_answer_sheet(self, data_url: str, max_tokens: int = 8192) -> dict:
        """从一页已作答的试卷图片中提取所有题目与学生答案。

        :return: {"pages": [{"page_number": int, "questions": [
                  {"question_index", "question_text", "image_description",
                   "student_answer"}]}]}
        """
        if not data_url:
            return {"pages": []}

        prompt = (
            "你是一名试卷批改助手。下面是一张已作答的试卷图片。\n\n"
            "请仔细识别图片中所有的题目和学生的作答，按以下 JSON 格式输出：\n"
            "{\n"
            '  "pages": [\n'
            "    {\n"
            '      "page_number": 1,\n'
            '      "questions": [\n'
            "        {\n"
            '          "question_index": 0,\n'
            '          "question_text": "题目原文（包括所有选项 A/B/C/D）",\n'
            '          "image_description": "如果题目配有图表/图片，请描述其内容；无图则为 null",\n'
            '          "student_answer": "学生填写的答案"\n'
            "        }\n"
            "      ]\n"
            "    }\n"
            "  ]\n"
            "}\n\n"
            "要求：\n"
            "1. 题目原文和学生答案严格分开，不要混在一起\n"
            "2. 题目有配图（几何图、函数图、表格等）时在 image_description 中描述其关键信息\n"
            "3. 学生写了多个答案时以最终/最明显的答案为准\n"
            "4. 只返回 JSON，不要包含其他内容\n"
            "5. 确保题目原文完整，选择题保留 A/B/C/D 选项"
        )

        try:
            text = self.ask(data_url, prompt=prompt, max_tokens=max_tokens,
                            temperature=0.1)
            return self._parse_answer_sheet(text)
        except Exception as e:
            logger.error("extract_answer_sheet 失败: %s", e)
            return {"pages": [], "error": str(e)}

    def extract_answer_sheet_batch(self, images: list, max_tokens: int = 8192) -> dict:
        """批量处理多页答题卡，合并为一个 answer_sheet。"""
        all_pages = []
        for i, img in enumerate(images or []):
            filename = img.get("filename", "page_%d" % i)
            data_url = img.get("data_url", "")
            if not data_url:
                continue
            page_result = self.extract_answer_sheet(data_url, max_tokens)
            pages = page_result.get("pages") or []
            for p in pages:
                p["source_file"] = filename
            all_pages.extend(pages)
        return {"pages": all_pages, "total_pages": len(all_pages)}

    @staticmethod
    def _parse_answer_sheet(text: str) -> dict:
        text = (text or "").strip()
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
            return _json.loads(text)
        except _json.JSONDecodeError:
            return {"pages": [], "error": "JSON 解析失败: %s" % text[:300]}
