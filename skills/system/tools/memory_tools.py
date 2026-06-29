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
               detail: bool = False) -> dict:
        ms = self._ctx.get("memory_system")
        if not ms:
            return {"error": "MemorySystem 未注入", "results": []}

        uid = self._ctx.get("_uid", 0)
        cid = self._ctx.get("_cid", 0)
        payload = {"keywords": keywords, "count": count, "detail": detail}
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
