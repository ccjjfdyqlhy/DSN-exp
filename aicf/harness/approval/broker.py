# harness/approval/broker.py
# 本地审批代理 —— 「谁来按那个同意按钮」的实现。
#
# 两种等待形态（策划案 §4.4.3）：
#   1. 同步等待：给一个 resolver（人机交互回调），代理调用它并等结果。
#      CLI / 本地控制台用这种。
#   2. 异步回填：不给 resolver，代理挂起等 submit(request_id, decision)。
#      Web 控制台通过 SSE 推 approval_request，人点一下再回填，用这种。
#
# 两种形态都遵守同一条铁律：**超时 = 拒绝**。把 timeout 当成同意，
# 等于给了一条「没人看着也能执行」的旁路。
#
# 还有一个容易忽略的场景：审批等待期间进程退出。重启后这次调用必须仍处于
# awaiting_approval，决策可以补填 —— 所以 broker 要能导出/恢复待决请求。

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from typing import Any, Awaitable, Callable, Optional

from .base import (
    ApprovalDecision,
    ApprovalRequest,
    SCOPE_ONCE,
)
from .session import ApprovalCache

logger = logging.getLogger("aicf.harness.approval")

#: 决策回调：给一个请求，返回一个决策（可以同步也可以是协程）
Resolver = Callable[[ApprovalRequest], "ApprovalDecision | Awaitable[ApprovalDecision]"]


class LocalApprovalBroker:
    """本地审批代理。

    用法（同步等待）:
        broker = LocalApprovalBroker(resolver=lambda req: ask_human(req))

    用法（异步回填）:
        broker = LocalApprovalBroker()
        ... 另一个协程: broker.submit(request_id, ApprovalDecision.approve())
    """

    def __init__(self, *, resolver: Resolver | None = None,
                 timeout: float = 300.0,
                 cache: ApprovalCache | None = None,
                 telemetry: Any = None,
                 session_id: str = ''):
        self.resolver = resolver
        self.timeout = timeout
        self.cache = cache if cache is not None else ApprovalCache()
        self.telemetry = telemetry
        self.session_id = session_id
        # 待决请求：id → (request, future)；future 可为 None —— 恢复路径
        # （重启后的线程）可能还没有事件循环，_await_decision 时再挂
        self._pending: dict[str, tuple[ApprovalRequest, asyncio.Future | None]] = {}
        # future 还没挂上时先到的决策，_await_decision 时取走
        self._resolved: dict[str, ApprovalDecision] = {}

    # ── 主入口 ────────────────────────────────────────────
    async def request(self, req: ApprovalRequest) -> ApprovalDecision:
        """等一个决定。

        返回值一定是 ApprovalDecision；出错、超时、无代理都归到拒绝。
        """
        # 已经放行过（会话级 / 工具级缓存）→ 直接放行，不再打扰人
        if self.cache.is_allowed(req.tool, session_id=req.session_id
                                 or self.session_id):
            decision = ApprovalDecision.approve(by='cache',
                                                reason='此前已放行（作用域内）',
                                                scope=SCOPE_ONCE)
            self._emit('approval_decision', {
                'id': req.id, 'tool': req.tool, 'decision': decision.decision,
                'decided_by': decision.decided_by, 'reason': decision.reason,
                'scope': decision.scope or '',
            })
            return decision

        self._emit('approval_request', {
            'id': req.id, 'tool': req.tool,
            'args_preview': req.args_preview, 'effect': req.effect,
            'risk': req.risk, 'expires_at': req.expires_at,
            'session_id': req.session_id, 'turn_id': req.turn_id,
            'destructive': req.destructive,
            'scopes_required': list(req.scopes_required),
            'detail': req.detail,
        })

        try:
            decision = await self._await_decision(req)
        except asyncio.CancelledError:
            # 等待期间被取消（超时 / turn 被中断）—— 按拒绝处理并清理。
            self._discard(req.id)
            self._emit('approval_timeout', {'id': req.id, 'tool': req.tool})
            raise
        except Exception as error:  # noqa: BLE001
            logger.exception('审批等待异常，按拒绝处理')
            self._discard(req.id)
            self._emit('approval_timeout', {'id': req.id, 'tool': req.tool})
            return ApprovalDecision.deny(by='auto-deny',
                                        reason=f'审批异常: {error}')

        self._discard(req.id)
        if decision.decision == 'timeout':
            self._emit('approval_timeout', {'id': req.id, 'tool': req.tool})
            return decision
        self._emit('approval_decision', {
            'id': req.id, 'tool': req.tool, 'decision': decision.decision,
            'decided_by': decision.decided_by, 'reason': decision.reason,
            'scope': decision.scope or '',
        })
        if decision.approved:
            self.cache.remember(req.tool,
                                session_id=req.session_id or self.session_id,
                                scope=decision.scope)
        return decision

    # ── 异步回填 ──────────────────────────────────────────
    def submit(self, request_id: str, decision: ApprovalDecision) -> bool:
        """回填一个待决请求的决策。

        进程重启后由恢复流程调用（见 pending() / restore_pending()）。
        返回是否命中了一个待决请求。
        """
        entry = self._pending.get(request_id)
        if entry is None:
            return False
        _request, future = entry
        if future is None:
            # 恢复路径还没进事件循环：决策先存下，等待时取走
            self._resolved[request_id] = decision
            return True
        if not future.done():
            future.set_result(decision)
        return True

    def pending(self) -> list[ApprovalRequest]:
        """当前所有待决请求（进程退出时导出，重启后恢复）。"""
        return [request for request, _ in self._pending.values()]

    def restore_pending(self, request: ApprovalRequest) -> None:
        """恢复一个待决请求（重启后调用）。

        恢复出来的请求已经在 journal 里留下了 approval_request 事件，
        所以这里**不重复发事件** —— 只把等待重新挂起来。
        """
        if request.id in self._pending:
            return
        # expires_at is written by the guard but was never enforced on this
        # path (W8): a restored request past its deadline must not come back
        # to life -- re-arming would grant a stale approval window
        expires_at = float(getattr(request, 'expires_at', 0.0) or 0.0)
        if expires_at and expires_at <= time.time():
            self._pending.pop(request.id, None)
            self._emit('approval_expired', {'request_id': request.id,
                                            'tool': getattr(request, 'tool', '')})
            return
        try:
            future: asyncio.Future | None = asyncio.get_event_loop().create_future()
        except RuntimeError:
            future = None  # no loop in this thread yet; armed at await time
        self._pending[request.id] = (request, future)

    # ── 内部 ──────────────────────────────────────────────
    async def _await_decision(self, req: ApprovalRequest) -> ApprovalDecision:
        if self.resolver is not None:
            outcome = self.resolver(req)
            if inspect.isawaitable(outcome):
                outcome = await outcome
            if isinstance(outcome, ApprovalDecision):
                return outcome
            return ApprovalDecision.deny(by='auto-deny',
                                        reason='resolver 返回了非法结果')

        # 无 resolver → 挂起等回填；恢复路径可能已经先交了决策
        resolved = self._resolved.pop(req.id, None)
        if resolved is not None:
            return resolved
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[req.id] = (req, future)
        try:
            decision = await asyncio.wait_for(future, timeout=self.timeout)
        except asyncio.TimeoutError:
            return ApprovalDecision.timeout()
        if not isinstance(decision, ApprovalDecision):
            return ApprovalDecision.deny(by='auto-deny',
                                        reason='回填了非法决策')
        return decision

    def _discard(self, request_id: str) -> None:
        self._pending.pop(request_id, None)
        self._resolved.pop(request_id, None)

    def _emit(self, kind: str, payload: dict) -> None:
        if self.telemetry is None:
            return
        try:
            self.telemetry.emit(kind, payload)
        except Exception:  # noqa: BLE001
            logger.exception('审批事件发送失败: %s', kind)


class AutoDenyBroker:
    """永远拒绝的代理。

    存在的意义：让「没有审批能力」这件事**显式化**。
    与其让代码路径在没有 broker 时行为含糊，不如给一个明确拒绝的代理，
    审计里能看出「这个环境不具备审批能力」。
    """

    def __init__(self, reason: str = '当前环境不具备审批能力'):
        self.reason = reason

    async def request(self, req: ApprovalRequest) -> ApprovalDecision:
        return ApprovalDecision.deny(by='auto-deny', reason=self.reason)


__all__ = ['LocalApprovalBroker', 'AutoDenyBroker', 'Resolver']
