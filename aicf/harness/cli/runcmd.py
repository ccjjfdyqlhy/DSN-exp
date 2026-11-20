# harness/cli/runcmd.py
# `aicf run` —— 跑一次 agent，落一份 trace。
#
# 这条命令是整条链路的入口：run → eval → gate。
# 每次 run 产出一个 trace.jsonl（策划案 §5.4），评测消费的就是它。
#
# `--artifact agents/xxx.yaml`（策划案 §5.4 `aicf run <artifact.yaml>`）：
# kernel / 工具 / 模型按声明装配 —— 「一种声明，多处消费」（§4.5.1），
# 命令行跑的配置与评测、发布看到的是同一份。
#
# `--dataset offline`（roadmap 段 3）：把数据集从头到尾跑一遍 ——
# 每个用例一轮、一条 trace，落 `--trace-dir`。这样「陌生人照 README
# 走完」的终点可以是 `aicf eval` + `aicf gate` 全绿（离线数据集
# 用桩模型就能过），而不是一句红色的「闸门未通过」。

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from aicf.harness.kernel import KernelContext, ReactKernel
from aicf.harness.kernel.capability import CapabilitySet

from .common import (
    attach_project_tools,
    build_model,
    build_registry,
    build_runtime,
    eprint,
    out_json,
)


def _apply_artifact(args: Any) -> None:
    """按 artifact 声明改写 run 参数（命令行显式给的值优先）。"""
    if not getattr(args, 'artifact', ''):
        return
    from aicf.infra.control.artifact import ArtifactError, load_artifact, parse_tool_ref

    try:
        artifact = load_artifact(args.artifact)
    except ArtifactError as error:
        raise SystemExit(f'Error: {error}')
    # 执行架构（策划案 §4.1.3）：换架构只改 spec.kernel；
    # 命令行显式 --kernel 优先于声明（显式覆盖是调试的合法需求）
    if not getattr(args, 'kernel', ''):
        args.kernel = artifact.spec_kernel
    # 工具：版本引用 → include 名单（引用了不存在的工具会在
    # build_registry 的 include 过滤里表现为「工具表变短」，
    # 守卫按最严格档拦住误用 —— 这正是版本引用的意义）
    if not args.include:
        args.include = [parse_tool_ref(ref)[0] for ref in artifact.spec_tools]
    # 模型：primary；命令行显式给了 model 就以命令行为准
    if not args.model and artifact.spec_model.primary:
        args.model = artifact.spec_model.primary
    args.artifact_loaded = artifact


def _resolve_kernel(args: Any):
    """按 --kernel / artifact 声明解析执行架构；未知 → SystemExit。"""
    from aicf.harness.kernel import kernel_by_name

    kernel_name = str(getattr(args, 'kernel', '') or 'react').lower()
    kernel_cls = kernel_by_name(kernel_name)
    if kernel_cls is None:
        eprint(f'Error: 未知执行架构 {kernel_name!r}（可选: react/workflow/planner）')
        raise SystemExit(2)
    return kernel_cls


class _Collector:
    """把事件流收进内存 —— trace 的 tool_calls 断言消费的就是它。"""

    def __init__(self) -> None:
        self.events: list[dict] = []

    def emit(self, kind, payload) -> None:
        self.events.append({'kind': kind, 'payload': dict(payload or {})})


def _setup_session(args: Any, *, session_id: str, collector: _Collector):
    """装配一次 run 需要的全部组件（单输入与数据集两条路径共用）。

    返回 (registry, kernel_cls, runtime, store)。守卫/策略/审批/审计
    都在这里挂好 —— CLI 不给任何绕过链路的旁路。
    """
    from aicf.harness.approval.broker import LocalApprovalBroker
    from aicf.harness.approval.base import ApprovalDecision
    from aicf.harness.tools.guard import ToolGuard
    from aicf.harness.policy.base import PolicyRule
    from aicf.infra.observability.audit import AuditLog
    from aicf.infra.policy.engine import RulePolicyEngine

    registry = build_registry(include=args.include or None)
    # `aicf init` 骨架的约定：当前目录的 tools/ 也算工具表的一部分，
    # 否则「aicf tool list 看得见自己的工具、aicf run 却看不见」就自相矛盾了。
    found_local = attach_project_tools(registry)
    if found_local:
        eprint(f'[aicf] 已从 ./tools/ 装载 {found_local} 个项目本地工具')

    engine = RulePolicyEngine(rules=[
        PolicyRule(action='deny', tool=name, id=f'deny-{name}')
        for name in (args.deny_tool or [])
    ])
    approval = LocalApprovalBroker(
        resolver=(lambda req: ApprovalDecision.approve(by='cli', reason='--yes')
                  if args.yes else
                  ApprovalDecision.deny(by='cli', reason='CLI 未开启 --yes')))
    runtime, store = build_runtime(args.db, session_id)
    # 不可删审计（策划案 §4.4.7）：run 路径的 audit.* 事件落独立存储。
    audit_log = AuditLog()
    guard = ToolGuard(policy=engine, approval=approval, telemetry=collector,
                      runtime=runtime, audit=audit_log,
                      session_id=session_id)
    registry.attach_guard(guard)
    return registry, _resolve_kernel(args), runtime, store


def _run_one_turn(kernel_cls, registry, model, *, session_id: str, turn_id: str,
                  text: str, collector: _Collector, runtime, max_steps: int):
    """跑一轮（一个 case 或一次单输入），返回 (result, duration_ms)。"""
    from aicf.infra.orchestrator.base import ChatMessage

    kernel = kernel_cls(client=model, tools=registry, max_steps=max_steps) \
        if kernel_cls is ReactKernel else kernel_cls()
    ctx = KernelContext(
        session_id=session_id,
        turn_id=turn_id,
        input=[ChatMessage.user(text)],
        tools=registry,
        model=model,
        telemetry=collector,
        runtime=runtime,
        caps=CapabilitySet(),
        max_steps=max_steps,
    )
    started = time.time()
    try:
        runtime.start_turn(turn_id=turn_id, input={'text': text})
        result = asyncio.run(kernel.run(ctx))
        runtime.finish_turn(status=('succeeded' if result.status == 'done'
                                     else 'failed'),
                             stop_reason=result.stop_reason)
    finally:
        duration_ms = (time.time() - started) * 1000
    return result, duration_ms


def _pricing_tier(args: Any) -> str:
    """Stub runs are free (local tier); a real endpoint bills at the flash table."""
    key = args.api_key or os.environ.get('OPENAI_API_KEY', '')
    return 'flash' if (getattr(args, 'base_url', '') or key) else 'local'


def _trace_payload(collector: _Collector, *, trace_id: str, session_id: str,
                   case_id: str, text: str, output: str,
                   latency_ms: float, pricing_name: str = 'local') -> dict:
    # usage/cost come from the kernel's `usage` events (W0): the data was
    # already in the collector -- dropping it made the cost gate judge 0
    from aicf.infra.eval.trace_store import cost_from_events, usage_from_events

    return {
        'trace_id': trace_id,
        'session_id': session_id,
        'case_id': case_id,
        'input': text,
        'output': output,
        'tool_calls': _tool_calls(collector.events),
        'usage': usage_from_events(collector.events),
        'cost': cost_from_events(collector.events, pricing_name=pricing_name),
        'latency_ms': latency_ms,
        'events': collector.events,
    }


def _write_trace(trace: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(trace, ensure_ascii=False, default=str))
        handle.write('\n')


def cmd_run(args: Any) -> int:
    _apply_artifact(args)
    if getattr(args, 'dataset', ''):
        return _run_dataset(args)

    run_id = args.run_id or uuid.uuid4().hex[:12]
    session_id = args.session_id or run_id
    collector = _Collector()
    registry, kernel_cls, runtime, store = _setup_session(
        args, session_id=session_id, collector=collector)
    model = build_model(model=args.model, base_url=args.base_url,
                        api_key=args.api_key)

    try:
        result, duration_ms = _run_one_turn(
            kernel_cls, registry, model,
            session_id=session_id, turn_id=run_id, text=args.input,
            collector=collector, runtime=runtime, max_steps=args.max_steps)
    finally:
        store.close()

    trace = _trace_payload(
        collector, trace_id=run_id, session_id=session_id,
        case_id=args.case_id or '', text=args.input, output=result.text,
        latency_ms=duration_ms, pricing_name=_pricing_tier(args))
    trace_path = Path(args.trace) if args.trace else None
    if trace_path is not None:
        _write_trace(trace, trace_path)
        print(f'trace → {trace_path}')
    if args.json:
        out_json(trace)
    else:
        print(result.text)
    return 0 if result.status == 'done' else 1


def _run_dataset(args: Any) -> int:
    """把数据集跑一遍：每个用例一轮、一条 trace（--trace-dir/<case_id>.jsonl）。

    评测断言消费的是 trace；这里只负责「把运行的事实留下来」，
    打分是 `aicf eval` 的事 —— run 和 eval 之间的边界不许糊。
    """
    from aicf.infra.eval.dataset import load_dataset

    dataset = load_dataset(_resolve_dataset_path(args.dataset))
    cases = dataset.cases
    trace_dir = Path(args.trace_dir or 'traces')
    workspace = Path(args.workspace or '.aicf-workspace')

    # 数据集自带的 setup.files 写进工作区 —— 与真模型路径共享同一份语义：
    # 用例说「要有 a.txt」，运行时就有 a.txt（写到当前目录是不可接受的）。
    if any(case.setup for case in cases):
        workspace.mkdir(parents=True, exist_ok=True)
        for case in cases:
            for rel, content in (case.setup or {}).get('files', {}).items():
                target = workspace / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(str(content), encoding='utf-8')

    run_id = args.run_id or uuid.uuid4().hex[:12]
    session_id = args.session_id or f'{run_id}-dataset'
    collector = _Collector()
    registry, kernel_cls, runtime, store = _setup_session(args, session_id=session_id,
                                                          collector=collector)
    model = build_model(model=args.model, base_url=args.base_url,
                        api_key=args.api_key)

    rows: list[dict] = []
    try:
        for case in cases:
            collector.events.clear()
            case_trace_dir = trace_dir / case.id
            trace_path = case_trace_dir.with_suffix('.jsonl')
            try:
                result, duration_ms = _run_one_turn(
                    kernel_cls, registry, model,
                    session_id=session_id, turn_id=f'{run_id}-{case.id}',
                    text=case.input, collector=collector, runtime=runtime,
                    max_steps=args.max_steps)
                status = 'done' if result.status == 'done' else result.status
                output = result.text
                error = ''
            except Exception as error:  # noqa: BLE001 —— 一个 case 挂了别的还要跑
                status = 'error'
                output = ''
                duration_ms = 0.0
                error = str(error)
            trace = _trace_payload(
                collector, trace_id=f'{run_id}-{case.id}',
                session_id=session_id, case_id=case.id, text=case.input,
                output=output, latency_ms=duration_ms,
                pricing_name=_pricing_tier(args))
            if error:
                trace['error'] = error
            _write_trace(trace, trace_path)
            rows.append({'case_id': case.id, 'group': case.group,
                         'status': status, 'trace': str(trace_path)})
            if not args.json:
                mark = '✓' if status == 'done' else '✗'
                eprint(f'{mark} {case.id} [{case.group}] {status}')
    finally:
        store.close()

    if args.json:
        out_json({'dataset': dataset.id, 'cases': rows})
    else:
        print(f"数据集 {dataset.id} 跑完：{len(rows)} case，"
              f"trace 落 {trace_dir}/，下一步: aicf eval --dataset {dataset.id} "
              f"--traces {trace_dir}/ --out run.json")
    return 0


def _resolve_dataset_path(name_or_path: str) -> str:
    """数据集参数 → 路径（与 evalcmd.resolve_dataset 同一解析顺序）。"""
    from .evalcmd import resolve_dataset

    return str(resolve_dataset(name_or_path))


def _tool_calls(events: list[dict]) -> list[dict]:
    """从事件流里抽出工具调用（评测断言消费的就是这个形状）。"""
    calls: list[dict] = []
    for event in events:
        kind = event.get('kind')
        payload = event.get('payload') or {}
        if kind == 'tool_intent':
            calls.append({
                'name': payload.get('tool', ''),
                'args': {},
                'effect': payload.get('effect', 'unknown'),
                'denied': False,
            })
        elif kind == 'tool_blocked':
            calls.append({
                'name': payload.get('tool', ''),
                'args': {},
                'effect': payload.get('effect', 'unknown'),
                'denied': True,
            })
    return calls


__all__ = ['cmd_run']
