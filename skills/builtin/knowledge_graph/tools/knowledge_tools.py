# skills/builtin/knowledge_graph/tools/knowledge_tools.py

from __future__ import annotations

import logging

logger = logging.getLogger("KnowledgeGraphTool")


class KnowledgeGraphTool:

    def __init__(self, graph_store=None, graph_engine=None,
                 knowledge_matcher=None, models_plugin=None,
                 question_store=None):
        self._store = graph_store
        self._engine = graph_engine
        self._matcher = knowledge_matcher
        self._models = models_plugin
        self._question_store = question_store

    def update_knowledge_state(self, kp_code: str, correct: bool,
                               user_id: int = 0, **kwargs) -> dict:
        if not self._store:
            return {"error": "GraphStore 未初始化"}
        self._store.update_user_state(user_id, kp_code, correct)
        if correct and self._engine:
            self._engine.propagate_mastery(user_id, kp_code)
        state = self._store.get_user_state(user_id, kp_code)
        return {
            "success": True,
            "confidence": state.get("confidence", 0) if state else 0,
            "kp_code": kp_code,
        }

    def get_due_reviews(self, user_id: int = 0, subject: str = None,
                        limit: int = 5, **kwargs) -> dict:
        if not self._engine:
            return {"error": "GraphEngine 未初始化"}
        due = self._engine.recommend_review(user_id, limit=limit)
        if subject:
            due = [d for d in due if d.get("subject") == subject]
        return {
            "success": True,
            "due_count": len(due),
            "items": due,
        }

    def analyze_weakness(self, kp_code: str, user_id: int = 0,
                         **kwargs) -> dict:
        if not self._engine:
            return {"error": "GraphEngine 未初始化"}
        path = self._engine.find_weak_path(user_id, kp_code)
        return {
            "success": True,
            "path": path,
            "path_length": len(path),
            "root_cause": path[0] if path else None,
        }

    def recommend_related(self, kp_code: str, depth: int = 2,
                          **kwargs) -> dict:
        if not self._engine:
            return {"error": "GraphEngine 未初始化"}
        related = self._engine.find_related(kp_code, depth=depth)
        return {
            "success": True,
            "related_count": len(related),
            "items": related,
        }

    def get_mastery_summary(self, subject: str, user_id: int = 0,
                            **kwargs) -> dict:
        if not self._engine:
            return {"error": "GraphEngine 未初始化"}
        summary = self._engine.get_mastery_summary(user_id, subject)
        return {
            "success": True,
            "subject": subject,
            "total": summary.get("total", 0),
            "mastered": summary.get("mastered", 0),
            "weak": summary.get("weak", 0),
            "untouched": summary.get("untouched", 0),
            "mastery_rate": summary.get("mastery_rate", 0),
        }

    def build_from_syllabus(self, subject: str, content: str,
                            user_id: int = 0, **kwargs) -> dict:
        from knowledge_graph.builder import KnowledgeGraphBuilder

        builder = KnowledgeGraphBuilder(
            graph_store=self._store,
            models_plugin=self._models,
        )
        if len(content) > 8000:
            content = content[:8000]
        result = builder.build_from_syllabus(subject, content)
        return result
