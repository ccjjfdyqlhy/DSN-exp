# harness/approval/base.py
# 审批（人在回路）的协议与数据结构。
#
# 审批是**内核能力**而不是工具能力（策划案 §4.1.5）：任何工具调用都可能
# 触发策略判定，判定逻辑必须在统一入口。所以协议放在 harness，
# 由 harness/tools/guard.py 在执行前调用；具体 broker 由应用注入。
#
# 失败方向：默认拒绝（fail-closed）。超时 = 拒绝，且 timeout 作为
# 独立决策记入审计 —— 不能把「没等到人」记成「人同意了」。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

#: 审批决策
#:
#: approve         放行这一次
#: approve_once    放行这一次（语义同 approve，保留独立取值便于审计区分）
#: approve_always  放行并记住（作用域见 scope）
#: deny            拒绝
#: timeout         等待超时 —— 语义上等于拒绝
ApprovalOutcome = Literal['approve', 'deny', 'approve_once', 'approve_always',
                          'timeout']

#: 放行作用域（配合 approve_always）
ApprovalScope = Literal['once', 'session', 'tool', 'always']

#: 放行作用域的字符串形式（进缓存 key 与审计）
#: 'once' | 'session' | 'tool:<name>' | 'always'
SCOPE_ONCE = 'once'
SCOPE_SESSION = 'session'
SCOPE_ALWAYS = 'always'


def scope_tool(name: str) -> str:
    """工具级放行作用域的 key。"""
    return f'tool:{name}'


@dataclass(frozen=True)
class ApprovalRequest:
    """一次审批请求。

    id              请求 id（可回填决策）
    session_id      会话 id
    turn_id         轮次 id
    tool            工具名
    args_preview    脱敏后的参数摘要（给人看的，不放明文敏感值）
    effect          副作用等级
    destructive     是否不可逆操作
    scopes_required 需要的授权范围
    risk            风险等级
    expires_at      绝对过期时间（epoch 秒）
    detail          补充说明（为什么需要审批）
    """

    id: str
    session_id: str = ''
    turn_id: str = ''
    tool: str = ''
    args_preview: str = ''
    effect: str = 'effectful'
    destructive: bool = False
    scopes_required: tuple[str, ...] = ()
    risk: str = 'medium'
    expires_at: float = 0.0
    detail: str = ''

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'session_id': self.session_id,
            'turn_id': self.turn_id,
            'tool': self.tool,
            'args_preview': self.args_preview,
            'effect': self.effect,
            'destructive': self.destructive,
            'scopes_required': list(self.scopes_required),
            'risk': self.risk,
            'expires_at': self.expires_at,
            'detail': self.detail,
        }


@dataclass(frozen=True)
class ApprovalDecision:
    """一次审批结果。

    decision   决策取值
    decided_by 谁做的决定（人类 uid / policy rule id / 'auto-deny'）
    reason     理由
    scope      放行作用域；deny/timeout 时为空
    """

    decision: ApprovalOutcome = 'deny'
    decided_by: str = ''
    reason: str = ''
    scope: str | None = None

    @property
    def approved(self) -> bool:
        return self.decision in ('approve', 'approve_once', 'approve_always')

    @classmethod
    def approve(cls, *, by: str = '', reason: str = '',
                scope: str | None = None) -> 'ApprovalDecision':
        return cls(decision='approve', decided_by=by, reason=reason, scope=scope)

    @classmethod
    def deny(cls, *, by: str = '', reason: str = '') -> 'ApprovalDecision':
        return cls(decision='deny', decided_by=by, reason=reason)

    @classmethod
    def timeout(cls, *, by: str = 'auto-deny',
                reason: str = '审批超时（fail-closed）') -> 'ApprovalDecision':
        return cls(decision='timeout', decided_by=by, reason=reason)

    def to_dict(self) -> dict:
        return {
            'decision': self.decision,
            'decided_by': self.decided_by,
            'reason': self.reason,
            'scope': self.scope,
        }


@runtime_checkable
class ApprovalBroker(Protocol):
    """审批代理。

    实现可以是同步等待（CLI / 本地），也可以是异步回调（Web 控制台通过
    SSE 推 approval_request，人点一下再回填）。
    """

    async def request(self, req: ApprovalRequest) -> ApprovalDecision: ...


__all__ = [
    'ApprovalRequest',
    'ApprovalDecision',
    'ApprovalBroker',
    'ApprovalOutcome',
    'ApprovalScope',
    'SCOPE_ONCE',
    'SCOPE_SESSION',
    'SCOPE_ALWAYS',
    'scope_tool',
]
