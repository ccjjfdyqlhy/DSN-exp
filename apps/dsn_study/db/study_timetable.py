# db/study_timetable.py
# 学习时间表 — 周计划时段 + 学习记录追踪 + 统计

import uuid
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger(__name__)

_global_db = None


def set_study_db(db):
    global _global_db
    _global_db = db


def get_study_db():
    return _global_db


# 星期映射：0=Mon, 6=Sun
DAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
DAY_NAMES_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


@dataclass
class TimetableSlot:
    slot_id: str = ""
    user_id: int = 0
    day_of_week: int = 0          # 0=Mon..6=Sun
    start_time: str = "09:00"     # HH:MM
    end_time: str = "10:00"       # HH:MM
    subject: str = ""
    activity_type: str = "study"  # study | review | exam | break
    goal_id: str = ""             # optional link to plan goal
    kp_code: str = ""             # optional link to knowledge point
    enabled: bool = True
    created_at: str = ""


@dataclass
class StudySession:
    session_id: str = ""
    user_id: int = 0
    slot_id: str = ""             # optional FK to timetable slot
    subject: str = ""
    activity_type: str = "study"  # study | review | exam
    date: str = ""                # YYYY-MM-DD
    planned_start: str = ""       # HH:MM
    planned_end: str = ""         # HH:MM
    actual_start: str = ""        # HH:MM (filled when check-in)
    actual_end: str = ""          # HH:MM (filled when check-out)
    duration_min: int = 0
    status: str = "pending"       # pending | active | done | missed
    note: str = ""
    created_at: str = ""


class StudyTimetableStore:
    """学习时间表数据存储（SQLite）"""

    def __init__(self, db):
        self.db = db
        self._init_tables()

    def _init_tables(self):
        conn = self.db._get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS study_timetable_slots (
                slot_id     TEXT PRIMARY KEY,
                user_id     INTEGER NOT NULL,
                day_of_week INTEGER NOT NULL,
                start_time  TEXT NOT NULL,
                end_time    TEXT NOT NULL,
                subject     TEXT NOT NULL DEFAULT '',
                activity_type TEXT NOT NULL DEFAULT 'study',
                goal_id     TEXT DEFAULT '',
                kp_code     TEXT DEFAULT '',
                enabled     INTEGER DEFAULT 1,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS study_sessions (
                session_id  TEXT PRIMARY KEY,
                user_id     INTEGER NOT NULL,
                slot_id     TEXT DEFAULT '',
                subject     TEXT NOT NULL DEFAULT '',
                activity_type TEXT NOT NULL DEFAULT 'study',
                date        TEXT NOT NULL,
                planned_start TEXT DEFAULT '',
                planned_end TEXT DEFAULT '',
                actual_start TEXT DEFAULT '',
                actual_end  TEXT DEFAULT '',
                duration_min INTEGER DEFAULT 0,
                status      TEXT DEFAULT 'pending',
                note        TEXT DEFAULT '',
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS study_stats (
                stat_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                date        TEXT NOT NULL,
                subject     TEXT NOT NULL DEFAULT '',
                planned_min INTEGER DEFAULT 0,
                actual_min  INTEGER DEFAULT 0,
                completed_slots INTEGER DEFAULT 0,
                total_slots INTEGER DEFAULT 0,
                UNIQUE(user_id, date, subject)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_slots_user ON study_timetable_slots(user_id, day_of_week)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_date ON study_sessions(user_id, date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_stats_user_date ON study_stats(user_id, date)")
        conn.commit()

    # ── Timetable Slot CRUD ──

    def create_slot(self, slot: TimetableSlot) -> str:
        conn = self.db._get_connection()
        slot.slot_id = slot.slot_id or str(uuid.uuid4())
        conn.execute(
            "INSERT OR REPLACE INTO study_timetable_slots "
            "(slot_id, user_id, day_of_week, start_time, end_time, subject, "
            " activity_type, goal_id, kp_code, enabled) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (slot.slot_id, slot.user_id, slot.day_of_week, slot.start_time, slot.end_time,
             slot.subject, slot.activity_type, slot.goal_id, slot.kp_code,
             1 if slot.enabled else 0),
        )
        conn.commit()
        logger.info("创建时间槽: %s (%s %s-%s %s)",
                     slot.slot_id[:8], DAY_NAMES[slot.day_of_week],
                     slot.start_time, slot.end_time, slot.subject)
        return slot.slot_id

    def get_slot(self, slot_id: str) -> Optional[TimetableSlot]:
        conn = self.db._get_connection()
        r = conn.execute("SELECT * FROM study_timetable_slots WHERE slot_id = ?",
                         (slot_id,)).fetchone()
        if not r:
            return None
        return self._row_to_slot(r)

    def list_slots(self, user_id: int, day_of_week: int = None) -> list[TimetableSlot]:
        conn = self.db._get_connection()
        if day_of_week is not None:
            rows = conn.execute(
                "SELECT * FROM study_timetable_slots WHERE user_id = ? AND day_of_week = ? "
                "ORDER BY start_time ASC",
                (user_id, day_of_week),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM study_timetable_slots WHERE user_id = ? "
                "ORDER BY day_of_week ASC, start_time ASC",
                (user_id,),
            ).fetchall()
        return [self._row_to_slot(r) for r in rows]

    def list_slots_by_subject(self, user_id: int, subject: str) -> list[TimetableSlot]:
        conn = self.db._get_connection()
        rows = conn.execute(
            "SELECT * FROM study_timetable_slots WHERE user_id = ? AND subject = ? "
            "ORDER BY day_of_week ASC, start_time ASC",
            (user_id, subject),
        ).fetchall()
        return [self._row_to_slot(r) for r in rows]

    def update_slot(self, slot: TimetableSlot):
        conn = self.db._get_connection()
        conn.execute(
            "UPDATE study_timetable_slots SET day_of_week=?, start_time=?, end_time=?, "
            "subject=?, activity_type=?, goal_id=?, kp_code=?, enabled=? WHERE slot_id=?",
            (slot.day_of_week, slot.start_time, slot.end_time, slot.subject,
             slot.activity_type, slot.goal_id, slot.kp_code,
             1 if slot.enabled else 0, slot.slot_id),
        )
        conn.commit()

    def delete_slot(self, slot_id: str):
        conn = self.db._get_connection()
        conn.execute("DELETE FROM study_timetable_slots WHERE slot_id = ?", (slot_id,))
        conn.commit()

    def toggle_slot(self, slot_id: str, enabled: bool):
        conn = self.db._get_connection()
        conn.execute("UPDATE study_timetable_slots SET enabled = ? WHERE slot_id = ?",
                     (1 if enabled else 0, slot_id))
        conn.commit()

    # ── Today's schedule (from timetable) ──

    def get_today_slots(self, user_id: int) -> list[TimetableSlot]:
        """获取今日（根据星期）所有启用的时间槽"""
        dow = date.today().weekday()
        return self.list_slots(user_id, dow)

    # ── Study Session CRUD ──

    def create_session(self, session: StudySession) -> str:
        conn = self.db._get_connection()
        session.session_id = session.session_id or str(uuid.uuid4())
        conn.execute(
            "INSERT OR REPLACE INTO study_sessions "
            "(session_id, user_id, slot_id, subject, activity_type, date, "
            " planned_start, planned_end, actual_start, actual_end, "
            " duration_min, status, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (session.session_id, session.user_id, session.slot_id,
             session.subject, session.activity_type, session.date,
             session.planned_start, session.planned_end,
             session.actual_start, session.actual_end,
             session.duration_min, session.status, session.note),
        )
        conn.commit()
        return session.session_id

    def get_session(self, session_id: str) -> Optional[StudySession]:
        conn = self.db._get_connection()
        r = conn.execute("SELECT * FROM study_sessions WHERE session_id = ?",
                         (session_id,)).fetchone()
        if not r:
            return None
        return self._row_to_session(r)

    def get_sessions_by_date(self, user_id: int, date_str: str) -> list[StudySession]:
        conn = self.db._get_connection()
        rows = conn.execute(
            "SELECT * FROM study_sessions WHERE user_id = ? AND date = ? "
            "ORDER BY planned_start ASC, created_at ASC",
            (user_id, date_str),
        ).fetchall()
        return [self._row_to_session(r) for r in rows]

    def get_active_session(self, user_id: int) -> Optional[StudySession]:
        """获取用户当前进行中的学习时段"""
        conn = self.db._get_connection()
        r = conn.execute(
            "SELECT * FROM study_sessions WHERE user_id = ? AND status = 'active' "
            "ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        return self._row_to_session(r) if r else None

    def update_session_status(self, session_id: str, status: str, **kwargs):
        conn = self.db._get_connection()
        fields = ["status = ?"]
        values = [status]
        for key in ("actual_start", "actual_end", "duration_min", "note"):
            if key in kwargs:
                fields.append(f"{key} = ?")
                values.append(kwargs[key])
        values.append(session_id)
        conn.execute(
            f"UPDATE study_sessions SET {', '.join(fields)} WHERE session_id = ?",
            values,
        )
        conn.commit()
        # 更新统计
        if status in ("done", "missed"):
            self._update_stats_for_session(session_id)

    def _update_stats_for_session(self, session_id: str):
        """更新学习统计"""
        sess = self.get_session(session_id)
        if not sess:
            return
        conn = self.db._get_connection()
        # 获取当天该科目的所有会话统计
        rows = conn.execute(
            "SELECT status, duration_min FROM study_sessions "
            "WHERE user_id = ? AND date = ? AND subject = ?",
            (sess.user_id, sess.date, sess.subject),
        ).fetchall()
        total = len(rows)
        done = sum(1 for r in rows if r["status"] == "done")
        actual_min = sum(r["duration_min"] or 0 for r in rows)
        # 获取该科目当天计划时长
        planned_min = 0
        plan_rows = conn.execute(
            "SELECT start_time, end_time FROM study_timetable_slots "
            "WHERE user_id = ? AND day_of_week = ? AND subject = ? AND enabled = 1",
            (sess.user_id, date.fromisoformat(sess.date).weekday(), sess.subject),
        ).fetchall()
        for pr in plan_rows:
            try:
                sh, sm = map(int, pr["start_time"].split(":"))
                eh, em = map(int, pr["end_time"].split(":"))
                planned_min += (eh * 60 + em) - (sh * 60 + sm)
            except (ValueError, TypeError):
                pass
        conn.execute(
            "INSERT OR REPLACE INTO study_stats "
            "(user_id, date, subject, planned_min, actual_min, completed_slots, total_slots) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sess.user_id, sess.date, sess.subject, planned_min, actual_min, done, total),
        )
        conn.commit()

    # ── Stats ──

    def get_daily_stats(self, user_id: int, date_str: str = "") -> list[dict]:
        if not date_str:
            date_str = date.today().isoformat()
        conn = self.db._get_connection()
        rows = conn.execute(
            "SELECT * FROM study_stats WHERE user_id = ? AND date = ? ORDER BY subject",
            (user_id, date_str),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_weekly_stats(self, user_id: int, week_start: str = "") -> list[dict]:
        """获取一周统计，按天聚合"""
        if not week_start:
            today = date.today()
            week_start = (today - __import__('datetime').timedelta(days=today.weekday())).isoformat()
        conn = self.db._get_connection()
        rows = conn.execute(
            "SELECT date, SUM(planned_min) as planned_min, SUM(actual_min) as actual_min, "
            "SUM(completed_slots) as completed_slots, SUM(total_slots) as total_slots "
            "FROM study_stats WHERE user_id = ? AND date >= ? "
            "GROUP BY date ORDER BY date",
            (user_id, week_start),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_subject_stats(self, user_id: int, subject: str = "") -> dict:
        """获取科目累计统计"""
        conn = self.db._get_connection()
        if subject:
            rows = conn.execute(
                "SELECT SUM(planned_min) as planned, SUM(actual_min) as actual, "
                "SUM(completed_slots) as done, SUM(total_slots) as total "
                "FROM study_stats WHERE user_id = ? AND subject = ?",
                (user_id, subject),
            ).fetchone()
        else:
            rows = conn.execute(
                "SELECT SUM(planned_min) as planned, SUM(actual_min) as actual, "
                "SUM(completed_slots) as done, SUM(total_slots) as total "
                "FROM study_stats WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if not rows:
            return {"planned": 0, "actual": 0, "done": 0, "total": 0, "subject": subject}
        return {"planned": rows["planned"] or 0, "actual": rows["actual"] or 0,
                "done": rows["done"] or 0, "total": rows["total"] or 0, "subject": subject or "全部"}

    # ── Generate today's sessions from timetable ──

    def generate_today_sessions(self, user_id: int) -> list[StudySession]:
        """从时间表生成今天的学习会话"""
        today = date.today()
        date_str = today.isoformat()
        dow = today.weekday()

        # 检查是否已生成
        existing = self.get_sessions_by_date(user_id, date_str)
        if existing:
            return existing

        slots = self.list_slots(user_id, dow)
        sessions = []
        for s in slots:
            if not s.enabled:
                continue
            session = StudySession(
                session_id=str(uuid.uuid4()),
                user_id=user_id,
                slot_id=s.slot_id,
                subject=s.subject,
                activity_type=s.activity_type,
                date=date_str,
                planned_start=s.start_time,
                planned_end=s.end_time,
                status="pending",
            )
            self.create_session(session)
            sessions.append(session)
        logger.info("生成今日学习会话: %d 个 (user=%d, date=%s)", len(sessions), user_id, date_str)
        return sessions

    # ── Check-in / Check-out ──

    def check_in(self, user_id: int, slot_id: str = "", subject: str = "",
                 activity_type: str = "study") -> Optional[StudySession]:
        """开始学习：找到最近的一个待办会话，标记为进行中"""
        # 检查是否有进行中的
        active = self.get_active_session(user_id)
        if active:
            return active

        today = date.today().isoformat()
        sessions = self.get_sessions_by_date(user_id, today)
        now = datetime.now().strftime("%H:%M")

        target = None
        if slot_id:
            target = next((s for s in sessions if s.slot_id == slot_id and s.status == "pending"), None)
        elif subject:
            target = next((s for s in sessions if s.subject == subject and s.status == "pending"), None)
        else:
            # 找最近的一个待办
            target = next((s for s in sessions if s.status == "pending"), None)

        if not target:
            # 无计划，创建即时会话
            target = StudySession(
                session_id=str(uuid.uuid4()),
                user_id=user_id,
                subject=subject or "自习",
                activity_type=activity_type,
                date=today,
                planned_start=now,
                actual_start=now,
                status="active",
            )
            self.create_session(target)
            logger.info("即时签到: session=%s", target.session_id[:8])
        else:
            self.update_session_status(target.session_id, "active",
                                       actual_start=now)
            logger.info("签到: session=%s (%s %s)", target.session_id[:8],
                        target.subject, target.planned_start)
        return target

    def check_out(self, user_id: int, session_id: str = "", note: str = "") -> Optional[StudySession]:
        """结束学习"""
        target = None
        if session_id:
            target = self.get_session(session_id)
        else:
            target = self.get_active_session(user_id)

        if not target:
            return None

        now = datetime.now()
        now_str = now.strftime("%H:%M")
        start_str = target.actual_start or target.planned_start

        # 计算时长
        try:
            sh, sm = map(int, start_str.split(":"))
            eh, em = map(int, now_str.split(":"))
            dur = (eh * 60 + em) - (sh * 60 + sm)
            if dur < 0:
                dur += 1440  # 跨天
        except (ValueError, TypeError):
            dur = 0

        self.update_session_status(target.session_id, "done",
                                   actual_end=now_str, duration_min=dur, note=note)
        logger.info("签退: session=%s 时长=%dmin", target.session_id[:8], dur)
        target.duration_min = dur
        target.actual_end = now_str
        target.status = "done"
        return target

    # ── Helper ──

    @staticmethod
    def _row_to_slot(r) -> TimetableSlot:
        return TimetableSlot(
            slot_id=r["slot_id"], user_id=r["user_id"],
            day_of_week=r["day_of_week"], start_time=r["start_time"],
            end_time=r["end_time"], subject=r["subject"] or "",
            activity_type=r["activity_type"] or "study",
            goal_id=r["goal_id"] or "", kp_code=r["kp_code"] or "",
            enabled=bool(r["enabled"]),
            created_at=r.get("created_at", "") or "",
        )

    @staticmethod
    def _row_to_session(r) -> StudySession:
        return StudySession(
            session_id=r["session_id"], user_id=r["user_id"],
            slot_id=r["slot_id"] or "", subject=r["subject"] or "",
            activity_type=r["activity_type"] or "study",
            date=r["date"], planned_start=r["planned_start"] or "",
            planned_end=r["planned_end"] or "",
            actual_start=r["actual_start"] or "",
            actual_end=r["actual_end"] or "",
            duration_min=r["duration_min"] or 0, status=r["status"],
            note=r["note"] or "", created_at=r.get("created_at", "") or "",
        )
