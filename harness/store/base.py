# harness/store/base.py
# 通用存储接口 + 迁移机制。

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol, runtime_checkable

logger = logging.getLogger("harness.store")


@runtime_checkable
class IStore(Protocol):
    """存储接口 — 提供连接与关闭。"""

    def get_connection(self) -> Any: ...

    def close(self) -> None: ...


@dataclass
class Migration:
    """一次 schema 迁移。id 需全局唯一且稳定。"""
    id: str
    up: Callable[[Any], None]
    down: Optional[Callable[[Any], None]] = None


class MigrationRunner:
    """按序执行尚未应用的迁移，并在 store 中记录已应用版本。"""

    def __init__(self, store: IStore, *, table: str = "schema_migrations"):
        self._store = store
        self._table = table
        self._ensure_table()

    def _ensure_table(self) -> None:
        conn = self._store.get_connection()
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {self._table} "
            f"(id TEXT PRIMARY KEY, applied_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        conn.commit()

    def applied(self) -> set[str]:
        conn = self._store.get_connection()
        rows = conn.execute(f"SELECT id FROM {self._table}").fetchall()
        return {r[0] for r in rows}

    def migrate(self, migrations: list[Migration]) -> list[str]:
        """应用未执行的迁移，返回本次新应用的 id 列表。"""
        applied = self.applied()
        new_ids: list[str] = []
        for mig in migrations:
            if mig.id in applied:
                continue
            logger.info("应用迁移 %s", mig.id)
            conn = self._store.get_connection()
            try:
                mig.up(conn)
                conn.execute(f"INSERT INTO {self._table} (id) VALUES (?)", (mig.id,))
                conn.commit()
            except Exception:
                conn.rollback()
                logger.exception("迁移 %s 失败", mig.id)
                raise
            new_ids.append(mig.id)
        return new_ids
