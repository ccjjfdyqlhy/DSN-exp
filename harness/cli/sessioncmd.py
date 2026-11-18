# harness/cli/sessioncmd.py
# `aicf session` —— 会话与恢复。
#
# `aicf session list --db <path>`    列出托管运行时的会话
# `aicf session resume <session_id> --db <path>`  从 journal 恢复，
#                                      报告最后一个未完成的 turn 与
#                                      哪些副作用的结果未知
#
# 「结果未知」（unknown_outcome）是这一条命令存在的理由：
# 崩溃之后最重要的问题是「哪些事我可能已经做过了」。

from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import eprint, out_json


def _open_store(db_path: str):
    from infra.store.sqlite import SqliteStore
    store = SqliteStore(db_path)
    try:
        from infra.runtime import migrate_runtime
        migrate_runtime(store)
    except Exception:  # noqa: BLE001
        pass
    return store


def cmd_list(args: Any) -> int:
    store = _open_store(args.db)
    try:
        rows = store.execute(
            'SELECT id, status, created_at, updated_at FROM runtime_session '
            'ORDER BY created_at DESC')
    except Exception as error:  # noqa: BLE001
        eprint(f'读取会话失败: {error}')
        return 2
    finally:
        store.close()
    payload = [dict(row) for row in rows]
    if args.json:
        out_json(payload)
        return 0
    if not payload:
        print('(没有会话)')
        return 0
    for row in payload:
        print(f'{row["id"]}  {row["status"]}')
    return 0


def cmd_resume(args: Any) -> int:
    store = _open_store(args.db)
    try:
        from infra.runtime import SqliteRuntimeStore
        runtime_store = SqliteRuntimeStore(store)
        plan = runtime_store.recovery_plan(args.session_id)
    except Exception as error:  # noqa: BLE001
        eprint(f'恢复失败: {error}')
        return 2
    finally:
        store.close()

    payload = plan.to_dict() if hasattr(plan, 'to_dict') else {
        'session_id': args.session_id, 'replayable': [], 'unknown': [],
    }
    if args.json:
        out_json(payload)
        return 0
    print(f'会话 {args.session_id} 的恢复计划：')
    replayable = payload.get('replayable') or []
    unknown = payload.get('unknown') or []
    print(f'  可安全重放: {len(replayable)}')
    for item in replayable:
        print(f'    - {item.get("tool", "?")}')
    print(f'  结果未知（需要人工确认）: {len(unknown)}')
    for item in unknown:
        print(f'    - {item.get("tool", "?")} '
              f'{item.get("idempotency_key", "")[:12]}')
    if unknown:
        print('（这些调用不会自动重放 —— 请人工确认后再决定）')
    return 0


__all__ = ['cmd_list', 'cmd_resume']
