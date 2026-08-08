# tracking/tools.py
# TrackingTools — 供主 AI 通过技能系统访问用户跟踪系统（infra）的工具集合。
#
# 原则：
#   - AI 只能看到【文本数据】（含从其他模态转换来的文本，如音频 ASR 文本、
#     打卡【打卡】记录）；文件路径等非文本信息一律剥离。
#   - AI 为【只读】：不得修改/添加 tracking 记录（不提供任何写工具）。
# 提供：
#   - query_observations  搜索用户的观察日志（仅文本，剥离路径）
#   - query_models        查询建模结果（仅文本）
#   - model_routines      建模用户作息规律/生活节奏
#   - model_progress      建模用户事项/项目观察统计
#   - query_checkin_stats 查询打卡统计（仅文本）
#
# 所有操作严格按 user_id 隔离；AI 访问总开关为 Config.TRACKING_AI_ACCESS_ENABLED。

from __future__ import annotations

import logging

logger = logging.getLogger("tracking.tools")


class TrackingTools:
    _ctx: dict = {}

    @classmethod
    def set_context(cls, tracking_engine=None, db=None):
        if tracking_engine is not None:
            cls._ctx["engine"] = tracking_engine
        if db is not None:
            cls._ctx["db"] = db

    def __init__(self):
        pass

    def _engine(self):
        from .core import TrackingEngine
        engine = self._ctx.get("engine")
        if isinstance(engine, TrackingEngine):
            return engine
        # fallback：独立构造一个仅用于查询的轻量引擎（独立加密库）
        from .store import TrackingStore
        _engine = TrackingEngine.__new__(TrackingEngine)
        _engine.store = TrackingStore()
        _engine._vision = None
        _engine.media = None
        _engine.listener = None
        return _engine

    def _uid(self):
        return self._ctx.get("_uid", 0)

    def _access_enabled(self) -> bool:
        from config import Config
        return bool(getattr(Config, "TRACKING_AI_ACCESS_ENABLED",
                            getattr(Config, "SENSING_AI_ACCESS_ENABLED", False)))

    # ── 净化：AI 可见数据只保留文本，剥离一切文件路径 ──
    @staticmethod
    def _sanitize_record(rec: dict) -> dict:
        """从一条记录中剥离非文本信息（media_path/video_path/audio_path 等）。"""
        out = {
            "id": rec.get("id"),
            "etype": rec.get("etype"),
            "text": rec.get("payload") or "",
            "source": rec.get("source"),
            "created_at": rec.get("created_at"),
        }
        # 保留少量纯文本 meta（如打卡时间），绝不暴露路径
        meta = rec.get("meta") or {}
        safe_meta = {}
        for k in ("checkin_date", "checkin_time", "file_type", "duration"):
            if meta.get(k):
                safe_meta[k] = meta[k]
        if safe_meta:
            out["meta"] = safe_meta
        return out

    # ── 观察日志查询（关键词 + 时间范围 + 类型，全模态，仅文本）──
    def query_observations(self, etype: str = "", since: str = "", until: str = "",
                           keyword: str = "", limit: int = 20) -> dict:
        """搜索当前用户的行为日记文本记录（含从音频/图片/视频/文件转换来的文本）。
        用户问「我刚才周围有什么动静」「我今天旁边有人说话吗」「最近拍了什么」
        「我某天记录过什么」「有没有关于某事的记录」等时使用。
        支持按类型 (etype)、时间范围 (since/until)、关键词 (keyword) 过滤。
        返回按时间倒序的纯文本记录（不含文件路径），只含当前用户自己的数据。
        """
        if not self._access_enabled():
            logger.info("TrackingTools: AI 访问跟踪记录未启用，拒绝查询")
            return {"enabled": False, "error": "AI 访问跟踪记录未启用",
                    "records": [], "count": 0}
        uid = self._uid()
        if not uid:
            return {"enabled": True, "records": [], "count": 0, "error": "无法识别用户"}
        try:
            records = self._engine().query_observations(
                user_id=uid, etype=etype or None, since=since or "", until=until or "",
                keyword=keyword or "", limit=max(1, min(100, int(limit or 20))),
            )
            sanitized = [self._sanitize_record(r) for r in records]
            return {"enabled": True, "records": sanitized, "count": len(sanitized)}
        except Exception as e:
            logger.error("query_observations 失败: %s", e)
            return {"enabled": True, "records": [], "count": 0, "error": str(e)}

    # ── 查询既有建模结果（仅文本）──
    def query_models(self, model_type: str = "") -> dict:
        """查询当前用户已有的建模结果（作息/节奏/进度/项目等）。
        用户问「你之前总结过我的作息吗」「我有哪些跟踪模型」等时使用。
        """
        if not self._access_enabled():
            return {"enabled": False, "error": "AI 访问跟踪记录未启用"}
        uid = self._uid()
        if not uid:
            return {"enabled": True, "models": [], "error": "无法识别用户"}
        try:
            models = self._engine().get_models(user_id=uid, model_type=model_type or None)
            sanitized = []
            for m in models:
                safe = {
                    "id": m.get("id"),
                    "model_type": m.get("model_type"),
                    "title": m.get("title"),
                    "content": m.get("content") or "",
                    "updated_at": m.get("updated_at"),
                }
                meta = m.get("meta") or {}
                # 仅保留文本化统计（去路径类字段）
                safe_meta = {k: v for k, v in meta.items()
                             if k in ("days", "events", "peak_hour", "active_hours",
                                      "style", "stability", "hourly", "total", "by_type")}
                if safe_meta:
                    safe["meta"] = safe_meta
                sanitized.append(safe)
            return {"enabled": True, "models": sanitized, "count": len(sanitized)}
        except Exception as e:
            logger.error("query_models 失败: %s", e)
            return {"enabled": True, "models": [], "error": str(e)}

    # ⚠️ AI 为只读：刻意不提供 add_text_entry / add_file_entry 等写工具，
    #    AI 无法主动修改用户跟踪系统记录的数据。

    # ── 作息 / 生活节奏建模 ──
    def model_routines(self, days: int = 7) -> dict:
        """建模当前用户的作息规律 / 生活节奏。
        用户问「我的作息规律」「我的生活节奏怎么样」「我一般什么时候活跃」等时使用。
        """
        if not self._access_enabled():
            return {"enabled": False, "error": "AI 访问跟踪记录未启用"}
        uid = self._uid()
        if not uid:
            return {"enabled": True, "error": "无法识别用户"}
        try:
            res = self._engine().model_routines(user_id=uid, days=max(1, min(30, int(days or 7))))
            return {"enabled": True, "model": res}
        except Exception as e:
            logger.error("model_routines 失败: %s", e)
            return {"enabled": True, "error": str(e)}

    # ── 事项 / 项目进度观察统计 ──
    def model_progress(self, days: int = 7) -> dict:
        """建模当前用户的近期事项/项目观察统计。
        用户问「我最近在忙什么」「我的进度怎么样」等时使用。
        """
        if not self._access_enabled():
            return {"enabled": False, "error": "AI 访问跟踪记录未启用"}
        uid = self._uid()
        if not uid:
            return {"enabled": True, "error": "无法识别用户"}
        try:
            res = self._engine().model_progress(user_id=uid, days=max(1, min(30, int(days or 7))))
            return {"enabled": True, "model": res}
        except Exception as e:
            logger.error("model_progress 失败: %s", e)
            return {"enabled": True, "error": str(e)}

    # ── 打卡统计（基于 checkins 表）──
    def query_checkin_stats(self) -> dict:
        """查询当前用户的打卡统计：累计打卡天数、连续打卡天数、今日打卡状态、最近记录。

        用户问「我打卡多少天了」「连续打卡几天」「今天打卡了吗」等时使用。
        返回数据仅供当前用户。
        """
        if not self._access_enabled():
            return {"enabled": False, "error": "AI 访问跟踪记录未启用"}
        uid = self._uid()
        if not uid:
            return {"enabled": True, "error": "无法识别用户"}
        db = self._ctx.get("db")
        if db is None or not hasattr(db, "query_checkins"):
            return {"enabled": True, "error": "打卡数据不可用"}
        try:
            from datetime import datetime
            total_days = db.count_checkin_days(uid)
            streak = db.compute_checkin_streak(uid)
            today = db.checkin_date_for(datetime.now())
            today_rec = db.get_today_checkin(uid, today)
            recent = db.query_checkins(uid, limit=7)
            # 只暴露文本：剥离 media_path/video_path/audio_path
            recent_safe = [{
                "id": r.get("id"),
                "checkin_date": r.get("checkin_date"),
                "checkin_time": r.get("checkin_time"),
                "text": r.get("text") or "",
                "is_valid": r.get("is_valid"),
            } for r in recent]
            return {
                "enabled": True,
                "total_days": total_days,
                "streak": streak,
                "today_checked": today_rec is not None,
                "today_checkin_time": (today_rec or {}).get("checkin_time", ""),
                "checkin_date": today,
                "recent": recent_safe,
            }
        except Exception as e:
            logger.error("query_checkin_stats 失败: %s", e)
            return {"enabled": True, "error": str(e)}
