import json
import logging
from typing import Optional

logger = logging.getLogger("KnowledgeGraphBuilder")


class KnowledgeGraphBuilder:

    def __init__(self, graph_store: Optional['GraphStore'] = None,
                 models_plugin=None):
        self._store = graph_store
        self._models = models_plugin

    def build_from_textbook(self, subject: str, textbook_content: str) -> dict:
        """从教材内容构建知识图"""
        if not self._models:
            return {"success": False, "error": "ModelsPlugin 未注入，无法构建"}

        prompt = f"""
请从以下教材内容中提取知识点结构，构建知识图谱。
学科: {subject}

输出 JSON 格式:
{{
  "nodes": [
    {{"kp_code": "KP-{subject.upper()}-001", "name": "知识点名称", "level": 0, "parent_code": null, "description": "描述"}},
    ...
  ],
  "edges": [
    {{"source": "KP-{subject.upper()}-001", "target": "KP-{subject.upper()}-002", "edge_type": "parent_of", "weight": 1.0}},
    ...
  ]
}}

规则:
- level 0 = 顶层概念, level 5 = 叶子节点
- edge_type: parent_of / prerequisite / related
- 节点之间通过 parent_of 形成树结构

教材内容:
{textbook_content[:8000]}
"""
        try:
            response = self._models.send_message(prompt)
            graph_data = self._parse_json(response)
            return self._save_graph(graph_data, subject)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def build_from_syllabus(self, subject: str, syllabus: str) -> dict:
        """从考纲构建知识图"""
        if not self._models:
            return {"success": False, "error": "ModelsPlugin 未注入"}

        prompt = f"""
请从以下考纲提取知识点结构，构建知识图谱。
学科: {subject}

输出 JSON 格式:
{{
  "nodes": [...],
  "edges": [...]
}}

考纲内容:
{syllabus[:8000]}
"""
        try:
            response = self._models.send_message(prompt)
            graph_data = self._parse_json(response)
            return self._save_graph(graph_data, subject)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def expand_node(self, kp_code: str, depth: int = 1) -> dict:
        """扩展节点: 自动生成子节点和关系"""
        if not self._store or not self._models:
            return {"success": False, "error": "依赖未注入"}

        node = self._store.get_node(kp_code)
        if not node:
            return {"success": False, "error": f"节点不存在: {kp_code}"}

        prompt = f"""
请为以下知识点展开子知识点，输出扩展示例。

父知识点: {node['name']} ({kp_code})
学科: {node['subject']}

输出 JSON:
{{
  "nodes": [
    {{"kp_code": "扩展代码", "name": "子知识点", "level": {node.get('level', 0)+1}, "parent_code": "{kp_code}"}}
  ],
  "edges": [
    {{"source": "{kp_code}", "target": "子节点代码", "edge_type": "parent_of"}}
  ]
}}
"""
        try:
            response = self._models.send_message(prompt)
            graph_data = self._parse_json(response)
            return self._save_graph(graph_data, node["subject"])
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _save_graph(self, graph_data: dict, subject: str) -> dict:
        """保存构建的知识图到数据库"""
        if not self._store:
            return {"success": False, "error": "GraphStore 未注入"}

        nodes = graph_data.get("nodes", [])
        edges = graph_data.get("edges", [])
        node_count = 0
        edge_count = 0

        for n in nodes:
            ok = self._store.add_node(
                kp_code=n.get("kp_code", ""),
                subject=n.get("subject", subject),
                name=n.get("name", ""),
                level=n.get("level", 0),
                parent_code=n.get("parent_code"),
                aliases=n.get("aliases", []),
                description=n.get("description", ""),
                metadata=n.get("metadata", {}),
            )
            if ok:
                node_count += 1

        for e in edges:
            ok = self._store.add_edge(
                source=e.get("source", ""),
                target=e.get("target", ""),
                edge_type=e.get("edge_type", "related"),
                weight=e.get("weight", 1.0),
            )
            if ok:
                edge_count += 1

        return {
            "success": True,
            "node_count": node_count,
            "edge_count": edge_count,
            "subject": subject,
        }

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
            result = json.loads(text)
            if isinstance(result, dict):
                return result
            return {"nodes": [], "edges": []}
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("JSON 解析失败: %s", e)
            return {"nodes": [], "edges": []}
