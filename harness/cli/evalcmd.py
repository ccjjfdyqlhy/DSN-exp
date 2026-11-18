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
import time
import uuid
from pathlib import Path
from typing import Any

from infra.eval import (
    Evaluator,
    GateEvaluator,
    Trace,
    capture_run_version,
    load_dataset,
)

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
    return Trace(
        trace_id=str(payload.get('trace_id', '')),
        session_id=str(payload.get('session_id', '')),
        run_version_id=str(payload.get('run_version_id', '')),
        case_id=str(payload.get('case_id', '')),
        input=str(payload.get('input', '')),
        output=str(payload.get('output', '')),
        tool_calls=list(payload.get('tool_calls') or []),
        messages=list(payload.get('messages') or []),
        usage=dict(payload.get('usage') or {}),
        cost=float(payload.get('cost', 0.0) or 0.0),
        latency_ms=float(payload.get('latency_ms', 0.0) or 0.0),
        error=str(payload.get('error', '')),
        events=list(payload.get('events') or []),
    )


def cmd_eval(args: Any) -> int:
    try:
        dataset = load_dataset(resolve_dataset(args.dataset))
    except Exception as error:  # noqa: BLE001
        eprint(f'数据集加载失败: {error}')
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


def cmd_gate(args: Any) -> int:
    try:
        run = _load_run(args.run)
        baseline = _load_run(args.baseline) if args.baseline else None
    except Exception as error:  # noqa: BLE001
        eprint(f'运行结果读取失败: {error}')
        return 2

    evaluator = GateEvaluator()
    report = evaluator.evaluate(_to_run_result(run), _to_run_result(baseline)
                                if baseline else None)
    payload = report.to_dict()
    if args.out:
        path = write_json(args.out, payload)
        print(f'gate 报告 → {path}')
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


def _load_run(source: str) -> dict:
    path = Path(source)
    if path.exists():
        return read_json(path)
    raise FileNotFoundError(f'找不到运行结果: {source}')


def _to_run_result(payload: dict):
    from infra.eval import CaseResult, RunResult
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
