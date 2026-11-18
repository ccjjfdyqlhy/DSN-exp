# infra/runtime/store.py
# 托管运行时的**存储端口**（StorePort）与 SQLite 实现。
#
# 【为什么要有这一层】
#   策划案 §5.1 的表结构是「SQLite 起步，接口可换 Postgres」。
#   如果 journal / checkpoint / idempotency 各写各的 SQL，
#   换库时就得把这三层全翻一遍 —— 而它们是恢复逻辑的地基，
#   翻错一行就是「崩溃后重复扣款」。所以：
#     * 上层（journal / checkpoint / idempotency / recovery / managed）
#       只认 StorePort 这个 Protocol，**不出现一个 SQL 字符串**；
#     * 端口的方法是**领域语义**（append_event / load_checkpoint），
#       不是 SQL 片段（这样 Postgres 实现不需要做 SQL 方言翻译）；
#     * SqliteRuntimeStore 是这个端口的 SQLite 实现，内部复用
#       infra/store/sqlite.py 的 SqliteStore（连接生命周期 + 写锁都在那），
#       不再自己造一个 sqlite3 连接。
#
# 端口方法名刻意与 SQL 解耦：rc1 换成 Postgres 时，上层调用方一行不改。

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Optional, Protocol, Sequence, runtime_checkable

from infra.store.base import IStore

from .state import (
    CheckpointRecord,
    EventRecord,
    SessionRecord,
    ToolResultRecord,
    TurnRecord,
)

logger = logging.getLogger('infra.runtime.store')


@runtime_checkable
class StorePort(Protocol):
    """托管运行时的存储端口。

    实现方：SqliteRuntimeStore（rc0）/ PostgresRuntimeStore（rc1）。
    调用方只应该通过它访问数据库。
    """

    # ── 会话 / 轮次 ──────────────────────────────────────
    def upsert_session(self, session: SessionRecord) -> None: ...

    def get_session(self, session_id: str) -> Optional[SessionRecord]: ...

    def upsert_turn(self, turn: TurnRecord) -> None: ...

    def get_turn(self, session_id: str, seq: int) -> Optional[TurnRecord]: ...

    def list_turns(self, session_id: str) -> list[TurnRecord]: ...

    def last_open_turn(self, session_id: str) -> Optional[TurnRecord]: ...

    # ── 事件（只追加）────────────────────────────────────
    def append_event(self, event: EventRecord) -> EventRecord: ...

    def list_events(self, session_id: str, *, after_seq: int = 0,
                    kinds: Optional[Sequence[str]] = None,
                    limit: Optional[int] = None) -> list[EventRecord]: ...

    def last_event_seq(self, session_id: str) -> int: ...

    # ── 检查点 ───────────────────────────────────────────
    def put_checkpoint(self, checkpoint: CheckpointRecord) -> None: ...

    def load_checkpoint(self, session_id: str,
                        turn_seq: Optional[int] = None) -> Optional[CheckpointRecord]: ...

    def list_checkpoints(self, session_id: str) -> list[CheckpointRecord]: ...

    # 可选扩展：清理旧检查点（CheckpointStore.prune 会探测它是否存在）。
    # 不放进 Protocol —— 它不是恢复流程的必需能力，只是省磁盘。
    def prune_checkpoints(self, session_id: str, keep: int = 1) -> int: ...

    # ── 幂等结果缓存 ─────────────────────────────────────
    def get_tool_result(self, idempotency_key: str) -> Optional[ToolResultRecord]: ...

    def put_tool_result(self, record: ToolResultRecord) -> None: ...

    # ── 按幂等键回查事件（意图 / 结果）────────────────────
    def find_tool_event(self, session_id: str, idempotency_key: str,
                        kind: str) -> Optional[EventRecord]: ...


def _dumps(value: Any) -> str:
    """稳定地把对象写成 JSON。

    default=repr 是刻意的：工具结果里可能混进不可序列化的对象
    （文件句柄、SDK 的自定义类），**绝不能因为写不进 journal 就把整次调用丢掉**。
    宁可存成 repr 字符串（人还能看懂），也不要崩。
    """
    return json.dumps(value, ensure_ascii=False, default=repr)


def _loads_strict(text: Optional[str]) -> Any:
    """严格解析 JSON；坏了就返回 None（由调用方判断「这是不是损坏」）。

    检查点用它：损坏的快照必须**显式**变成「不可用」，
    而不是被悄悄吞成空字典 —— 空字典是一个合法的快照。
    """
    if text is None:
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _loads(text: Optional[str], default: Any = None) -> Any:
    """容错地读 JSON —— 损坏的行不能让整个恢复流程崩掉。"""
    if not text:
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        logger.warning('journal 行损坏，按空值处理')
        return default


class SqliteRuntimeStore:
    """StorePort 的 SQLite 实现。

    复用 infra/store/sqlite.py 的 SqliteStore：
      * 连接生命周期由 store 拥有（调用方不要 close）
      * 写操作串行化（本类另有一把锁，见下）

    【为什么本类还要自己一把锁】
      SqliteStore.execute() 每次调用各自加锁 —— 一次调用里的多条语句
      之间并没有互斥。而「取 max(seq) 再插入」这种两步操作必须原子，
      否则两个线程会抢到同一个 seq。所以本类用一把 RLock 把
      「读水位线 + 写入」包成临界区，并配合 BEGIN IMMEDIATE 拿到写锁。
    """

    def __init__(self, store: IStore):
        self._store = store
        self._lock = threading.RLock()

    # ── 内部工具 ─────────────────────────────────────────
    @property
    def _conn(self) -> Any:
        return self._store.get_connection()

    def _query(self, sql: str, params: tuple = ()) -> list[Any]:
        with self._lock:
            cur = self._conn.execute(sql, params)
            return list(cur.fetchall())

    def _write(self, sql: str, params: tuple = ()) -> None:
        """执行一条写语句并提交（自带事务边界）。"""
        with self._lock:
            conn = self._conn
            # 先关掉可能残留的隐式事务，否则 BEGIN IMMEDIATE 会报
            # "cannot start a transaction within a transaction"。
            conn.commit()
            conn.execute('BEGIN IMMEDIATE')
            try:
                conn.execute(sql, params)
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    # ── 会话 ─────────────────────────────────────────────
    def upsert_session(self, session: SessionRecord) -> None:
        self._write(
            'INSERT INTO runtime_session (id, tenant, artifact_id, artifact_version,'
            ' deployment_id, workspace_id, status, budget_json, created_at, updated_at)'
            ' VALUES (?,?,?,?,?,?,?,?,?,?)'
            ' ON CONFLICT(id) DO UPDATE SET tenant=excluded.tenant,'
            ' artifact_id=excluded.artifact_id, artifact_version=excluded.artifact_version,'
            ' deployment_id=excluded.deployment_id, workspace_id=excluded.workspace_id,'
            ' status=excluded.status, budget_json=excluded.budget_json,'
            ' updated_at=excluded.updated_at',
            (session.id, session.tenant, session.artifact_id, session.artifact_version,
             session.deployment_id, session.workspace_id, session.status,
             _dumps(session.budget), session.created_at, session.updated_at),
        )

    def get_session(self, session_id: str) -> Optional[SessionRecord]:
        rows = self._query('SELECT * FROM runtime_session WHERE id = ?', (session_id,))
        if not rows:
            return None
        row = rows[0]
        return SessionRecord(
            id=row['id'],
            tenant=row['tenant'] or '',
            artifact_id=row['artifact_id'] or '',
            artifact_version=row['artifact_version'] or '',
            deployment_id=row['deployment_id'] or '',
            workspace_id=row['workspace_id'] or '',
            status=row['status'] or '',
            budget=_loads(row['budget_json'], {}) or {},
            created_at=row['created_at'] or 0.0,
            updated_at=row['updated_at'] or 0.0,
        )

    # ── 轮次 ─────────────────────────────────────────────
    def upsert_turn(self, turn: TurnRecord) -> None:
        self._write(
            'INSERT INTO runtime_turn (id, session_id, seq, status, input_json,'
            ' checkpoint_ref, usage_json, cost_json, stop_reason, created_at, updated_at)'
            ' VALUES (?,?,?,?,?,?,?,?,?,?,?)'
            ' ON CONFLICT(id) DO UPDATE SET status=excluded.status,'
            ' input_json=excluded.input_json, checkpoint_ref=excluded.checkpoint_ref,'
            ' usage_json=excluded.usage_json, cost_json=excluded.cost_json,'
            ' stop_reason=excluded.stop_reason, updated_at=excluded.updated_at',
            (turn.id, turn.session_id, turn.seq, turn.status, _dumps(turn.input),
             turn.checkpoint_ref, _dumps(turn.usage), _dumps(turn.cost),
             turn.stop_reason, turn.created_at, turn.updated_at),
        )

    def get_turn(self, session_id: str, seq: int) -> Optional[TurnRecord]:
        rows = self._query(
            'SELECT * FROM runtime_turn WHERE session_id = ? AND seq = ?',
            (session_id, seq))
        if not rows:
            return None
        return self._row_to_turn(rows[0])

    def list_turns(self, session_id: str) -> list[TurnRecord]:
        rows = self._query(
            'SELECT * FROM runtime_turn WHERE session_id = ? ORDER BY seq ASC',
            (session_id,))
        return [self._row_to_turn(row) for row in rows]

    def last_open_turn(self, session_id: str) -> Optional[TurnRecord]:
        """最后一个「未结束」的轮次 —— 恢复时它就是续跑目标。

        故意不按 seq 取最后一行：一个已经 SUCCEEDED 的 turn 排在
        一个 PENDING 的 turn 后面（并发轮次）时，取最后一行会挑错对象。
        """
        rows = self._query(
            'SELECT * FROM runtime_turn WHERE session_id = ?'
            " AND status IN ('pending','running','awaiting_approval','interrupted')"
            ' ORDER BY seq DESC LIMIT 1',
            (session_id,))
        if not rows:
            return None
        return self._row_to_turn(rows[0])

    @staticmethod
    def _row_to_turn(row: Any) -> TurnRecord:
        return TurnRecord(
            id=row['id'],
            session_id=row['session_id'],
            seq=row['seq'],
            status=row['status'] or '',
            input=_loads(row['input_json'], {}) or {},
            checkpoint_ref=row['checkpoint_ref'] or '',
            usage=_loads(row['usage_json'], {}) or {},
            cost=_loads(row['cost_json'], {}) or {},
            stop_reason=row['stop_reason'] or '',
            created_at=row['created_at'] or 0.0,
            updated_at=row['updated_at'] or 0.0,
        )

    # ── 事件 ─────────────────────────────────────────────
    def append_event(self, event: EventRecord) -> EventRecord:
        """追加一条事件，返回带**真实 seq** 的记录。

        seq 在会话内单调递增：先读水位线再插入，两步必须原子，
        所以整段跑在 BEGIN IMMEDIATE 事务里（并发写者要么在前者提交后读，
        要么直接被写锁挡在外面）。
        """
        with self._lock:
            conn = self._conn
            conn.commit()
            conn.execute('BEGIN IMMEDIATE')
            try:
                row = conn.execute(
                    'SELECT COALESCE(MAX(seq), 0) FROM runtime_event WHERE session_id = ?',
                    (event.session_id,)).fetchone()
                seq = int(row[0]) + 1
                conn.execute(
                    'INSERT INTO runtime_event (session_id, turn_id, seq, kind,'
                    ' payload_json, ts, idempotency_key) VALUES (?,?,?,?,?,?,?)',
                    (event.session_id, event.turn_id, seq, event.kind,
                     _dumps(event.payload), event.ts, event.idempotency_key))
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        event.seq = seq
        return event

    def list_events(self, session_id: str, *, after_seq: int = 0,
                    kinds: Optional[Sequence[str]] = None,
                    limit: Optional[int] = None) -> list[EventRecord]:
        sql = 'SELECT * FROM runtime_event WHERE session_id = ? AND seq > ?'
        params: list[Any] = [session_id, after_seq]
        if kinds:
            placeholders = ','.join('?' for _ in kinds)
            sql += f' AND kind IN ({placeholders})'
            params.extend(kinds)
        sql += ' ORDER BY seq ASC'
        if limit is not None:
            sql += ' LIMIT ?'
            params.append(limit)
        rows = self._query(sql, tuple(params))
        return [self._row_to_event(row) for row in rows]

    def last_event_seq(self, session_id: str) -> int:
        rows = self._query(
            'SELECT COALESCE(MAX(seq), 0) FROM runtime_event WHERE session_id = ?',
            (session_id,))
        return int(rows[0][0]) if rows else 0

    @staticmethod
    def _row_to_event(row: Any) -> EventRecord:
        return EventRecord(
            session_id=row['session_id'],
            seq=row['seq'],
            kind=row['kind'],
            turn_id=row['turn_id'] or '',
            payload=_loads(row['payload_json'], {}) or {},
            ts=row['ts'] or 0.0,
            idempotency_key=row['idempotency_key'] or '',
        )

    # ── 检查点 ───────────────────────────────────────────
    def put_checkpoint(self, checkpoint: CheckpointRecord) -> None:
        self._write(
            'INSERT INTO runtime_checkpoint (session_id, turn_seq, blob_json, created_at)'
            ' VALUES (?,?,?,?)'
            ' ON CONFLICT(session_id, turn_seq) DO UPDATE SET'
            ' blob_json=excluded.blob_json, created_at=excluded.created_at',
            (checkpoint.session_id, checkpoint.turn_seq,
             _dumps(checkpoint.blob), checkpoint.created_at),
        )

    def load_checkpoint(self, session_id: str,
                        turn_seq: Optional[int] = None) -> Optional[CheckpointRecord]:
        if turn_seq is None:
            rows = self._query(
                'SELECT * FROM runtime_checkpoint WHERE session_id = ?'
                ' ORDER BY turn_seq DESC LIMIT 1',
                (session_id,))
        else:
            rows = self._query(
                'SELECT * FROM runtime_checkpoint WHERE session_id = ? AND turn_seq = ?',
                (session_id, turn_seq))
        if not rows:
            return None
        row = rows[0]
        # blob 解析失败 → None：checkpoint.py 会把它判成「这份快照不可用」
        return CheckpointRecord(
            session_id=row['session_id'],
            turn_seq=row['turn_seq'],
            blob=_loads_strict(row['blob_json']),
            created_at=row['created_at'] or 0.0,
        )

    def list_checkpoints(self, session_id: str) -> list[CheckpointRecord]:
        rows = self._query(
            'SELECT * FROM runtime_checkpoint WHERE session_id = ? ORDER BY turn_seq ASC',
            (session_id,))
        return [CheckpointRecord(
            session_id=row['session_id'],
            turn_seq=row['turn_seq'],
            blob=_loads_strict(row['blob_json']),
            created_at=row['created_at'] or 0.0,
        ) for row in rows]

    def prune_checkpoints(self, session_id: str, keep: int = 1) -> int:
        """只保留最近 keep 份检查点，返回删掉的份数。

        检查点是**加速器**，留着不会更安全，只会占磁盘；
        真正的真相是 journal（它一行都不会少）。
        """
        if keep < 0:
            keep = 0
        with self._lock:
            conn = self._conn
            conn.commit()
            conn.execute('BEGIN IMMEDIATE')
            try:
                rows = conn.execute(
                    'SELECT turn_seq FROM runtime_checkpoint WHERE session_id = ?'
                    ' ORDER BY turn_seq DESC', (session_id,)).fetchall()
                victims = [int(row[0]) for row in rows[keep:]]
                for turn_seq in victims:
                    conn.execute(
                        'DELETE FROM runtime_checkpoint WHERE session_id = ? AND turn_seq = ?',
                        (session_id, turn_seq))
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return len(victims)

    # ── 幂等缓存 ─────────────────────────────────────────
    def get_tool_result(self, idempotency_key: str) -> Optional[ToolResultRecord]:
        """查这次调用的结果。

        缓存表是**加速器**，journal 才是真相：
        如果进程在「写完 result 事件、还没写缓存」之间死了，
        缓存会没有这条 —— 但事件在。所以这里缓存未命中时回落到 journal，
        否则恢复后会**重复执行**一次已经跑完的工具（对 effectful 是事故）。
        """
        rows = self._query(
            'SELECT * FROM tool_result_cache WHERE idempotency_key = ?',
            (idempotency_key,))
        if rows:
            row = rows[0]
            return ToolResultRecord(
                idempotency_key=row['idempotency_key'],
                tool=row['tool'] or '',
                version=row['version'] or '',
                result=_loads(row['result_json']),
                effect=row['effect'] or '',
                created_at=row['created_at'] or 0.0,
            )
        event = self.find_tool_event_by_key(idempotency_key, 'tool_result')
        if event is None:
            return None
        return ToolResultRecord(
            idempotency_key=idempotency_key,
            tool=str(event.payload.get('tool', '')),
            version=str(event.payload.get('tool_version', '')),
            result=event.payload.get('result'),
            effect=str(event.payload.get('effect', '')),
            created_at=event.ts,
        )

    def find_tool_event(self, session_id: str, idempotency_key: str,
                        kind: str) -> Optional[EventRecord]:
        """按 (session, 幂等键, kind) 回查一条事件（取最早的一条）。"""
        rows = self._query(
            'SELECT * FROM runtime_event WHERE session_id = ? AND idempotency_key = ?'
            ' AND kind = ? ORDER BY seq ASC LIMIT 1',
            (session_id, idempotency_key, kind))
        if not rows:
            return None
        return self._row_to_event(rows[0])

    def find_tool_event_by_key(self, idempotency_key: str,
                               kind: str) -> Optional[EventRecord]:
        """不带 session 的回查 —— 幂等键本身已经包含 session。"""
        rows = self._query(
            'SELECT * FROM runtime_event WHERE idempotency_key = ? AND kind = ?'
            ' ORDER BY seq ASC LIMIT 1',
            (idempotency_key, kind))
        if not rows:
            return None
        return self._row_to_event(rows[0])

    def put_tool_result(self, record: ToolResultRecord) -> None:
        self._write(
            'INSERT INTO tool_result_cache (idempotency_key, tool, version,'
            ' result_json, effect, created_at) VALUES (?,?,?,?,?,?)'
            ' ON CONFLICT(idempotency_key) DO UPDATE SET tool=excluded.tool,'
            ' version=excluded.version, result_json=excluded.result_json,'
            ' effect=excluded.effect, created_at=excluded.created_at',
            (record.idempotency_key, record.tool, record.version,
             _dumps(record.result), record.effect, record.created_at),
        )


__all__ = ['StorePort', 'SqliteRuntimeStore']
