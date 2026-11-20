# harness/cli/evalcmd.py
# `aicf eval` 与 `aicf gate` —— 评测闭环的命令面。
#
# eval:  拿一份 dataset + 一批 trace → 逐 case 打分 → 产出 run 结果
# gate:  拿 run 结果（可选 baseline）→ 四闸门报告
#
# 报告落成 JSON，是为了能被控制面在 APPROVED → RELEASED 迁移时强制校验
# （策划案 §4.5.2：发布必须携带通过的 Gate 报告）。

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from aicf.infra.eval import (
    Evaluator,
    GateEvaluator,
    Trace,
    capture_run_version,
    load_dataset,
)
from aicf.infra.eval.trace_store import usage_from_events

from .common import eprint, out_json, read_json, write_json


def resolve_dataset(source: str) -> str:
    """解析数据集路径。

    依次尝试：
      1. 原样（相对当前目录或绝对路径）
      2. 包内数据 ``harness/datasets/<名字>``（pip 装完就有）
      3. ``./datasets/<名字>``（源码树里跑时）
    """
    candidate = Path(source)
    if candidate.exists():
        return str(candidate)
    # 允许省略扩展名：`--dataset basic` → basic.yaml
    names = [candidate.name]
    if not candidate.suffix:
        names.append(candidate.name + '.yaml')
    for base in (Path(__file__).resolve().parent.parent / 'datasets',
                 Path.cwd() / 'datasets'):
        for name in names:
            probe = base / name
            if probe.exists():
                return str(probe)
    return source


def _load_traces(source: str) -> list[Trace]:
    """从一个 JSONL 文件或一个目录里读 trace。"""
    path = Path(source)
    traces: list[Trace] = []
    files: list[Path]
    if path.is_dir():
        files = sorted(path.glob('*.jsonl'))
    elif path.exists():
        files = [path]
    else:
        raise FileNotFoundError(f'找不到 trace: {source}')
    for file in files:
        for line in file.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            traces.append(_to_trace(payload))
    return traces


def _to_trace(payload: dict) -> Trace:
    # older traces carry usage only inside the event stream -- fall back to
    # it so eval sees the same numbers run wrote (W0)
    usage = dict(payload.get('usage') or {})
    if not usage:
        usage = usage_from_events(payload.get('events') or [])
    return Trace(
        trace_id=str(payload.get('trace_id', '')),
        session_id=str(payload.get('session_id', '')),
        run_version_id=str(payload.get('run_version_id', '')),
        case_id=str(payload.get('case_id', '')),
        input=str(payload.get('input', '')),
        output=str(payload.get('output', '')),
        tool_calls=list(payload.get('tool_calls') or []),
        messages=list(payload.get('messages') or []),
        usage=usage,
        cost=float(payload.get('cost', 0.0) or 0.0),
        latency_ms=float(payload.get('latency_ms', 0.0) or 0.0),
        error=str(payload.get('error', '')),
        events=list(payload.get('events') or []),
    )


def _dataset_from_badcases(db_path: str):
    """Labelled badcases -> a hard_cases regression dataset (W5.3).

    Only rows with repro data (input_text) become cases; the rest are still
    waiting for someone to label the repro.
    """
    from aicf.infra.eval.badcase import STATUS_LABELLED, BadCaseIntake, LabelledBadCase
    from aicf.infra.eval.dataset import EvalDataset
    from aicf.infra.eval.trace_store import TraceStore

    store = TraceStore(db_path)
    intake = BadCaseIntake(store)
    records = []
    for row in store.list_badcases(status=STATUS_LABELLED):
        if not str(row.get('input_text') or '').strip():
            continue
        records.append(LabelledBadCase(
            id=str(row['id']), session_id=str(row.get('session_id') or ''),
            trace_id=str(row.get('trace_id') or ''),
            reason=str(row.get('reason') or ''),
            label=str(row.get('label') or ''), status=STATUS_LABELLED,
            input_text=str(row.get('input_text') or ''),
            expect=list(row.get('expect') or ()),
            critical=bool(row.get('critical', True))))
    if not records:
        raise ValueError(f'{db_path} 里没有可回流的已标注坏样本')
    return EvalDataset(id='badcases', version='1', path=db_path,
                       cases=intake.to_dataset(records),
                       description=f'hard cases from {db_path} ({len(records)} labelled)')


def cmd_eval(args: Any) -> int:
    if not getattr(args, 'dataset', '') and not getattr(args, 'from_badcases', ''):
        eprint('Error: 需要 --dataset <名字|路径>（或 --from-badcases <db>）')
        return 2
    try:
        dataset = (_dataset_from_badcases(args.from_badcases)
                   if getattr(args, 'from_badcases', '')
                   else load_dataset(resolve_dataset(args.dataset)))
    except Exception as error:  # noqa: BLE001
        eprint(f'数据集加载失败: {error}')
        return 2

    # --group 过滤：只评选中的组。数据集对象是冻结口径（hash 进 run version），
    # 所以过滤发生在「装载之后、打分之前」，且过滤后的用例名单随 run 一起落盘
    # —— 评审的人能看出这份 run 评的是全集还是子集。
    selected_groups = _parse_groups(getattr(args, 'group', None))
    if selected_groups:
        dataset = dataset.filtered(selected_groups)
        if not dataset.cases:
            known = ', '.join(sorted(load_dataset(resolve_dataset(args.dataset)).groups()))
            eprint(f'分组 {sorted(selected_groups)} 在数据集里没有用例'
                   f'（可用: {known}）')
            return 2

    traces: list[Trace] = []
    if args.traces:
        try:
            traces = _load_traces(args.traces)
        except Exception as error:  # noqa: BLE001
            eprint(f'trace 读取失败: {error}')
            return 2

    evaluator = Evaluator()
    run_id = args.run_id or uuid.uuid4().hex[:12]
    version = capture_run_version(dataset=dataset, artifact_path=args.artifact or '',
                                 model=args.model or '', commit=args.commit or '')
    # evaluate_run 负责 case→trace 的匹配与聚合统计。
    # 只带 trace 的 case 会得满分，其它 case 记 missing_trace ——
    # 「没跑」和「跑失败」是两件事，不能混。
    result = evaluator.evaluate_run(dataset, traces, run_id=run_id,
                                     run_version_id=version.id)
    results = result.results
    run = {
        'run_id': run_id,
        'run_version_id': version.id,
        'dataset_id': dataset.id,
        'dataset_hash': dataset.hash,
        'status': result.status,
        'started_at': result.started_at or time.time(),
        'ended_at': result.ended_at or time.time(),
        'results': [r.to_dict() for r in results],
        'aggregate': dict(result.aggregate or _aggregate(results)),
    }
    if args.out:
        path = write_json(args.out, run)
        print(f'run → {path}')
    if args.json:
        out_json(run)
    else:
        passed = sum(1 for r in results if r.passed)
        print(f'用例 {passed}/{len(results)} 通过'
              f'（数据集 {dataset.id}，hash {dataset.hash[:12]}）')
        for result in results:
            if not result.passed:
                print(f'  FAIL {result.case_id}: '
                      f'{", ".join(result.failed_rules) or "断言未通过"}')
    return 0 if run['status'] == 'passed' else 1


def _aggregate(results: list) -> dict:
    total = len(results) or 1
    passed = sum(1 for r in results if r.passed)
    return {
        'cases': float(len(results)),
        'passed': float(passed),
        'pass_rate': passed / total,
        'score': sum(r.score for r in results) / total,
    }


def _parse_groups(groups: list[str] | None) -> set[str]:
    """--group 可以重复、也可以逗号分隔（--group refusal,safety）。"""
    selected: set[str] = set()
    for item in groups or []:
        selected.update(part.strip() for part in str(item).split(',') if part.strip())
    return selected


def cmd_gate(args: Any) -> int:
    try:
        run = _load_run(args.run)
        baseline = _load_run(args.baseline) if args.baseline else None
    except Exception as error:  # noqa: BLE001
        eprint(f'运行结果读取失败: {error}')
        return 2

    thresholds = None
    if getattr(args, 'cost_budget', None) is not None:
        from aicf.infra.eval.gate import GateThresholds
        thresholds = GateThresholds(cost_budget_per_session=args.cost_budget)
    evaluator = GateEvaluator(thresholds=thresholds)
    report = evaluator.evaluate(_to_run_result(run), _to_run_result(baseline)
                                if baseline else None)
    payload = report.to_dict()
    if not report.passed:
        # gate FAIL feeds the badcase intake (W5.3): the loop the roadmap
        # promised -- failures come back as labelled regression cases
        try:
            from aicf.infra.eval.badcase import BadCaseIntake
            from aicf.infra.eval.trace_store import TraceStore

            intake = BadCaseIntake(TraceStore(_gate_db_path(args)))
            for item in run.get('results') or []:
                if item.get('passed'):
                    continue
                rules = ','.join(item.get('failed_rules') or []) or 'failed'
                intake.intake(session_id=str(run.get('run_id') or ''),
                              trace_id=str(item.get('trace_id') or ''),
                              source='gate',
                              reason=f"{item.get('case_id')}:{rules}")
        except Exception as error:  # noqa: BLE001
            eprint(f'（badcase 回流未落库：{error}）')
    if args.out:
        path = write_json(args.out, payload)
        print(f'gate 报告 → {path}')
    # 报告同时落 eval_gate_report 表（策划案 §4.5.2）：控制面的发布迁移
    # （aicf artifact publish --gate <id>）要能查到它并校验 verdict。
    # 存不进去不阻断 —— 报告文件仍然可用，只是发布时要给文件里的 id。
    if payload.get('id'):
        try:
            from aicf.infra.eval.trace_store import TraceStore
            TraceStore(_gate_db_path(args)).save_gate_report(payload)
        except Exception as error:  # noqa: BLE001
            eprint(f'（gate 报告未能落库：{error}）')
    if args.json:
        out_json(payload)
    else:
        print(f'闸门判定: {"通过" if report.passed else "未通过"}')
        for name in ('quality', 'regression', 'cost', 'safety'):
            outcome = report.gate(name)
            if outcome is None:
                continue
            mark = 'PASS' if outcome.passed else 'FAIL'
            summary = outcome.summary or ''
            if not outcome.passed and outcome.failures:
                first = outcome.failures[0]
                if isinstance(first, dict):
                    summary = summary or str(first.get('message', ''))
            print(f'  [{mark}] {name}: {summary}')
    return 0 if report.passed else 1


def _gate_db_path(args: Any) -> str:
    """gate 报告落库的位置：与运行时同库（eval/runtime 的表同文件起步）。"""
    db = getattr(args, 'db', '')
    if db:
        return db
    return os.environ.get('AICF_DB') or 'aicf.db'


def _load_run(source: str) -> dict:
    path = Path(source)
    if path.exists():
        return read_json(path)
    raise FileNotFoundError(f'找不到运行结果: {source}')


def _to_run_result(payload: dict):
    from aicf.infra.eval import CaseResult, RunResult
    results = []
    for item in payload.get('results') or []:
        results.append(CaseResult(
            case_id=item.get('case_id', ''),
            group=item.get('group', 'default'),
            critical=bool(item.get('critical')),
            passed=bool(item.get('passed')),
            score=float(item.get('score', 0.0) or 0.0),
            metrics=dict(item.get('metrics') or {}),
            failed_rules=list(item.get('failed_rules') or []),
        ))
    return RunResult(
        run_id=payload.get('run_id', ''),
        run_version_id=payload.get('run_version_id', ''),
        dataset_id=payload.get('dataset_id', ''),
        dataset_hash=payload.get('dataset_hash', ''),
        status=payload.get('status', 'passed'),
        started_at=float(payload.get('started_at', 0.0) or 0.0),
        ended_at=float(payload.get('ended_at', 0.0) or 0.0),
        results=results,
        aggregate=dict(payload.get('aggregate') or {}),
    )


__all__ = ['cmd_eval', 'cmd_gate']
