# harness/cli/finetunecmd.py
# `aicf finetune` -- the second half of the learn loop (W7).
#
# `aicf learn` produces the SFT dataset; until this command existed the chain
# ended there: FinetuneManager.submit had no CLI caller, PromotionManager had
# zero production callers, and the active slot had no reader at all. This
# command face wires submit / status / promote / rollback / active.
#
# Promotion evidence comes in two shapes: the classic score+samples (the
# learning.evaluator path, no framework producer) and --gate-report, a
# verdict=pass four-gate report from `aicf gate` (the path that actually
# exists in the CLI). The policy flag accept_gate_report gates the second.

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .common import eprint, out_json


def _manager(args: Any):
    from aicf.infra.finetune.runner import FinetuneManager

    return FinetuneManager(store=_store(args), root=getattr(args, 'root', '') or None)


def _store(args: Any):
    from aicf.infra.finetune.store import FinetuneStore

    db = getattr(args, 'db', '') or 'finetune.db'
    return FinetuneStore(db)


def cmd_submit(args: Any) -> int:
    from aicf.infra.finetune.base import TrainSpec

    spec = TrainSpec(
        base_model=args.base_model,
        dataset_path=args.dataset,
        output_dir=args.output,
    )
    try:
        job = _manager(args).submit(spec)
    except Exception as error:  # noqa: BLE001 -- submit rejects loudly on purpose
        eprint(f'Error: {error}')
        return 2
    payload = {'job_id': job.id, 'state': job.state.value,
               'base_model': spec.base_model, 'dataset': spec.dataset_path}
    if args.json:
        out_json(payload)
    else:
        eprint(f'queued {job.id} ({spec.base_model}); '
               f'check with: aicf finetune status {job.id}')
    return 0


def cmd_status(args: Any) -> int:
    manager = _manager(args)
    if args.job_id:
        job = manager.status(args.job_id)
        if job is None:
            eprint(f'Error: 作业不存在: {args.job_id}')
            return 2
        rows = [job]
    else:
        rows = manager.list_jobs()
    payload = [{'job_id': j.id, 'state': j.state.value,
                'adapter': j.adapter_path, 'error': j.error} for j in rows]
    if args.json:
        out_json(payload)
    else:
        for row in payload:
            eprint(f"{row['job_id']}  {row['state']}  {row['adapter'] or '-'}")
        if not payload:
            eprint('(no jobs)')
    return 0


def _load_gate_report(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if 'passed' not in data:
        raise ValueError(f'{path} 不是 Gate 报告（缺 passed 字段）')
    return data


def cmd_promote(args: Any) -> int:
    from aicf.harness.learning.promotion import PromotionManager, PromotionPolicy

    policy = PromotionPolicy(accept_gate_report=bool(args.gate_report))
    manager = PromotionManager(_store(args), policy=policy)
    gate_report = _load_gate_report(args.gate_report) if args.gate_report else None
    try:
        result = manager.promote(args.job, args.slot, score=args.score,
                                 samples=args.samples,
                                 gate_report=gate_report)
    except ValueError as error:
        eprint(f'Error: {error}')
        return 2
    if args.json:
        out_json(result)
    else:
        eprint(f"promoted {args.job} -> slot {args.slot} "
               f"(active={result.get('job_id')})")
    return 0


def cmd_rollback(args: Any) -> int:
    from aicf.harness.learning.promotion import PromotionManager

    result = PromotionManager(_store(args)).rollback(args.slot)
    if args.json:
        out_json(result)
    else:
        eprint(f"slot {args.slot} -> {result.get('job_id') or '(empty)'} "
               f"(rolled_back={result.get('rolled_back')})")
    return 0 if result.get('rolled_back') else 1


def cmd_active(args: Any) -> int:
    from aicf.harness.learning.promotion import PromotionManager

    job = PromotionManager(_store(args)).active(args.slot)
    payload = {'slot': args.slot, 'job_id': job.id if job else None}
    if args.json:
        out_json(payload)
    else:
        eprint(f"slot {args.slot}: {payload['job_id'] or '(nothing active)'}")
    return 0


def register(sub: Any) -> None:
    finetune = sub.add_parser('finetune', help='训练作业与晋级（learn 闭环后半，W7）')
    ft = finetune.add_subparsers(dest='finetune_command')

    submit = ft.add_parser('submit', help='提交一次训练（learn 的 SFT 数据集 → 适配器）')
    submit.add_argument('--base-model', required=True)
    submit.add_argument('--dataset', required=True, help='train.jsonl 路径')
    submit.add_argument('--output', default='', help='输出目录')
    submit.add_argument('--db', default='finetune.db')
    submit.add_argument('--root', default='')
    submit.add_argument('--json', action='store_true')
    submit.set_defaults(func=cmd_submit)

    status = ft.add_parser('status', help='作业状态')
    status.add_argument('job_id', nargs='?', default='')
    status.add_argument('--db', default='finetune.db')
    status.add_argument('--root', default='')
    status.add_argument('--json', action='store_true')
    status.set_defaults(func=cmd_status)

    promote = ft.add_parser('promote', help='把适配器晋级到槽位')
    promote.add_argument('--job', required=True)
    promote.add_argument('--slot', required=True)
    promote.add_argument('--score', type=float, default=None)
    promote.add_argument('--samples', type=int, default=None)
    promote.add_argument('--gate-report', default='',
                         help='verdict=pass 的 Gate 报告（W7 晋级通道）')
    promote.add_argument('--db', default='finetune.db')
    promote.add_argument('--json', action='store_true')
    promote.set_defaults(func=cmd_promote)

    rollback = ft.add_parser('rollback', help='回滚槽位')
    rollback.add_argument('--slot', required=True)
    rollback.add_argument('--db', default='finetune.db')
    rollback.add_argument('--json', action='store_true')
    rollback.set_defaults(func=cmd_rollback)

    active = ft.add_parser('active', help='查看槽位当前生效的适配器')
    active.add_argument('--slot', required=True)
    active.add_argument('--db', default='finetune.db')
    active.add_argument('--json', action='store_true')
    active.set_defaults(func=cmd_active)


__all__ = ['register']
