
# plan_store.py
# 计划系统 — 三层模型 (Goal → Phase → DailyTask) + SQLite 持久化

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

_global_db = None


def set_plan_db(db):
    global _global_db
    _global_db = db


def get_plan_db():
    return _global_db


@dataclass
class DailyTask:
    task_id: str = ""
    user_id: int = 0
    date: str = ""                # YYYY-MM-DD
    title: str = ""
    subject: str = ""
    duration_min: int = 30
    priority: int = 3              # 1-5
    status: str = "pending"        # pending / done / skipped
    note: str = ""
    goal_id: str = ""
    phase_id: str = ""


@dataclass
class Phase:
    phase_id: str = ""
    goal_id: str = ""
    title: str = ""
    description: str = ""
    start_date: str = ""           # YYYY-MM-DD
    end_date: str = ""
    status: str = "pending"        # pending / active / completed
    progress: float = 0.0
    position: int = 0


@dataclass
class Goal:
    goal_id: str = ""
    user_id: int = 0
    title: str = ""
    description: str = ""
    deadline: str = ""             # YYYY-MM-DD
    status: str = "active"         # active / completed / abandoned
    progress: float = 0.0
    phases: list[Phase] = field(default_factory=list)


class PlanStore:
    """三层计划数据存储（SQLite 持久化）"""

    def __init__(self, db):
        self.db = db
        self._init_tables()

    def _init_tables(self):
        conn = self.db._get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS goals (
                goal_id     TEXT PRIMARY KEY,
                user_id     INTEGER NOT NULL,
                title       TEXT NOT NULL,
                description TEXT DEFAULT '',
                deadline    TEXT,
                status      TEXT DEFAULT 'active',
                progress    REAL DEFAULT 0.0,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS phases (
                phase_id    TEXT PRIMARY KEY,
                goal_id     TEXT NOT NULL,
                title       TEXT NOT NULL,
                description TEXT DEFAULT '',
                start_date  TEXT,
                end_date    TEXT,
                status      TEXT DEFAULT 'pending',
                progress    REAL DEFAULT 0.0,
                position    INTEGER DEFAULT 0,
                FOREIGN KEY (goal_id) REFERENCES goals(goal_id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_tasks (
                task_id     TEXT PRIMARY KEY,
                user_id     INTEGER NOT NULL,
                date        TEXT NOT NULL,
                title       TEXT NOT NULL,
                subject     TEXT DEFAULT '',
                duration_min INTEGER DEFAULT 30,
                priority    INTEGER DEFAULT 3,
                status      TEXT DEFAULT 'pending',
                note        TEXT DEFAULT '',
                goal_id     TEXT DEFAULT '',
                phase_id    TEXT DEFAULT '',
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_goals_user ON goals(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_phases_goal ON phases(goal_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_date ON daily_tasks(date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_user_date ON daily_tasks(user_id, date)")
        # 迁移: 为旧表补充 position 列 (main 分支的 phases 表无此列)
        _phase_cols = [r[1] for r in conn.execute("PRAGMA table_info(phases)").fetchall()]
        if "position" not in _phase_cols:
            conn.execute("ALTER TABLE phases ADD COLUMN position INTEGER DEFAULT 0")
        conn.commit()

    # ── Goal CRUD ──

    def create_goal(self, goal: Goal) -> str:
        conn = self.db._get_connection()
        conn.execute(
            "INSERT INTO goals (goal_id, user_id, title, description, deadline, status, progress) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (goal.goal_id, goal.user_id, goal.title, goal.description, goal.deadline, goal.status, goal.progress),
        )
        conn.commit()
        return goal.goal_id

    def get_goal(self, goal_id: str) -> Optional[Goal]:
        conn = self.db._get_connection()
        r = conn.execute("SELECT * FROM goals WHERE goal_id = ?", (goal_id,)).fetchone()
        if not r:
            return None
        goal = Goal(goal_id=r["goal_id"], user_id=r["user_id"], title=r["title"],
                    description=r["description"] or "", deadline=r["deadline"] or "",
                    status=r["status"], progress=r["progress"])
        goal.phases = self.get_phases(goal_id)
        return goal

    def list_goals(self, user_id: int) -> list[Goal]:
        conn = self.db._get_connection()
        rows = conn.execute("SELECT * FROM goals WHERE user_id = ? ORDER BY created_at DESC", (user_id,)).fetchall()
        goals = []
        for r in rows:
            g = Goal(goal_id=r["goal_id"], user_id=r["user_id"], title=r["title"],
                     description=r["description"] or "", deadline=r["deadline"] or "",
                     status=r["status"], progress=r["progress"])
            g.phases = self.get_phases(g.goal_id)
            goals.append(g)
        return goals

    def update_goal(self, goal: Goal):
        conn = self.db._get_connection()
        conn.execute(
            "UPDATE goals SET title=?, description=?, deadline=?, status=?, progress=? WHERE goal_id=?",
            (goal.title, goal.description, goal.deadline, goal.status, goal.progress, goal.goal_id),
        )
        conn.commit()

    def delete_goal(self, goal_id: str):
        conn = self.db._get_connection()
        conn.execute("DELETE FROM daily_tasks WHERE goal_id = ?", (goal_id,))
        conn.execute("DELETE FROM daily_tasks WHERE phase_id IN (SELECT phase_id FROM phases WHERE goal_id = ?)", (goal_id,))
        conn.execute("DELETE FROM phases WHERE goal_id = ?", (goal_id,))
        conn.execute("DELETE FROM goals WHERE goal_id = ?", (goal_id,))
        conn.commit()

    # ── Phase CRUD ──

    def create_phase(self, phase: Phase) -> str:
        conn = self.db._get_connection()
        conn.execute(
            "INSERT INTO phases (phase_id, goal_id, title, description, start_date, end_date, status, progress, position) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (phase.phase_id, phase.goal_id, phase.title, phase.description,
             phase.start_date, phase.end_date, phase.status, phase.progress, phase.position),
        )
        conn.commit()
        return phase.phase_id

    def get_phases(self, goal_id: str) -> list[Phase]:
        conn = self.db._get_connection()
        rows = conn.execute(
            "SELECT * FROM phases WHERE goal_id = ? ORDER BY position ASC, start_date ASC", (goal_id,)
        ).fetchall()
        return [Phase(phase_id=r["phase_id"], goal_id=r["goal_id"], title=r["title"],
                      description=r["description"] or "", start_date=r["start_date"] or "",
                      end_date=r["end_date"] or "", status=r["status"], progress=r["progress"],
                      position=r["position"] or 0)
                for r in rows]

    # ── DailyTask CRUD ──

    def save_task(self, task: DailyTask):
        conn = self.db._get_connection()
        conn.execute(
            "INSERT OR REPLACE INTO daily_tasks "
            "(task_id, user_id, date, title, subject, duration_min, priority, status, note, goal_id, phase_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (task.task_id, task.user_id, task.date, task.title,
             task.subject, task.duration_min, task.priority, task.status, task.note,
             task.goal_id, task.phase_id),
        )
        conn.commit()

    def get_tasks_by_date(self, user_id: int, date_str: str) -> list[DailyTask]:
        conn = self.db._get_connection()
        rows = conn.execute(
            "SELECT * FROM daily_tasks WHERE user_id = ? AND date = ? ORDER BY priority DESC, created_at ASC",
            (user_id, date_str),
        ).fetchall()
        return [DailyTask(task_id=r["task_id"], user_id=r["user_id"], date=r["date"], title=r["title"],
                          subject=r["subject"] or "", duration_min=r["duration_min"],
                          priority=r["priority"], status=r["status"], note=r["note"] or "",
                          goal_id=r["goal_id"] or "", phase_id=r["phase_id"] or "")
                for r in rows]

    def update_task_status(self, task_id: str, status: str, note: str = ""):
        conn = self.db._get_connection()
        conn.execute("UPDATE daily_tasks SET status=?, note=? WHERE task_id=?",
                     (status, note, task_id))
        conn.commit()
