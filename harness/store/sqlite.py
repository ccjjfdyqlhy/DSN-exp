# harness/store/sqlite.py
# SqliteStore — 通用 SQLite 存储实现。
#
# 单连接模型：store 拥有连接生命周期，调用方通过 get_connection()
# 复用同一连接（不要自行 close）。线程间通过内部锁串行化写操作。

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any


class SqliteStore:
    def __init__(self, path: str = ":memory:", *, row_factory: Any = sqlite3.Row):
        self.path = str(path)
        # timeout 限制 SQLite 锁等待时间，避免写锁竞争时无限阻塞事件循环
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        self._conn.row_factory = row_factory
        self._conn.execute("PRAGMA busy_timeout=10000")
        self._lock = threading.RLock()

    def get_connection(self) -> sqlite3.Connection:
        """返回共享连接。调用方不得 close。"""
        return self._conn

    def execute(self, sql: str, params: tuple = ()) -> list:
        """便捷执行：SELECT/PRAGMA 返回行，写操作自动提交。"""
        with self._lock:
            cur = self._conn.execute(sql, params)
            if sql.lstrip().upper().startswith(("SELECT", "PRAGMA")):
                rows = cur.fetchall()
            else:
                self._conn.commit()
                rows = []
            return rows

    def execute_many(self, sql: str, seq_of_params: list[tuple]) -> None:
        with self._lock:
            self._conn.executemany(sql, seq_of_params)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def exists(self) -> bool:
        return self.path != ":memory:" and Path(self.path).exists()
