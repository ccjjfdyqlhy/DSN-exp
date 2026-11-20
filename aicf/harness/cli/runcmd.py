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
    """Kernel telemetry sink with a dual fan-out.

    The raw event list feeds the eval contract (tool_calls assertions, W0
    usage); the same stream also feeds the real span machine
    (infra TraceCollector, W1) so a run leaves an auditable span trail
    instead of only the trimmed eval payload.
    """

    def __init__(self, *, trace_id: str = '', run_id: str = '',
                 session_id: str = '') -> None:
        from aicf.infra.observability.trace import TraceCollector

        self.events: list[dict] = []
        self._spans = TraceCollector(trace_id=trace_id or None, run_id=run_id,
                                     session_id=session_id)

    def emit(self, kind, payload) -> None:
        self.events.append({'kind': kind, 'payload': dict(payload or {})})
        self._spans.emit(kind, payload)

    def spans(self) -> list[dict]:
        return self._spans.records()  # method on TraceCollector, not a property


def _setup_session(args: Any, *, session_id: str, collector: _Collector):
    """装配一次 run 需要的全部组件（单输入与数据集两条路径共用）。

    返回 (registry, kernel_cls, runtime, store, ports)。守卫/策略/审批/审计
    都在这里挂好 —— CLI 不给任何绕过链路的旁路。ports 是 W4 的三个内核
    端口（memory/approval/context），此前在所有装配路径上恒为 None。
    """
    from aicf.harness.approval.broker import LocalApprovalBroker
    from aicf.harness.approval.base import ApprovalDecision
    from aicf.harness.context_assembly import SegmentedContextAssembler
    from aicf.harness.memory.session_port import SessionMemoryStore
    from aicf.harness.tools.guard import ToolGuard
    from aicf.harness.policy.base import PolicyRule
    from aicf.infra.observability.audit import AuditLog
    from aicf.infra.policy.engine import RulePolicyEngine
    from aicf.infra.store.chat_store import SessionStore

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
    identity = None
    if getattr(args, 'identity', ''):
        from aicf.infra.control.identity import AgentIdentity
        identity = AgentIdentity(agent_id=args.identity, delegated_by='user')
    guard = ToolGuard(policy=engine, approval=approval, telemetry=collector,
                      runtime=runtime, audit=audit_log, identity=identity,
                      session_id=session_id)
    registry.attach_guard(guard)
    # kernel ports (W4): the same db hosts the session tables, so the memory
    # port rides on it; the context port is the budgeted segment assembler
    session_store = SessionStore(store)
    ports = {
        'memory': SessionMemoryStore(session_store=session_store),
        'approval': approval,
        'context': SegmentedContextAssembler(),
    }
    return registry, _resolve_kernel(args), runtime, store, ports


def _run_one_turn(kernel_cls, registry, model, *, session_id: str, turn_id: str,
                  text: str, collector: _Collector, runtime, max_steps: int,
                  ports: dict | None = None):
    """跑一轮（一个 case 或一次单输入），返回 (result, duration_ms)。"""
    from aicf.infra.orchestrator.base import ChatMessage

    kernel = kernel_cls(client=model, tools=registry, max_steps=max_steps) \
        if kernel_cls is ReactKernel else kernel_cls()
    ports = ports or {}
    ctx = KernelContext(
        session_id=session_id,
        turn_id=turn_id,
        input=[ChatMessage.user(text)],
        tools=registry,
        model=model,
        telemetry=collector,
        runtime=runtime,
        memory=ports.get('memory'),
        approval=ports.get('approval'),
        context=ports.get('context'),
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
    # redact only the free-form payloads inside events: the eval contract
    # fields (usage tokens, cost) must survive verbatim, and a blanket
    # redact_dict would mask numeric accounting values as '***' (W1)
    from aicf.infra.observability.redact import redact_dict
    from aicf.harness.telemetry.exporter import TraceExporter

    payload = dict(trace)
    payload['events'] = [
        dict(event, payload={k: (redact_dict(v) if isinstance(v, dict) else v)
                             for k, v in (event.get('payload') or {}).items()})
        for event in trace.get('events') or []
    ]
    with TraceExporter(path, append=True, redact_values=False) as exporter:
        exporter.write(payload)


def _write_spans(collector: _Collector, path: Path, *, start: int = 0) -> None:
    """Sidecar span trail for one run/case (<trace>.spans.jsonl).

    Spans carry free-form tool args, so they get the blanket redact.
    """
    from aicf.harness.telemetry.exporter import TraceExporter

    spans = collector.spans()[start:]
    if not spans:
        return
    with TraceExporter(path.with_suffix('.spans.jsonl')) as exporter:
        exporter.export(spans)


def _record_cost(args: Any, session_id: str, tokens: int, cost: float) -> None:
    """Best-effort cost attribution (W5.2): the ledger never breaks a run."""
    try:
        from aicf.infra.control.store import ArtifactStore
        from aicf.infra.eval.trace_store import TraceStore

        store = ArtifactStore(TraceStore(args.db))
        store.cost.record(session_id=session_id,
                          agent_id=getattr(args, 'identity', '') or '',
                          model=args.model or 'stub',
                          tokens=int(tokens), cost=float(cost))
    except Exception as error:  # noqa: BLE001
        eprint(f'[aicf] cost ledger write skipped: {error}')


def cmd_run(args: Any) -> int:
    _apply_artifact(args)
    if getattr(args, 'dataset', ''):
        return _run_dataset(args)

    run_id = args.run_id or uuid.uuid4().hex[:12]
    session_id = args.session_id or run_id
    collector = _Collector(trace_id=run_id, run_id=run_id, session_id=session_id)
    registry, kernel_cls, runtime, store, ports = _setup_session(
        args, session_id=session_id, collector=collector)
    model = build_model(model=args.model, base_url=args.base_url,
                        api_key=args.api_key)

    try:
        result, duration_ms = _run_one_turn(
            kernel_cls, registry, model,
            session_id=session_id, turn_id=run_id, text=args.input,
            collector=collector, runtime=runtime, max_steps=args.max_steps,
            ports=ports)
    finally:
        store.close()

    trace = _trace_payload(
        collector, trace_id=run_id, session_id=session_id,
        case_id=args.case_id or '', text=args.input, output=result.text,
        latency_ms=duration_ms, pricing_name=_pricing_tier(args))
    trace_path = Path(args.trace) if args.trace else None
    if trace_path is not None:
        _write_trace(trace, trace_path)
        _write_spans(collector, trace_path)
        print(f'trace → {trace_path}')
    _record_cost(args, session_id,
                 tokens=(trace.get('usage') or {}).get('total_tokens', 0),
                 cost=trace.get('cost', 0.0))
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
    collector = _Collector(trace_id=run_id, run_id=run_id, session_id=session_id)
    registry, kernel_cls, runtime, store, ports = _setup_session(args, session_id=session_id,
                                                                 collector=collector)
    model = build_model(model=args.model, base_url=args.base_url,
                        api_key=args.api_key)

    rows: list[dict] = []
    total_tokens, total_cost = 0, 0.0
    try:
        for case in cases:
            collector.events.clear()
            span_start = len(collector.spans())
            case_trace_dir = trace_dir / case.id
            trace_path = case_trace_dir.with_suffix('.jsonl')
            try:
                result, duration_ms = _run_one_turn(
                    kernel_cls, registry, model,
                    session_id=session_id, turn_id=f'{run_id}-{case.id}',
                    text=case.input, collector=collector, runtime=runtime,
                    max_steps=args.max_steps, ports=ports)
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
            _write_spans(collector, trace_path, start=span_start)
            total_tokens += int((trace.get('usage') or {}).get('total_tokens', 0))
            total_cost += float(trace.get('cost', 0.0))
            rows.append({'case_id': case.id, 'group': case.group,
                         'status': status, 'trace': str(trace_path)})
            if not args.json:
                mark = '✓' if status == 'done' else '✗'
                eprint(f'{mark} {case.id} [{case.group}] {status}')
    finally:
        store.close()

    _record_cost(args, session_id, tokens=total_tokens, cost=total_cost)
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
