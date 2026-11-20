# harness/tools/guard.py
# 工具调用的**唯一入口**（策划案 §3.2 依赖规则 5）。
#
# 为什么必须有这一个入口：审批、审计、幂等、沙箱四件事都需要「在工具执行
# 前后各插一刀」。如果每个调用点自己插，迟早有一个调用点忘了 —— 那正是
# 现在的状况：harness/tools/shell.py 直接 subprocess，模型可以无审批地
# 执行任意 shell。
#
# 一次调用的完整链路：
#
#   ToolRegistry.execute()
#        └─> ToolGuard.execute()
#              ├─ 1. 取 ToolSpec（没有声明 = 最严格档）
#              ├─ 2. PolicyEngine.admit()      → 放行 / 拒绝 / 需要审批
#              ├─ 3. ApprovalBroker.request()  → 需要审批时问人（超时=拒绝）
#              ├─ 4. 幂等检查（RuntimeClient） → 命中则复用上次结果，不重复执行
#              ├─ 5. 写 intent 事件              → 执行前落 journal
#              ├─ 6. 执行 handler（沙箱经 ToolContext 注入）
#              └─ 7. 写 result 事件 + 审计        → 执行后落 journal
#
# 失败方向：任何一步不确定，一律拒绝或标记 unknown_outcome，绝不「先执行了再说」。

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from ..approval.base import (
    ApprovalDecision,
    ApprovalRequest,
)
from ..approval.events import (
    approval_decision_event,
    approval_request_event,
    approval_timeout_event,
)
from ..policy.base import PolicyDecision
from ..runtime_client import NullRuntimeClient, ToolIntent, UnknownOutcomeError
from .base import Tool, ToolResult
from .sandbox.restricted import RestrictedSandbox
from .spec import ToolSpec

logger = logging.getLogger("aicf.harness.tools.guard")

#: 安全模式
#:
#: strict  全链路：策略 + 审批 + 沙箱 + 审计（默认）
#: legacy  直连执行，无审批无审计（仅用于迁移期，会打显著告警）
SecurityMode = str

STRICT_MODE = 'strict'
LEGACY_MODE = 'legacy'


def default_security_mode(default: str = STRICT_MODE) -> str:
    """Read the AICF_SECURITY_MODE environment variable.

    strict (the default) = policy + approval + sandbox + audit
    legacy                = direct calls, for the migration period only
    """
    value = (os.environ.get('AICF_SECURITY_MODE') or default).strip().lower()
    return value if value in (STRICT_MODE, LEGACY_MODE) else default


def args_digest(args: Any) -> str:
    """参数摘要：只存哈希与长度，不存明文。

    审计需要能回答「这两次调用是不是同一组参数」，但不该把用户数据
    （可能含密钥）复制进审计存储。所以存 sha256 + 字符长度。
    """
    try:
        text = json.dumps(args, sort_keys=True, ensure_ascii=False,
                          default=repr, separators=(',', ':'))
    except (TypeError, ValueError):
        text = repr(args)
    digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
    return f'sha256:{digest[:32]}:len={len(text)}'


def _is_unknown_outcome(error: BaseException) -> bool:
    """判断异常是不是「结果未知」。

    跨层识别：infra 不能 import aicf.harness（依赖规则），所以两边各有一份
    UnknownOutcomeError，靠 ``unknown_outcome`` 标记属性互相认出来。

    **认不出来时的行为是「不放行」** —— 上面调用方会把任何异常都当成
    拒绝处理，所以这里认错的最坏后果只是错误信息不够精确，
    不会出现「结果未知却被当成普通失败后重试」。
    """
    return bool(getattr(error, 'unknown_outcome', False))


def preview_args(args: Any, *, limit: int = 400) -> str:
    """给人看的参数摘要（脱敏 + 截断）。

    审批界面会显示它，所以要短、要能看懂、且不能带明文密钥。
    """
    try:
        text = json.dumps(args, sort_keys=True, ensure_ascii=False,
                          default=repr)
    except (TypeError, ValueError):
        text = repr(args)
    if len(text) > limit:
        text = text[:limit] + f'…(共 {len(text)} 字符)'
    return text


@dataclass
class GuardResult:
    """一次受控调用的结果。"""

    result: ToolResult
    decision: PolicyDecision
    approved: bool = False
    degraded: bool = False
    reused: bool = False
    duration_ms: float = 0.0


class ToolGuard:
    """工具调用的守卫。

    典型装配:
        guard = ToolGuard(
            policy=RulePolicyEngine(rules=[...]),
            approval=LocalApprovalBroker(),
            sandbox=RestrictedSandbox(),
            runtime=runtime,
            identity=identity,
        )
        registry.attach_guard(guard)

    没有 guard 时注册表会打一次显著告警 —— 「当前为 legacy 直连模式，
    无审批无审计」（策划案 §9.2）。
    """

    def __init__(self, *,
                 policy: Any = None,
                 approval: Any = None,
                 sandbox: Any = None,
                 telemetry: Any = None,
                 runtime: Any = None,
                 identity: Any = None,
                 audit: Any = None,
                 decision_gate: Any = None,
                 mode: SecurityMode = STRICT_MODE,
                 session_id: str = '',
                 turn_id: str = '',
                 turn_seq: int = 0,
                 approval_timeout: float = 300.0):
        # 注意：「哪些副作用等级需要审批」由 **PolicyEngine** 决定
        # （RulePolicyEngine.require_approval_effects），守卫不自己再判一遍 ——
        # 两处各判一次迟早会不一致，而且会让「改策略却没生效」很难查。
        self.policy = policy
        self.approval = approval
        # A guard without a backend would run every command with the current
        # user's permissions while the tool spec still claims a sandbox. The
        # default keeps the declared boundary real for every guarded call.
        self.sandbox = sandbox if sandbox is not None else RestrictedSandbox()
        self.telemetry = telemetry
        self.runtime = runtime or NullRuntimeClient()
        self.identity = identity
        #: optional System-1 consult before execution (W5.4, default off).
        #: Contract: check(tool=..., args=..., spec=...) returns None to pass
        #: or {'allow': False, 'reason': ...} to refuse.
        self.decision_gate = decision_gate
        #: 不可删审计存储（策划案 §4.4.7「同流但独立存储、不可被业务删除」）。
        #: 鸭子类型契约：只要提供 ``record(kind, payload)`` 一个方法 ——
        #: infra.observability.audit.AuditLog 满足它。audit.* 事件在这里
        #: 落独立存储；telemetry 面的 trace 扇出不因此重复（AuditLog
        #: 构造时不挂 telemetry，trace 由守卫自己的 telemetry 口负责）。
        self.audit = audit
        self.mode = mode
        self.session_id = session_id
        self.turn_id = turn_id
        self.turn_seq = turn_seq
        self.approval_timeout = approval_timeout
        self._legacy_warned = False

    # ── 对外 ──────────────────────────────────────────────
    def spec_for(self, tool: Tool) -> ToolSpec:
        """取工具的契约。没有声明就按最严格档 —— 「忘写声明」不等于放开。"""
        spec = getattr(tool, 'spec', None)
        if isinstance(spec, ToolSpec):
            return spec
        read_only = bool(getattr(tool, 'read_only', False))
        if read_only:
            return ToolSpec.read_only_default(
                tool.name,
                version=str(getattr(tool, 'version', '1.0')),
                summary=getattr(tool, 'description', ''),
                params_schema=getattr(tool, 'parameters', {}) or {},
            )
        return ToolSpec(
            name=tool.name,
            version=str(getattr(tool, 'version', '1.0')),
            summary=getattr(tool, 'description', ''),
            params_schema=getattr(tool, 'parameters', {}) or {},
        )

    async def execute(self, tool: Tool, args: dict[str, Any], *,
                      context: Any = None) -> GuardResult:
        """受控执行一次工具调用。"""
        if self.mode == LEGACY_MODE:
            self._warn_legacy(tool)
            return GuardResult(result=await tool.run_async(**args),
                               decision=PolicyDecision.allow(
                                   detail='legacy 直连模式，无审批无审计'))

        spec = self.spec_for(tool)
        started = time.monotonic()

        # 2. 策略判定
        decision = self._admit(tool, args, spec)
        if not decision.allowed and not decision.needs_approval:
            self._emit_blocked(tool, spec, decision)
            self._emit_denied(tool, decision)
            return GuardResult(result=self._blocked_result(tool, decision),
                               decision=decision)

        # 2.5 decision gate (W5.4, default off): the System-1 mount point.
        # None means byte-for-byte the old behavior; a gate returns None to
        # pass or {'allow': False, 'reason': ...} to refuse.
        if self.decision_gate is not None:
            verdict = self.decision_gate.check(tool=tool.name, args=args,
                                               spec=spec)
            if verdict is not None and not verdict.get('allow', True):
                denial = PolicyDecision.deny(
                    'decision_gate',
                    detail=str(verdict.get('reason') or 'decision gate refused'))
                self._emit_blocked(tool, spec, denial)
                self._emit_denied(tool, denial)
                return GuardResult(result=self._blocked_result(tool, denial),
                                   decision=denial)

        # 3. 审批
        approved = False
        if decision.needs_approval:
            decision, approved = await self._ask_approval(tool, args, spec,
                                                           decision)
            if not approved:
                self._emit_blocked(tool, spec, decision)
                self._emit_denied(tool, decision)
                return GuardResult(result=self._blocked_result(tool, decision),
                                   decision=decision)

        # 4. 幂等检查
        key = self._key(tool, args)
        cached = self.runtime.lookup_tool_result(key)
        if cached is not None:
            self._emit('tool_end', {'tool': tool.name, 'reused': True,
                                    'idempotency_key': key})
            return GuardResult(result=self._as_result(cached),
                               decision=decision, approved=approved,
                               reused=True,
                               duration_ms=(time.monotonic() - started) * 1000)

        # 5. intent 先落 journal，再执行
        #
        # 这一步是**执行前的那道门**：托管运行时发现「同幂等键已有 intent
        # 但没有 result」时会抛 UnknownOutcomeError —— 说明上一次崩溃时
        # 这次 effectful 调用的结果未知（可能已经扣过款了）。
        # 绝不能在这里退让：放过去就是重复副作用。
        intent = ToolIntent(
            session_id=self.session_id,
            turn_seq=self.turn_seq,
            tool=tool.name,
            tool_version=spec.version,
            idempotency_key=key,
            effect=spec.effect,
            args_digest=args_digest(args),
            created_at=time.time(),
        )
        try:
            self.runtime.record_tool_intent(intent)
        except Exception as error:  # noqa: BLE001
            unknown = _is_unknown_outcome(error)
            if unknown:
                self._emit('tool_effect_unknown', {
                    'tool': tool.name,
                    'idempotency_key': key,
                    'effect': spec.effect,
                })
            else:
                logger.exception('写工具意图失败，按拒绝处理: %s', tool.name)
            # 两种情况都不执行 —— fail closed。
            return GuardResult(
                result=ToolResult.fail(
                    f'工具 {tool.name} 未执行：'
                    + ('上一次调用的结果未知（可能已经产生副作用），'
                       '需要人工确认后才能重放。' if unknown
                       else f'无法记录执行意图（{error}）。'),
                    hint=('请向用户确认上一次调用是否已经生效；'
                          '确认无副作用后可以显式重放。' if unknown
                          else '检查运行时存储是否可用。')),
                decision=decision, approved=approved,
                duration_ms=(time.monotonic() - started) * 1000)
        self._emit('tool_intent', {'tool': tool.name, 'idempotency_key': key,
                                   'effect': spec.effect,
                                   'args_digest': args_digest(args)})

        # 6. 执行
        degraded = False
        violations: list = []
        try:
            result = await self._invoke(tool, args, context, violations)
        except Exception as error:  # noqa: BLE001
            logger.exception('工具 %s 执行异常', tool.name)
            result = ToolResult.fail(str(error))

        # 6b. 沙箱拒绝：工具执行前就被挡下，命令根本没跑。
        #     违规码由工具通过 ToolContext.violations 结构化递上来。
        if violations:
            degraded = any(bool(v.get('degraded')) for v in violations)
            for violation in violations:
                self._emit('tool_blocked', {
                    'tool': tool.name,
                    'reason': 'sandbox',
                    'effect': spec.effect,
                    'risk': decision.risk,
                    'violation': str(violation.get('code', '')),
                })
                self._emit('audit.denied', {
                    'identity': self._identity_label(),
                    'tool': tool.name,
                    'reason': 'sandbox',
                    'violation': str(violation.get('code', '')),
                    'detail': str(violation.get('detail', '')),
                })
                self._record_audit({
                    'kind': 'audit.denied',
                    'identity': self._identity_label(),
                    'tool': tool.name,
                    'reason': 'sandbox',
                    'violation': str(violation.get('code', '')),
                    'detail': str(violation.get('detail', '')),
                })
            # A blocked call is not a successful call. The tool may have
            # returned a payload that says otherwise, so the guard decides
            # what the caller sees.
            codes = ', '.join(str(v.get('code', '')) for v in violations)
            result = ToolResult(
                success=False,
                output=result.output,
                error=f'工具 {tool.name} 被沙箱拒绝（{codes}）',
                status='error',
                hint='请在允许的范围内重试，或改用其他工具。',
            )

        # 7. 结果落 journal + 审计
        self.runtime.record_tool_result(key, result, effect=spec.effect)
        duration_ms = (time.monotonic() - started) * 1000
        self._emit('tool_end', {
            'tool': tool.name,
            'idempotency_key': key,
            'duration': duration_ms,
            'success': result.success,
            'error': result.error or '',
        })
        self._audit_call(tool, spec, decision, duration_ms, result, approved,
                          args)
        return GuardResult(result=result, decision=decision, approved=approved,
                           degraded=degraded,
                           duration_ms=duration_ms)

    # ── 内部：判定 ────────────────────────────────────────
    def _admit(self, tool: Tool, args: dict[str, Any],
               spec: ToolSpec) -> PolicyDecision:
        if self.policy is None:
            # 没有策略引擎 = 没有判定能力。按 fail-closed 处理：
            # 只读纯计算工具放行，其余需要审批。
            if spec.effect == 'pure' and not spec.destructive:
                return PolicyDecision.allow(risk='low', detail='无策略引擎，纯计算工具')
            return PolicyDecision.require_approval(
                risk='high', detail='无策略引擎，按默认拒绝处理')
        try:
            decision = self.policy.admit(tool.name, args=args, spec=spec,
                                         identity=self.identity)
        except Exception as error:  # noqa: BLE001
            logger.exception('策略判定异常，按拒绝处理')
            return PolicyDecision.deny('policy',
                                       detail=f'策略判定异常: {error}')
        return decision

    async def _ask_approval(self, tool: Tool, args: dict[str, Any],
                             spec: ToolSpec,
                             decision: PolicyDecision) -> tuple[PolicyDecision, bool]:
        """走审批。超时 = 拒绝（fail-closed）。"""
        if self.approval is None:
            # 没有 broker 时不能默认放行 —— 只能拒绝。
            # 这里没有 request 可用（还没构造），所以先造一个最小的，
            # 只为了让超时事件带得上 id 与工具名。
            stub = ApprovalRequest(id=uuid.uuid4().hex, tool=tool.name,
                                   session_id=self.session_id,
                                   turn_id=self.turn_id)
            self._emit('approval_timeout', approval_timeout_event(stub.id,
                                                                  tool.name))
            return (PolicyDecision.deny('approval',
                                        detail='没有审批代理，默认拒绝'),
                    False)

        request = ApprovalRequest(
            id=uuid.uuid4().hex,
            session_id=self.session_id,
            turn_id=self.turn_id,
            tool=tool.name,
            args_preview=preview_args(args),
            effect=spec.effect,
            destructive=spec.destructive,
            scopes_required=spec.scopes,
            risk=decision.risk,
            expires_at=time.time() + self.approval_timeout,
            detail=decision.detail,
        )
        self._emit('approval_request', approval_request_event(request))
        try:
            outcome = await self.approval.request(request)
        except Exception as error:  # noqa: BLE001
            logger.exception('审批代理异常，按拒绝处理')
            outcome = ApprovalDecision.deny(by='auto-deny',
                                            reason=f'审批异常: {error}')
        if not isinstance(outcome, ApprovalDecision):
            outcome = ApprovalDecision.deny(by='auto-deny',
                                            reason='审批代理返回了非法结果')
        self._emit('approval_decision',
                   approval_decision_event(request.id, tool.name, outcome))
        if outcome.decision == 'timeout':
            self._emit('approval_timeout',
                       approval_timeout_event(request.id, tool.name))
            return (PolicyDecision.deny('approval', detail=outcome.reason,
                                        risk=decision.risk), False)
        if not outcome.approved:
            return (PolicyDecision.deny('approval', detail=outcome.reason,
                                        risk=decision.risk), False)
        return (PolicyDecision.allow(risk=decision.risk,
                                     detail=f'审批通过（{outcome.decided_by}）',
                                     rule_id=request.id), True)

    async def _invoke(self, tool: Tool, args: dict[str, Any],
                      context: Any, violations: list | None = None
                      ) -> ToolResult:
        """执行 handler；有沙箱时通过 ToolContext 注入。

        violations 是一个**由调用方提供**的列表：沙箱拒绝时工具往里 append
        结构化违规记录，执行完守卫再读走。
        之所以不在守卫里自己建列表 —— 那会让「这次调用的违规」和
        「别的调用的违规」在并发下混在一起。
        """
        from .context import current_context, push_context, pop_context
        ctx = current_context()
        original = getattr(ctx, 'sandbox', None)
        had_violations = hasattr(ctx, 'violations')
        original_violations = getattr(ctx, 'violations', None)
        if self.sandbox is not None:
            setattr(ctx, 'sandbox', self.sandbox)
        # The spec travels with the call so the tool can read its own declared
        # network level. Without it a tool that honours the allowlist has no
        # way to know which level was declared.
        original_spec = getattr(ctx, 'tool_spec', None)
        ctx.tool_spec = self.spec_for(tool)
        # violations 通道**总是**注入，不只在挂了沙箱时 ——
        # 工具可以自己发现违规（不只是沙箱会拒），审计通道不该取决于
        # 有没有配沙箱后端。
        if violations is not None:
            setattr(ctx, 'violations', violations)
        token = push_context(ctx)
        try:
            return await tool.run_async(**args)
        finally:
            pop_context(token)
            if self.sandbox is not None:
                if original is None:
                    try:
                        delattr(ctx, 'sandbox')
                    except AttributeError:
                        pass
                else:
                    setattr(ctx, 'sandbox', original)
            ctx.tool_spec = original_spec
            if violations is not None:
                if had_violations:
                    setattr(ctx, 'violations', original_violations)
                else:
                    try:
                        delattr(ctx, 'violations')
                    except AttributeError:
                        pass

    # ── 内部：辅助 ────────────────────────────────────────
    def _key(self, tool: Tool, args: dict[str, Any]) -> str:
        try:
            return self.runtime.idempotency_key(self.session_id, self.turn_seq,
                                                 tool.name, args)
        except Exception:  # noqa: BLE001
            from ..runtime_client import idempotency_key as _key_fn
            return _key_fn(self.session_id, self.turn_seq, tool.name, args)

    def _emit(self, kind: str, payload: dict[str, Any]) -> None:
        if self.telemetry is None:
            return
        try:
            self.telemetry.emit(kind, payload)
        except Exception:  # noqa: BLE001
            logger.exception('遥测事件发送失败: %s', kind)

    def _record_audit(self, payload: dict[str, Any]) -> None:
        """把一条 audit.* 事件落进**不可删**的独立存储（§4.4.7）。

        与 _emit（trace 面）并行调用：trace 会被轮转清理，审计不会 ——
        「审计可被业务删除 = 没有审计」。审计存储故障**不阻断调用**：
        丢进 trace 的审计仍在（同流），把拒绝升级成故障会让
        「策略判定」被「审计可用性」劫持。
        """
        if self.audit is None:
            return
        try:
            self.audit.record(payload.get('kind', ''), dict(payload))
        except Exception:  # noqa: BLE001
            logger.exception('审计存储写入失败（trace 面的审计仍在）')

    def _identity_label(self) -> str:
        """Who the audit record is for: uid for user identities, agent_id for
        AgentIdentity (two different classes, same audit field)."""
        return (getattr(self.identity, 'uid', '')
                or getattr(self.identity, 'agent_id', ''))

    def _emit_denied(self, tool: Tool, decision: PolicyDecision) -> None:
        """审计：一次被拒绝的调用。

        审计与业务事件同流但独立存储 —— 这里是**审计面**的入口，
        不是业务事件。deny 的原因分类（policy / scope / approval / sandbox）
        让复盘时能按原因分组。
        """
        self._emit('audit.denied', {
            'identity': self._identity_label(),
            'tool': tool.name,
            'reason': decision.reason,
            'detail': decision.detail,
        })
        self._record_audit({
            'kind': 'audit.denied',
            'identity': self._identity_label(),
            'tool': tool.name,
            'reason': decision.reason,
            'detail': decision.detail,
        })

    def _emit_blocked(self, tool: Tool, spec: ToolSpec,
                      decision: PolicyDecision) -> None:
        self._emit('tool_blocked', {
            'tool': tool.name,
            'reason': decision.reason,
            'effect': spec.effect,
            'risk': decision.risk,
        })

    def _audit_call(self, tool: Tool, spec: ToolSpec, decision: PolicyDecision,
                    duration_ms: float, result: ToolResult,
                    approved: bool, args: dict[str, Any]) -> None:
        call_audit = {
            'identity': self._identity_label(),
            'tool': tool.name,
            'version': spec.version,
            # The digest has to describe the real arguments, otherwise the
            # audit cannot answer whether two calls were the same request.
            'args_digest': args_digest(args),
            'effect': spec.effect,
            'sandbox': spec.sandbox,
            'decision': 'approved' if approved else 'auto',
            'duration': duration_ms,
            'outcome': 'ok' if result.success else 'error',
        }
        self._emit('audit.tool_call', call_audit)
        self._record_audit({'kind': 'audit.tool_call', **call_audit})

    def _blocked_result(self, tool: Tool,
                        decision: PolicyDecision) -> ToolResult:
        detail = decision.detail or decision.reason
        # 注意：这里**不要**自己加 'Error: ' 前缀 —— 调用方（注册表的
        # execute / CLI）会按约定给失败文本加前缀。这里再加一次就会变成
        # 'Error: Error: ...'。
        return ToolResult.fail(
            f'工具 {tool.name} 被策略拒绝（{decision.reason}）：{detail}',
            hint='可以向用户说明原因，或改用其他工具。',
        )

    @staticmethod
    def _as_result(cached: Any) -> ToolResult:
        if isinstance(cached, ToolResult):
            return cached
        if isinstance(cached, dict):
            return ToolResult(
                success=bool(cached.get('success', True)),
                output=cached.get('output'),
                error=cached.get('error'),
                status=cached.get('status', 'ok'),
                hint=cached.get('hint'),
                data={k: v for k, v in cached.items()
                      if k not in ('success', 'output', 'error', 'status', 'hint')},
            )
        return ToolResult.ok(cached)

    def _warn_legacy(self, tool: Tool) -> None:
        if self._legacy_warned:
            return
        self._legacy_warned = True
        logger.warning(
            '当前为 legacy 直连模式（工具 %s），无审批无审计。'
            '迁移期行为，1.0.0 正式版将移除。', tool.name)


__all__ = [
    'ToolGuard',
    'GuardResult',
    'STRICT_MODE',
    'LEGACY_MODE',
    'args_digest',
    'preview_args',
]
