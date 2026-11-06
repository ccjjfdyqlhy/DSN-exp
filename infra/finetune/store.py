
# infra/finetune/store.py
# 训练作业与适配器版本的持久化（SQLite）。
#
# 落在 infra/store/ 的通用 SqliteStore 之上（不自己造连接管理）。
# 两张表：
#   finetune_jobs  —— 作业状态快照（提交即落库，进程重启后仍能查到历史）
#   finetune_slots —— "哪个适配器当前生效"的登记表（晋级 / 回滚的依据）
#
# 晋级与回滚为什么要有登记表：
#   训练产出的 LoRA 只是一份候选产物；真正"上线"意味着某个角色
#   （比如某个学生模型槽位）改用它。回滚 = 把槽位指回上一个适配器。
#   没有这张表，"上一个"就无从谈起。

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Optional

from ..store.base import Migration, MigrationRunner
from ..store.sqlite import SqliteStore
from .base import JobState, TrainJob, TrainSpec

logger = logging.getLogger("infra.finetune.store")

#: 迁移 id 必须全局唯一（与 infra/store/chat_store.py 的迁移共用同一张
#: schema_migrations 表）。
_MIGRATIONS = [
    Migration("finetune_001_jobs", lambda c: c.executescript(
        """
        CREATE TABLE IF NOT EXISTS finetune_jobs (
            id TEXT PRIMARY KEY,
            state TEXT NOT NULL,
            spec TEXT NOT NULL,
            created_at REAL NOT NULL,
            started_at REAL,
            finished_at REAL,
            adapter_path TEXT DEFAULT '',
            log_path TEXT DEFAULT '',
            error TEXT DEFAULT '',
            metrics TEXT DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_finetune_jobs_created
            ON finetune_jobs(created_at DESC);
        """
    )),
    Migration("finetune_002_slots", lambda c: c.executescript(
        """
        CREATE TABLE IF NOT EXISTS finetune_slots (
            slot TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            previous_job_id TEXT DEFAULT '',
            promoted_at REAL NOT NULL
        );
        """
    )),
]


class FinetuneStore:
    """训练作业存储。线程安全（内部锁 + SQLite 事务）。"""

    def __init__(self, path: str | Path = ":memory:"):
        self._store = SqliteStore(str(path))
        self._lock = threading.RLock()
        if str(path) != ":memory:":
            self._store.execute("PRAGMA journal_mode=WAL")
        MigrationRunner(self._store).migrate(_MIGRATIONS)

    # ── 作业 ──

    def save_job(self, job: TrainJob) -> None:
        with self._lock:
            self._store.execute(
                """
                INSERT INTO finetune_jobs
                    (id, state, spec, created_at, started_at, finished_at,
                     adapter_path, log_path, error, metrics)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    state=excluded.state, started_at=excluded.started_at,
                    finished_at=excluded.finished_at, adapter_path=excluded.adapter_path,
                    log_path=excluded.log_path, error=excluded.error,
                    metrics=excluded.metrics
                """,
                (
                    job.id,
                    job.state.value,
                    json.dumps(job.spec.to_dict(), ensure_ascii=False),
                    job.created_at,
                    job.started_at,
                    job.finished_at,
                    job.adapter_path,
                    job.log_path,
                    job.error,
                    json.dumps(job.metrics, ensure_ascii=False),
                ),
            )

    def get_job(self, job_id: str) -> Optional[TrainJob]:
        rows = self._store.execute(
            "SELECT * FROM finetune_jobs WHERE id = ?", (job_id,)
        )
        if not rows:
            return None
        return self._row_to_job(rows[0])

    def list_jobs(self, limit: int = 50) -> list[TrainJob]:
        rows = self._store.execute(
            "SELECT * FROM finetune_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return [self._row_to_job(r) for r in rows]

    def jobs_in_state(self, state: JobState) -> list[TrainJob]:
        rows = self._store.execute(
            "SELECT * FROM finetune_jobs WHERE state = ? ORDER BY created_at DESC", (state.value,)
        )
        return [self._row_to_job(r) for r in rows]

    @staticmethod
    def _row_to_job(row: Any) -> TrainJob:
        spec = TrainSpec.from_dict(json.loads(row["spec"]))
        metrics = json.loads(row["metrics"] or "{}")
        return TrainJob(
            id=row["id"],
            spec=spec,
            state=JobState(row["state"]),
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            adapter_path=row["adapter_path"] or "",
            log_path=row["log_path"] or "",
            error=row["error"] or "",
            metrics=metrics,
        )

    # ── 槽位（晋级 / 回滚） ──

    def promote(self, slot: str, job_id: str) -> dict[str, Any]:
        """把某个作业的适配器设为槽位当前生效版本。返回变更记录。"""
        with self._lock:
            rows = self._store.execute(
                "SELECT job_id FROM finetune_slots WHERE slot = ?", (slot,)
            )
            previous = rows[0]["job_id"] if rows else ""
            self._store.execute(
                """
                INSERT INTO finetune_slots (slot, job_id, previous_job_id, promoted_at)
                VALUES (?,?,?,?)
                ON CONFLICT(slot) DO UPDATE SET
                    job_id=excluded.job_id,
                    previous_job_id=excluded.previous_job_id,
                    promoted_at=excluded.promoted_at
                """,
                (slot, job_id, previous, time.time()),
            )
        logger.info("槽位 %s 晋级: %s → %s", slot, previous or "(空)", job_id)
        return {"slot": slot, "job_id": job_id, "previous_job_id": previous}

    def active(self, slot: str) -> Optional[str]:
        rows = self._store.execute(
            "SELECT job_id FROM finetune_slots WHERE slot = ?", (slot,)
        )
        return rows[0]["job_id"] if rows else None

    def rollback(self, slot: str) -> dict[str, Any]:
        """回滚：把槽位指回上一个适配器。"""
        with self._lock:
            rows = self._store.execute(
                "SELECT job_id, previous_job_id FROM finetune_slots WHERE slot = ?", (slot,)
            )
            if not rows:
                return {"slot": slot, "job_id": "", "previous_job_id": "", "rolled_back": False}
            current = rows[0]["job_id"]
            previous = rows[0]["previous_job_id"] or ""
            if not previous:
                return {
                    "slot": slot, "job_id": current,
                    "previous_job_id": "", "rolled_back": False,
                    "reason": "没有上一个版本可回滚",
                }
            self._store.execute(
                """
                UPDATE finetune_slots
                SET job_id = ?, previous_job_id = '', promoted_at = ?
                WHERE slot = ?
                """,
                (previous, time.time(), slot),
            )
        logger.info("槽位 %s 回滚: %s → %s", slot, current, previous)
        return {
            "slot": slot, "job_id": previous,
            "previous_job_id": current, "rolled_back": True,
        }

    def slots(self) -> list[dict[str, Any]]:
        rows = self._store.execute("SELECT * FROM finetune_slots")
        return [dict(r) for r in rows]

    def close(self) -> None:
        self._store.close()
