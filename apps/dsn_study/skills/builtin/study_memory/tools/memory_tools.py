# apps/dsn_study/skills/builtin/study_memory/tools/memory_tools.py
# 自 apps/dsn/skills/system/tools/memory_tools.py 移植（dsn_study 功能补齐阶段 2）。
# 差异：实例属性注入（对齐 study 技能依赖注入机制）+ uid 默认 1；话题工具保留
# 但 study 侧话题系统休眠（调用会返回友好错误）。

import json


class MemoryTools:
    _ctx = {}

    @classmethod
    def set_context(cls, memory_system=None):
        cls._ctx["memory_system"] = memory_system

    def __init__(self):
        self.memory_system = None

    def _ms(self):
        ms = getattr(self, "memory_system", None) or self._ctx.get("memory_system")
        if not ms:
            raise RuntimeError("MemorySystem 未注入")
        return ms

    def _uid(self):
        # study 为单用户应用：默认归属本地用户 uid=1（与 LocalAuthManager 对齐）
        return self._ctx.get("_uid", 1) or 1

    def _cid(self):
        return self._ctx.get("_cid", 0)

    def recall(self, keywords: list, count: int = 3,
               detail: bool = False) -> dict:
        """按关键词检索长期记忆。detail=true 时附带命中轮次的完整对话还原。"""
        ms = self._ms()
        payload = {"keywords": keywords, "count": count, "detail": detail}
        result = ms._handle_recall(self._uid(), self._cid(), payload)
        return {"results": result}

    def save_memo(self, content: str) -> dict:
        """保存一条长期备忘（用户偏好、约定、重要事实等，跨会话可见）。"""
        ms = self._ms()
        mid = ms.add_memo(self._uid(), self._cid(), content)
        return {"saved": True, "memo_id": mid}
