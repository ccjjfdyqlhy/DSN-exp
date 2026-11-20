# infra/store/documents.py
# 文档存储：把「一整份 JSON 文档」放进数据库，而不是散在项目根目录的 .json 文件。
#
# 为什么需要它：
#   应用把自己的状态写成项目根目录下的 JSON（``.harness_todo.json``、
#   ``predictor.json``、``wires.json``…），于是**agent 正在改的那个仓库**
#   里长出了一堆与代码无关的文件。用户看到的不是「���个会话的待办」，
#   而是一堆不知道是谁写的文件 —— 而且它们会被 git 看见。
#
#   文档存储给出的是**同一份契约**（一整份 JSON，读成整体、写回整体），
#   区别只在字节落在哪：落在应用自己的数据库里，而不是项目里。
#
# 接口刻意做小：
#   load(key) -> dict | None      取一整份文档
#   save(key, data)               写回一整份文档（原子替换）
#   delete(key) -> bool           删掉一份
#   keys(prefix) -> list[str]     列出（可按前缀过滤）
#
# 为什么不叫「KV」：这里的值是**文档**（结构化 JSON），不是字符串。
# 需要字符串键值对的应用用 sqlite 自己那张表就行。

from __future__ import annotations

import json
import threading
from typing import Any, Iterable, Mapping, Optional, Protocol, runtime_checkable

from .sqlite import SqliteStore

#: 文档表的名字。放在 store 里而不是模块常量，是为了让多租户/多库
#: 的应用可以给每库一张自己的表。
DEFAULT_TABLE = "documents"


@runtime_checkable
class DocumentStore(Protocol):
    """一整份 JSON 文档的读写接口。"""

    def load(self, key: str) -> Optional[dict[str, Any]]:
        """取一份文档；没有就是 None。"""
        ...

    def save(self, key: str, data: Mapping[str, Any]) -> None:
        """写回一整份文档。"""
        ...

    def delete(self, key: str) -> bool:
        """删掉一份文档；返回它是否本来就在。"""
        ...

    def keys(self, prefix: str = "") -> list[str]:
        """列出文档的键（可按前缀过滤）。"""
        ...


class MemoryDocumentStore:
    """内存实现：测试与临时会话用。"""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def load(self, key: str) -> Optional[dict[str, Any]]:
        with self._lock:
            data = self._data.get(key)
            return json.loads(json.dumps(data)) if data is not None else None

    def save(self, key: str, data: Mapping[str, Any]) -> None:
        with self._lock:
            self._data[key] = json.loads(json.dumps(dict(data)))

    def delete(self, key: str) -> bool:
        with self._lock:
            return self._data.pop(key, None) is not None

    def keys(self, prefix: str = "") -> list[str]:
        with self._lock:
            return sorted(k for k in self._data if k.startswith(prefix))


class SqliteDocumentStore:
    """SQLite 实现：文档落在应用自己的数据库里。

    用 ``infra.store.SqliteStore`` 而不是自己开连接，是为了让同一份数据库
    只有**一个**连接在写 —— sqlite 的写锁是进程级的，两个连接同时写会
    撞上 "database is locked"。应用已经有 store 实例时直接复用它：

        store = SqliteStore(path)
        docs = SqliteDocumentStore(store)

    没有 store 时按路径自己建一个（生命周期归这个对象）。
    """

    def __init__(self, store: Optional[SqliteStore] = None, *,
                 db_path: str = ":memory:", table: str = DEFAULT_TABLE) -> None:
        self._owns = store is None
        self.store = store or SqliteStore(db_path)
        self.table = table
        self._lock = threading.RLock()
        self._ensure_table()

    def _ensure_table(self) -> None:
        self.store.execute(
            f'CREATE TABLE IF NOT EXISTS "{self.table}" ('
            ' key TEXT PRIMARY KEY,'
            ' payload TEXT NOT NULL,'
            ' updated_at REAL NOT NULL)')

    def load(self, key: str) -> Optional[dict[str, Any]]:
        rows = self.store.execute(
            f'SELECT payload FROM "{self.table}" WHERE key = ?', (str(key),))
        if not rows:
            return None
        try:
            data = json.loads(rows[0][0])
        except (TypeError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def save(self, key: str, data: Mapping[str, Any]) -> None:
        import time
        payload = json.dumps(dict(data), ensure_ascii=False, default=str)
        with self._lock:
            self.store.execute(
                f'INSERT INTO "{self.table}" (key, payload, updated_at) '
                'VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET '
                'payload = excluded.payload, updated_at = excluded.updated_at',
                (str(key), payload, time.time()))

    def delete(self, key: str) -> bool:
        with self._lock:
            rows = self.store.execute(
                f'SELECT 1 FROM "{self.table}" WHERE key = ?', (str(key),))
            existed = bool(rows)
            self.store.execute(
                f'DELETE FROM "{self.table}" WHERE key = ?', (str(key),))
            return existed

    def keys(self, prefix: str = "") -> list[str]:
        rows = self.store.execute(
            f'SELECT key FROM "{self.table}" WHERE key LIKE ? ORDER BY key',
            (f'{prefix}%',))
        return [str(row[0]) for row in rows]


def document_store(store: Any = None, *, db_path: str = ":memory:",
                   table: str = DEFAULT_TABLE) -> DocumentStore:
    """拿一个文档存储：复用已有的 store，或按路径新建一个。

    这个小函数是为了让调用点少写一次 ``isinstance`` 判断 —— 传进来的
    东西可能已经是 DocumentStore 了。
    """
    if isinstance(store, DocumentStore):
        return store
    return SqliteDocumentStore(store, db_path=db_path, table=table)


__all__ = [
    "DEFAULT_TABLE",
    "DocumentStore",
    "MemoryDocumentStore",
    "SqliteDocumentStore",
    "document_store",
]
