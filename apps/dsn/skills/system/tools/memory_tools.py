# skills/system/tools/memory_tools.py

import json


class MemoryTools:
    _ctx = {}

    @classmethod
    def set_context(cls, memory_system=None):
        cls._ctx["memory_system"] = memory_system

    def __init__(self):
        pass

    def recall(self, keywords: list, count: int = 3,
               detail: bool = False, activate: bool = False) -> dict:
        ms = self._ctx.get("memory_system")
        if not ms:
            return {"error": "MemorySystem 未注入", "results": []}

        uid = self._ctx.get("_uid", 0)
        cid = self._ctx.get("_cid", 0)
        payload = {"keywords": keywords, "count": count, "detail": detail,
                   "activate": activate}
        result = ms._handle_recall(uid, cid, payload)
        return {"results": result}

    def save_memo(self, content: str) -> dict:
        ms = self._ctx.get("memory_system")
        if not ms:
            return {"error": "MemorySystem 未注入"}

        uid = self._ctx.get("_uid", 0)
        cid = self._ctx.get("_cid", 0)
        ms.add_memo(uid, cid, content)
        return {"saved": True}

    def activate_topic(self, topic_id: int) -> dict:
        """主动激活(持续打开)某个话题: 原文持续注入直到话题结束。"""
        ms = self._ctx.get("memory_system")
        if not ms or not getattr(ms, "_topics", None):
            return {"error": "MemorySystem/TopicManager 未注入"}

        uid = self._ctx.get("_uid", 0)
        cid = self._ctx.get("_cid", 0)
        ok = ms._topics.pin_topic(uid, cid, topic_id)
        return {"activated": ok, "topic_id": topic_id}

    def deactivate_topic(self, topic_id: int) -> dict:
        """取消某话题的持续激活。"""
        ms = self._ctx.get("memory_system")
        if not ms or not getattr(ms, "_topics", None):
            return {"error": "MemorySystem/TopicManager 未注入"}

        uid = self._ctx.get("_uid", 0)
        cid = self._ctx.get("_cid", 0)
        ok = ms._topics.unpin_topic(uid, cid, topic_id)
        return {"deactivated": ok, "topic_id": topic_id}

    def list_topics(self) -> dict:
        """列出本聊天的话题(标题/轮次/状态/摘要)。"""
        ms = self._ctx.get("memory_system")
        if not ms or not getattr(ms, "_topics", None):
            return {"error": "MemorySystem/TopicManager 未注入"}

        uid = self._ctx.get("_uid", 0)
        cid = self._ctx.get("_cid", 0)
        topics = ms._topics.store.list_topics(uid, cid)
        return {"topics": [
            {
                "topic_id": t["topic_id"],
                "title": t.get("title") or None,
                "rounds": f"{t['start_round']}-{t.get('end_round') or '?'}",
                "status": t["status"],
                "summary": (t.get("summary") or "")[:200],
            }
            for t in topics
        ]}
