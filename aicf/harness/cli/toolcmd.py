# harness/cli/toolcmd.py
# `aicf tool` —— 工具目录与手工执行。
#
# `aicf tool list`  输出目录快照（名字、版本、副作用等级、沙箱档位、
#                 所需 scope）—— 这正是策划案 §4.4.2 的 ToolDiscovery.list，
#                 评测按工具版本分组、控制面资产管理都用它。
# `aicf tool exec` 手工执行一次工具，**带策略**：越权会被拒、
#                 effectful 工具要审批（CLI 下用 --yes 直接放行，
#                 否则显式拒绝，绝不静默放行）。

from __future__ import annotations

import asyncio
import json
from typing import Any

from .common import (
    ToolCatalog,
    attach_project_tools,
    build_registry,
    build_runtime,
    eprint,
    out_json,
    security_mode,
)


def cmd_list(args: Any) -> int:
    registry = build_registry(include=args.include or None)
    found = attach_project_tools(registry)
    if found:
        eprint(f'[aicf] 已从 ./tools/ 装载 {found} 个项目本地工具')
    rows = ToolCatalog(registry).entries()
    if args.json:
        out_json(rows)
        return 0
    if not rows:
        print('(没有工具)')
        return 0
    width = max(len(row['name']) for row in rows)
    print(f'{"tool".ljust(width)}  {"effect":<10} {"sandbox":<9} '
          f'{"net":<9} {"destructive":<10} version')
    for row in rows:
        print(f'{row["name"].ljust(width)}  {row["effect"]:<10} '
              f'{row["sandbox"]:<9} {row["network"]:<9} '
              f'{str(row["destructive"]):<10} {row["version"]}')
    return 0


def cmd_exec(args: Any) -> int:
    try:
        call_args = json.loads(args.args_json or '{}')
    except json.JSONDecodeError as error:
        eprint(f'参数不是合法 JSON: {error}')
        return 2
    if not isinstance(call_args, dict):
        eprint('参数必须是一个 JSON 对象')
        return 2

    registry = build_registry(include=args.include or None)
    attach_project_tools(registry)
    tool = registry.get(args.name)
    if tool is None:
        eprint(f'工具不存在: {args.name}')
        eprint('用 `aicf tool list` 看可用工具')
        return 2

    from aicf.harness.approval.broker import LocalApprovalBroker
    from aicf.harness.approval.base import ApprovalDecision
    from aicf.harness.policy.base import PolicyRule
    from aicf.harness.tools.guard import ToolGuard
    from aicf.infra.policy.engine import RulePolicyEngine

    mode = security_mode('strict' if args.policy == 'strict' else 'legacy')
    if args.policy == 'legacy':
        mode = 'legacy'
    elif args.policy == 'strict':
        mode = 'strict'

    rules = []
    if args.deny:
        for name in args.deny:
            rules.append(PolicyRule(action='deny', tool=name, id=f'deny-{name}'))
    if args.allow:
        for name in args.allow:
            rules.append(PolicyRule(action='allow', tool=name, id=f'allow-{name}'))
    engine = RulePolicyEngine(rules=rules)

    approval = LocalApprovalBroker(
        resolver=(lambda req: ApprovalDecision.approve(by='cli', reason='--yes')
                  if args.yes else
                  ApprovalDecision.deny(by='cli', reason='CLI 未开启 --yes')),
        timeout=args.approval_timeout)

    runtime, store = build_runtime(args.db, args.name)
    # 不可删审计（策划案 §4.4.7）：手工执行也落审计，不留旁路。
    from aicf.infra.observability.audit import AuditLog
    audit_log = AuditLog()
    identity = None
    if getattr(args, 'identity', ''):
        from aicf.infra.control.identity import AgentIdentity
        identity = AgentIdentity(agent_id=args.identity, delegated_by='user')
    guard = ToolGuard(policy=engine, approval=approval, mode=mode,
                      identity=identity, runtime=runtime, audit=audit_log,
                      session_id=args.name)
    registry.attach_guard(guard)

    try:
        result = asyncio.run(registry.execute_async(args.name, call_args))
    finally:
        store.close()
    payload = {
        'tool': args.name,
        'success': result.success,
        'output': result.output,
        'error': result.error,
        'status': result.status,
    }
    if args.json:
        out_json(payload)
    else:
        if result.success:
            print(result.output if isinstance(result.output, str)
                  else json.dumps(result.output, ensure_ascii=False, default=str))
        else:
            eprint(f'Error: {result.error}')
    return 0 if result.success else 1


__all__ = ['cmd_exec', 'cmd_list']
