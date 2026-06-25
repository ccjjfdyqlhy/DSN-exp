import json
import logging
import re
from typing import Optional

logger = logging.getLogger("KnowledgeMatcher")


class KnowledgeMatcher:

    def __init__(self, graph_store: Optional['GraphStore'] = None,
                 models_plugin=None):
        self._store = graph_store
        self._models = models_plugin

    def match_question_to_kps(self, question_content: str, subject: str) -> list[dict]:
        """题目→知识点匹配 (LLM + 关键词)"""
        # 1. 关键词匹配
        matched = self._keyword_match(question_content, subject)

        # 2. LLM 补充 (如果有 models plugin)
        if self._models:
            try:
                llm_kps = self._llm_match(question_content, subject)
                existing_codes = {m["kp_code"] for m in matched}
                for kp in llm_kps:
                    if kp["kp_code"] not in existing_codes:
                        matched.append(kp)
            except Exception as e:
                logger.warning("LLM 知识点匹配失败: %s", e)

        return matched

    def match_text_to_kps(self, text: str, subject: str) -> list[dict]:
        """文本→知识点匹配"""
        return self.match_question_to_kps(text, subject)

    def extract_kps_from_conversation(self, conversation: str, subject: str) -> list[dict]:
        """从对话中提取知识点"""
        if not self._models:
            return []

        prompt = f"""
从以下对话中提取涉及的知识点，返回 JSON 数组。
每项包含:
- kp_code: 知识点代码 (如 "KP-MATH-001")
- name: 知识点名称
- relevance: 关联度 0.0-1.0

对话:
{conversation[:2000]}

学科: {subject}

只返回 JSON 数组，不要其他内容。
"""
        try:
            response = self._models.send_message(prompt)
            return self._parse_json(response)
        except Exception as e:
            logger.error("对话知识点提取失败: %s", e)
            return []

    def _keyword_match(self, text: str, subject: str) -> list[dict]:
        """基于关键词的快速匹配"""
        if not self._store:
            return []
        text_lower = text.lower()
        nodes = self._store.get_nodes_by_subject(subject)
        matched = []
        for n in nodes:
            name = n.get("name", "").lower()
            aliases = n.get("aliases", [])
            if isinstance(aliases, list):
                all_keywords = [name] + [a.lower() for a in aliases if isinstance(a, str)]
            else:
                all_keywords = [name]
            for kw in all_keywords:
                if kw and kw in text_lower:
                    matched.append({
                        "kp_code": n["kp_code"],
                        "name": n.get("name", ""),
                        "weight": 0.5,
                    })
                    break
        return matched

    def _llm_match(self, content: str, subject: str) -> list[dict]:
        """LLM 匹配知识点"""
        if not self._store:
            return []

        nodes = self._store.get_nodes_by_subject(subject)
        kp_list = "\n".join([f"- {n['kp_code']}: {n['name']}" for n in nodes[:50]])

        prompt = f"""
请从以下知识点列表中，找出与题目内容相关的知识点。

知识点列表:
{kp_list}

题目内容: {content}

返回 JSON 数组，每项包含 kp_code 和 weight (0.0-1.0):
[{{"kp_code": "KP-MATH-001", "weight": 0.9}}, ...]

只返回 JSON 数组，不要其他内容。
"""
        try:
            response = self._models.send_message(prompt)
            result = self._parse_json(response)
            return result
        except Exception as e:
            logger.warning("LLM 知识点匹配异常: %s", e)
            return []

    @staticmethod
    def _parse_json(text: str) -> list[dict]:
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
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("JSON 解析失败: %s", e)
            return []
