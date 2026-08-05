# skills/system/tools/sensing_tools.py
# 闲置时感知记录查询工具 — 供主 AI 根据上下文查询用户闲置时捕捉到的环境声音。

import logging

logger = logging.getLogger("skill.system.sensing")


class SensingTools:
    _ctx = {}

    @classmethod
    def set_context(cls, db=None):
        cls._ctx["db"] = db

    def __init__(self):
        pass

    def _db(self):
        db = self._ctx.get("db")
        if not db:
            raise RuntimeError("数据库未注入")
        return db

    def _uid(self):
        return self._ctx.get("_uid", 0)

    def query_sensing_events(self, since: str = "", until: str = "",
                             limit: int = 20, keyword: str = "") -> dict:
        """查询当前用户在闲置/非对话时段被捕捉到的环境声音记录（闲置时感知）。

        仅在服务端 SENSING_AI_ACCESS_ENABLED=true 时可用；未启用时返回
        enabled=false 且不泄露任何数据。始终只返回当前用户的记录。
        """
        from config import Config
        if not getattr(Config, "SENSING_AI_ACCESS_ENABLED", False):
            logger.info("SensingTools: AI 访问闲置时感知记录未启用，拒绝查询")
            return {"enabled": False, "error": "AI 访问闲置时感知记录未启用",
                    "records": [], "count": 0}

        db = self._db()
        uid = self._uid()
        if not uid:
            return {"enabled": True, "records": [], "count": 0,
                    "error": "无法识别用户"}
        try:
            records = db.query_sensing_events(
                uid, since=since or "", until=until or "",
                limit=max(1, min(100, int(limit or 20))), keyword=keyword or "")
            return {"enabled": True, "records": records, "count": len(records)}
        except Exception as e:
            logger.error("query_sensing_events 失败: %s", e)
            return {"enabled": True, "records": [], "count": 0, "error": str(e)}
