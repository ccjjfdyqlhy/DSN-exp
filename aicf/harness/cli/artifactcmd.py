# harness/cli/artifactcmd.py
# `aicf artifact` —— Agent 资产的校验 / 列表 / 发布（策划案 §5.4）。
#
#   aicf artifact validate a.yaml        声明校验（不落库）
#   aicf artifact list [--id X]          目录快照（含状态）
#   aicf artifact show a.yaml            解析后的声明
#   aicf artifact publish a.yaml --gate <report_id>
#
# 发布的硬规则（策划案 §4.5.2）：**必须携带通过的 Gate 报告**。
# 发布链路：登记（版本不可变）→ review → approve → release；
# release 会用评测面的 gate_lookup 查报告，verdict != pass 一律阻断。

from __future__ import annotations

from typing import Any

from aicf.infra.control.artifact import ArtifactError, load_artifact
from aicf.infra.control.lifecycle import (
    LifecycleError,
    allowed_actions,
)
from aicf.infra.control.store import ArtifactStore, VersionConflictError

from .common import eprint, out_json


def cmd_validate(args: Any) -> int:
    """校验声明：解析 + 语义检查（内核名 / 工具引用 / 记忆层）。"""
    try:
        artifact = load_artifact(args.path)
    except ArtifactError as error:
        eprint(f'Error: {error}')
        return 1
    payload = {
        'name': artifact.name,
        'version': artifact.version,
        'owner': artifact.metadata.owner,
        'kernel': artifact.spec_kernel,
        'tools': list(artifact.spec_tools),
        'content_hash': artifact.content_hash(),
        'valid': True,
    }
    if args.json:
        out_json(payload)
    else:
        eprint(f"✔ {artifact.name}@{artifact.version}"
               f" kernel={artifact.spec_kernel}"
               f" tools={len(artifact.spec_tools)}")
        eprint(f"  content_hash={artifact.content_hash()[:16]}…")
    return 0


def cmd_show(args: Any) -> int:
    try:
        artifact = load_artifact(args.path)
    except ArtifactError as error:
        eprint(f'Error: {error}')
        return 1
    if args.json:
        out_json(artifact.to_dict())
    else:
        eprint(artifact.to_yaml())
    return 0


def _open_store(db_path: str) -> ArtifactStore:
    """打开控制面存储，并接上评测面的 Gate 报告查询。

    两个面的表都在同一个 sqlite 文件里（策划案 §5.1 的表结构就是
    一个库起步），gate_lookup 只读 eval_gate_report。
    """
    from aicf.infra.eval.trace_store import TraceStore
    from aicf.infra.store.sqlite import SqliteStore

    store = SqliteStore(db_path)
    trace_store = TraceStore(db_path)

    def gate_lookup(report_id: str) -> dict | None:
        try:
            return trace_store.get_gate_report(report_id)
        except Exception:  # noqa: BLE001
            return None

    return ArtifactStore(store, gate_lookup=gate_lookup)


def cmd_publish(args: Any) -> int:
    try:
        artifact = load_artifact(args.path)
    except ArtifactError as error:
        eprint(f'Error: {error}')
        return 1
    if not (args.gate or '').strip():
        eprint('Error: 发布必须携带 Gate 报告（--gate <report_id>）。'
               '发布必须证明这次变更过了四道闸门（策划案 §4.5.2）')
        return 2
    store = _open_store(args.db)
    try:
        event = store.publish(artifact, actor=args.actor,
                              gate_report_id=args.gate)
    except VersionConflictError as error:
        eprint(f'Error: {error}')
        return 1
    except LifecycleError as error:
        eprint(f'Error: 发布被阻断：{error}')
        return 1
    payload = {
        'artifact': artifact.name,
        'version': artifact.version,
        'state': event.to_state,
        'gate_report': args.gate,
        'actor': event.actor,
    }
    if args.json:
        out_json(payload)
    else:
        eprint(f"✔ {artifact.name}@{artifact.version} → {event.to_state}"
               f" (gate={args.gate})")
    return 0


def cmd_list(args: Any) -> int:
    store = _open_store(args.db)
    records = store.list_artifacts(artifact_id=args.id or '',
                                   state=args.state or '')
    rows = []
    for record in records:
        actions = allowed_actions(record.state)
        rows.append({
            'id': record.id,
            'version': record.version,
            'owner': record.owner,
            'state': record.state,
            'content_hash': record.content_hash[:16],
            'allowed_actions': list(actions),
        })
    if args.json:
        out_json(rows)
    else:
        if not rows:
            eprint('（控制面里还没有资产）')
        for row in rows:
            eprint(f"{row['id']}@{row['version']}  {row['state']}"
                   f"  hash={row['content_hash']}…  可做: {row['allowed_actions']}")
    return 0


def cmd_history(args: Any) -> int:
    store = _open_store(args.db)
    events = store.lifecycle_events(args.id, args.version or '')
    rows = [event.to_dict() for event in events]
    if args.json:
        out_json(rows)
    else:
        for row in rows:
            eprint(f"{row['created_at']:.0f}  {row['from_state']} → "
                   f"{row['to_state']}  ({row['action']})  by={row['actor']}"
                   f"  gate={row['gate_report_id'] or '-'}"
                   f"  {row['reason']}")
    return 0


def cmd_rollback(args: Any) -> int:
    """一键回滚（策划案 §4.5.2/§7.2 C2：可一键回滚到上一版本）。"""
    store = _open_store(args.db)
    try:
        event = store.transition(args.id, args.version, 'rollback',
                                 actor=args.actor, reason=args.reason or 'rollback')
    except LifecycleError as error:
        eprint(f'Error: {error}')
        return 1
    if args.json:
        out_json(event.to_dict())
    else:
        eprint(f"✔ {args.id}@{args.version} → {event.to_state}")
    return 0


def register(sub: Any) -> None:
    """把 artifact 子命令挂到 aicf 主解析器上。"""
    artifact = sub.add_parser('artifact', help='Agent 资产（校验/列表/发布/回滚）')
    artifact_sub = artifact.add_subparsers(dest='artifact_command')

    validate = artifact_sub.add_parser('validate', help='校验 artifact 声明')
    validate.add_argument('path')
    validate.add_argument('--json', action='store_true')

    show = artifact_sub.add_parser('show', help='查看解析后的声明')
    show.add_argument('path')
    show.add_argument('--json', action='store_true')

    publish = artifact_sub.add_parser('publish', help='发布（必须携带 Gate 报告）')
    publish.add_argument('path')
    publish.add_argument('--gate', required=True, help='通过的 Gate 报告 ID')
    publish.add_argument('--actor', default='cli')
    publish.add_argument('--db', default='aicf.db')
    publish.add_argument('--json', action='store_true')

    lst = artifact_sub.add_parser('list', help='资产目录快照')
    lst.add_argument('--id', default='')
    lst.add_argument('--state', default='')
    lst.add_argument('--db', default='aicf.db')
    lst.add_argument('--json', action='store_true')

    history = artifact_sub.add_parser('history', help='生命周期事件')
    history.add_argument('id')
    history.add_argument('--version', default='')
    history.add_argument('--db', default='aicf.db')
    history.add_argument('--json', action='store_true')

    rollback = artifact_sub.add_parser('rollback', help='回滚一个版本')
    rollback.add_argument('id')
    rollback.add_argument('version')
    rollback.add_argument('--actor', default='cli')
    rollback.add_argument('--reason', default='')
    rollback.add_argument('--db', default='aicf.db')
    rollback.add_argument('--json', action='store_true')

    validate.set_defaults(func=cmd_validate)
    show.set_defaults(func=cmd_show)
    publish.set_defaults(func=cmd_publish)
    lst.set_defaults(func=cmd_list)
    history.set_defaults(func=cmd_history)
    rollback.set_defaults(func=cmd_rollback)


__all__ = [
    'cmd_history',
    'cmd_list',
    'cmd_publish',
    'cmd_rollback',
    'cmd_show',
    'cmd_validate',
    'register',
]
