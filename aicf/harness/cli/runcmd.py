# harness/cli/runcmd.py
# `aicf run` —— 跑一次 agent，落一份 trace。
#
# 这条命令是整条链路的入口：run → eval → gate。
# 每次 run 产出一个 trace.jsonl（策划案 §5.4），评测消费的就是它。
#
# `--artifact agents/xxx.yaml`（策划案 §5.4 `aicf run <artifact.yaml>`）：
# kernel / 工具 / 模型按声明装配 —— 「一种声明，多处消费」（§4.5.1），
# 命令行跑的配置与评测、发布看到的是同一份。

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any

from aicf.harness.kernel import KernelContext, ReactKernel
from aicf.harness.kernel.capability import CapabilitySet

from .common import build_model, build_registry, build_runtime, eprint, out_json


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


def cmd_run(args: Any) -> int:
    _apply_artifact(args)
    registry = build_registry(include=args.include or None)
    model = build_model(model=args.model, base_url=args.base_url,
                        api_key=args.api_key)

    trace_path = Path(args.trace) if args.trace else None
    trace_events: list[dict] = []

    class Collector:
        def emit(self, kind, payload):
            trace_events.append({'kind': kind, 'payload': dict(payload or {})})

    collector = Collector()
    run_id = args.run_id or uuid.uuid4().hex[:12]
    session_id = args.session_id or run_id

    # 工具执行也要落进 trace —— 评测的 tool_called / forbid_tools 断言
    # 依赖的就是这条事件流。
    from aicf.harness.tools.guard import ToolGuard
    from aicf.harness.policy.base import PolicyRule
    from aicf.harness.approval.broker import LocalApprovalBroker
    from aicf.harness.approval.base import ApprovalDecision
    from aicf.infra.policy.engine import RulePolicyEngine

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
    from aicf.infra.observability.audit import AuditLog
    audit_log = AuditLog()
    guard = ToolGuard(policy=engine, approval=approval, telemetry=collector,
                      runtime=runtime, audit=audit_log,
                      session_id=session_id, turn_id=run_id)
    registry.attach_guard(guard)

    from aicf.infra.orchestrator.base import ChatMessage
    from aicf.harness.kernel import kernel_by_name
    kernel_name = str(getattr(args, 'kernel', '') or 'react').lower()
    kernel_cls = kernel_by_name(kernel_name)
    if kernel_cls is None:
        eprint(f'Error: 未知执行架构 {kernel_name!r}（可选: react/workflow/planner）')
        return 2
    kernel = kernel_cls(client=model, tools=registry, max_steps=args.max_steps) \
        if kernel_cls is ReactKernel else kernel_cls()
    ctx = KernelContext(
        session_id=session_id,
        turn_id=run_id,
        input=[ChatMessage.user(args.input)],
        tools=registry,
        model=model,
        telemetry=collector,
        runtime=runtime,
        caps=CapabilitySet(),
        max_steps=args.max_steps,
    )
    started = time.time()
    try:
        runtime.start_turn(turn_id=run_id, input={'text': args.input})
        result = asyncio.run(kernel.run(ctx))
        runtime.finish_turn(status=('succeeded' if result.status == 'done'
                                     else 'failed'),
                             stop_reason=result.stop_reason)
    finally:
        duration_ms = (time.time() - started) * 1000
        store.close()

    trace = {
        'trace_id': run_id,
        'session_id': session_id,
        'case_id': args.case_id or '',
        'input': args.input,
        'output': result.text,
        'tool_calls': _tool_calls(trace_events),
        'usage': {},
        'cost': 0.0,
        'latency_ms': duration_ms,
        'events': trace_events,
    }
    if trace_path is not None:
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        with trace_path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(trace, ensure_ascii=False, default=str))
            handle.write('\n')
        print(f'trace → {trace_path}')
    if args.json:
        out_json(trace)
    else:
        print(result.text)
    return 0 if result.status == 'done' else 1


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
