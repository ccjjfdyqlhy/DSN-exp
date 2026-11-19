# harness/cli/runcmd.py
# `aicf run` —— 跑一次 agent，落一份 trace。
#
# 这条命令是整条链路的入口：run → eval → gate。
# 每次 run 产出一个 trace.jsonl（策划案 §5.4），评测消费的就是它。

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any

from harness.kernel import KernelContext, ReactKernel
from harness.kernel.capability import CapabilitySet

from .common import build_model, build_registry, build_runtime, eprint, out_json


def cmd_run(args: Any) -> int:
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
    from harness.tools.guard import ToolGuard
    from harness.policy.base import PolicyRule
    from harness.approval.broker import LocalApprovalBroker
    from harness.approval.base import ApprovalDecision
    from infra.policy.engine import RulePolicyEngine

    engine = RulePolicyEngine(rules=[
        PolicyRule(action='deny', tool=name, id=f'deny-{name}')
        for name in (args.deny_tool or [])
    ])
    approval = LocalApprovalBroker(
        resolver=(lambda req: ApprovalDecision.approve(by='cli', reason='--yes')
                  if args.yes else
                  ApprovalDecision.deny(by='cli', reason='CLI 未开启 --yes')))
    runtime, store = build_runtime(args.db, session_id)
    guard = ToolGuard(policy=engine, approval=approval, telemetry=collector,
                      runtime=runtime, session_id=session_id, turn_id=run_id)
    registry.attach_guard(guard)

    from infra.orchestrator.base import ChatMessage
    kernel = ReactKernel(client=model, tools=registry, max_steps=args.max_steps)
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
