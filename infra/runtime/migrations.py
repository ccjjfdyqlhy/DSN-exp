# infra/runtime/migrations.py
# 托管运行时的建表迁移（策划案 §5.1）。
#
# 表结构照策划案 §5.1 抄，**只加不改**：
#   runtime_session     会话
#   runtime_turn        轮次
#   runtime_event       只追加事实（真相来源）
#   runtime_checkpoint  快照（可丢弃）
#   tool_result_cache   幂等结果缓存
#
# 唯一一处**增加**：idx_event_idem 索引（session_id, idempotency_key）。
#   理由：恢复时要按幂等键回查「这次调用到底有没有结果」——
#   没有索引就只能全表扫，而全表扫的代价会随着 journal 增长线性上升，
#   恰好在最需要它的时候（崩溃恢复、journal 最长的时候）最慢。
#   加索引是纯增量，不改任何列定义，所以不影响 Postgres 迁移的等价性。
#
# 迁移机制复用 infra/store/base.py 的 MigrationRunner —— 不自己再造一套。

from __future__ import annotations

import logging
from typing import Any

from infra.store.base import IStore, Migration, MigrationRunner

logger = logging.getLogger('infra.runtime.migrations')

#: 建表 DDL（一次迁移搞定 rc0 的运行时表）
_RUNTIME_SCHEMA = """
CREATE TABLE IF NOT EXISTS runtime_session (
  id TEXT PRIMARY KEY, tenant TEXT, artifact_id TEXT, artifact_version TEXT,
  deployment_id TEXT, workspace_id TEXT, status TEXT, budget_json TEXT,
  created_at REAL, updated_at REAL
);

CREATE TABLE IF NOT EXISTS runtime_turn (
  id TEXT PRIMARY KEY, session_id TEXT, seq INTEGER, status TEXT,
  input_json TEXT, checkpoint_ref TEXT, usage_json TEXT, cost_json TEXT,
  stop_reason TEXT, created_at REAL, updated_at REAL,
  UNIQUE(session_id, seq)
);

CREATE TABLE IF NOT EXISTS runtime_event (
  session_id TEXT, turn_id TEXT, seq INTEGER, kind TEXT, payload_json TEXT,
  ts REAL, idempotency_key TEXT,
  PRIMARY KEY (session_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_event_kind ON runtime_event(kind, ts);
CREATE INDEX IF NOT EXISTS idx_event_idem ON runtime_event(session_id, idempotency_key);

CREATE TABLE IF NOT EXISTS runtime_checkpoint (
  session_id TEXT, turn_seq INTEGER, blob_json TEXT, created_at REAL,
  PRIMARY KEY (session_id, turn_seq)
);

CREATE TABLE IF NOT EXISTS tool_result_cache (
  idempotency_key TEXT PRIMARY KEY, tool TEXT, version TEXT,
  result_json TEXT, effect TEXT, created_at REAL
);
"""


def _create_runtime_tables(conn: Any) -> None:
    conn.executescript(_RUNTIME_SCHEMA)


#: rc0 运行时迁移列表（id 必须全局唯一且稳定 —— 迁移记录表靠它去重）
RUNTIME_MIGRATIONS: list[Migration] = [
    Migration(id='rc0_runtime_001', up=_create_runtime_tables),
]


def migrate_runtime(store: IStore) -> list[str]:
    """把运行时表建好，返回本次新应用的迁移 id 列表。

    幂等：重复调用不会重复建表，也不会重复记迁移。
    """
    runner = MigrationRunner(store)
    applied = runner.migrate(RUNTIME_MIGRATIONS)
    if applied:
        logger.info('托管运行时表已就绪: %s', applied)
    return applied


__all__ = ['RUNTIME_MIGRATIONS', 'migrate_runtime']
