# apps/dsn_study/db/checkin_store.py
# 打卡数据层 — 自 apps/dsn/db/chat.py 的 checkins 表与方法移植
# （dsn_study 功能补齐阶段 4）。
#
# 差异：study 版为纯软件打卡（无视频/音频媒体列的写入来源，列保留以对齐
# dsn schema；media_* 恒空）；去掉对 users 表的 FOREIGN KEY（study 库无
# users 表，且连接开启 PRAGMA foreign_keys=ON）。

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("CheckinStore")


class CheckinStore:
    """打卡存取（挂在题库主库连接上，表名/语义与 dsn 对齐）。"""

    def __init__(self, db):
        self._db = db
        self._init_table()

    def _get_connection(self) -> sqlite3.Connection:
        return self._db._get_connection()

    def _init_table(self):
        conn = self._get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS checkins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                checkin_date TEXT NOT NULL,
                checkin_time TEXT NOT NULL,
                media_path TEXT DEFAULT '',
                video_path TEXT DEFAULT '',
                audio_path TEXT DEFAULT '',
                text TEXT DEFAULT '',
                is_valid INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_checkins_user_date "
                     "ON checkins(user_id, checkin_date)")
        conn.commit()

    # ── 日期边界 ──

    @staticmethod
    def checkin_date_for(dt: datetime) -> str:
        """按"凌晨4点边界"归并日期：当天 0:00-3:59:59 属于前一天。
        例：2026-08-08 03:00 → '2026-08-07'；2026-08-08 04:00 → '2026-08-08'。
        """
        if dt.hour < 4:
            dt = dt - timedelta(days=1)
        return dt.strftime("%Y-%m-%d")

    # ── 写入 ──

    def add_checkin(self, user_id: int, checkin_date: str, checkin_time: str,
                    media_path: str = "", video_path: str = "", audio_path: str = "",
                    text: str = "") -> int:
        """写入一条打卡记录。

        同一天内：若该日尚无记录，则本条为有效打卡 (is_valid=1)；否则为附加记录 (is_valid=0)。
        """
        conn = self._get_connection()
        try:
            existing = conn.execute(
                "SELECT id FROM checkins WHERE user_id=? AND checkin_date=? LIMIT 1",
                (user_id, checkin_date),
            ).fetchone()
            is_valid = 1 if existing is None else 0
            cursor = conn.execute(
                "INSERT INTO checkins (user_id, checkin_date, checkin_time, media_path, "
                "video_path, audio_path, text, is_valid) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, checkin_date, checkin_time, media_path,
                 video_path, audio_path, text, is_valid),
            )
            conn.commit()
            return cursor.lastrowid
        except sqlite3.Error as e:
            logger.error("添加打卡记录失败: %s", e)
            conn.rollback()
            raise

    # ── 查询 ──

    def get_today_checkin(self, user_id: int, checkin_date: str) -> Optional[dict]:
        """查询某打卡日（4点边界）的有效打卡记录（最早一次），无则返回 None。"""
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT id, user_id, checkin_date, checkin_time, media_path, video_path, "
                "audio_path, text, is_valid, created_at FROM checkins "
                "WHERE user_id=? AND checkin_date=? ORDER BY is_valid DESC, id ASC LIMIT 1",
                (user_id, checkin_date),
            ).fetchone()
            return dict(row) if row else None
        except sqlite3.Error as e:
            logger.error("查询今日打卡失败: %s", e)
            return None

    def count_checkin_days(self, user_id: int) -> int:
        """统计用户历史有效打卡天数（按打卡日去重）。"""
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(DISTINCT checkin_date) AS n FROM checkins "
                "WHERE user_id=? AND is_valid=1",
                (user_id,),
            ).fetchone()
            return int(row["n"]) if row else 0
        except sqlite3.Error as e:
            logger.error("统计打卡天数失败: %s", e)
            return 0

    def query_checkins(self, user_id: int, limit: int = 30) -> list[dict]:
        """查询用户打卡历史（按时间倒序）。"""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT id, user_id, checkin_date, checkin_time, media_path, video_path, "
                "audio_path, text, is_valid, created_at FROM checkins "
                "WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_id, max(1, int(limit))),
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.Error as e:
            logger.error("查询打卡历史失败: %s", e)
            return []

    def checkin_dates_set(self, user_id: int, limit: int = 1000) -> set[str]:
        """返回用户全部有效打卡日（去重 set），供连续天数/日历计算。"""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT DISTINCT checkin_date FROM checkins "
                "WHERE user_id=? AND is_valid=1 ORDER BY checkin_date DESC LIMIT ?",
                (user_id, max(1, int(limit))),
            ).fetchall()
            return {r["checkin_date"] for r in rows}
        except sqlite3.Error as e:
            logger.error("获取打卡日期集合失败: %s", e)
            return set()

    def compute_checkin_streak(self, user_id: int) -> int:
        """计算用户当前连续打卡天数。

        以"今天"（自然日）为基准，按 checkin_date 从今天往前数连续天数；
        若今天未打卡则从昨天往前数（保持"截至最近一次"的连续）。
        """
        dates = self.checkin_dates_set(user_id)
        if not dates:
            return 0
        today = datetime.now().date()
        streak = 0
        if today.strftime("%Y-%m-%d") not in dates:
            today = today - timedelta(days=1)
        while today.strftime("%Y-%m-%d") in dates:
            streak += 1
            today = today - timedelta(days=1)
        return streak

    def month_calendar(self, user_id: int, year: int, month: int) -> dict:
        """某月的打卡日历：返回当月每日是否有有效打卡。"""
        dates = self.checkin_dates_set(user_id)
        days: dict[str, bool] = {}
        day = datetime(year, month, 1)
        while day.month == month:
            key = day.strftime("%Y-%m-%d")
            days[key] = key in dates
            day += timedelta(days=1)
        return days
