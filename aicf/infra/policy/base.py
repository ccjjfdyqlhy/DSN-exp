# infra/policy/base.py
# 工具准入策略的**协议**与判定结果。
#
# 为什么这个端口住在 infra 而不是 harness：
# 仓库的端口约定是「端口与共享数据类型住在 infra，harness 往上依赖它」——
# IChatClient 在 infra/orchestrator/base.py、IStore 在 infra/store/base.py、
# Identity 在 infra/auth/base.py，都是同一个模式。策划案 §5.3 里的
# `PolicyEngine | infra/policy/engine.py` 也是这个意思。
#
# 依赖方向只有一条：**harness → infra**。infra 不得 import aicf.harness ——
# 曾经 infra/observability/core.py 反向 import aicf.harness.pipeline.events 就是
# 被当成违规清掉的（见 docs/architecture.md）。
# 所以 harness/policy/base.py 现在只是这个模块的**再导出**，让 harness 侧的
# 代码仍然能用 `from ..policy.base import PolicyDecision` 这样的短路径。
#
# 语义（策划案 §4.4.3 的求值顺序，先命中先生效）：
#   1. 显式 deny 规则 —— 永远赢
#   2. 显式 allow 规则
#   3. 风险等级阈值（risk <= threshold 自动放行）
#   4. 默认拒绝 → 需要人工审批

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

#: 风险等级
Risk = Literal['low', 'medium', 'high']

#: 拒绝原因分类 —— 审计与评测按这个分组
#:
#: policy   策略规则命中（显式 deny）
#: scope    身份范围不足（越权）
#: sandbox  沙箱档位不足
#: network  网络档位不足
#: approval 人工审批未通过
#: deny_default 默认拒绝（走了审批但没人批 / 超时）
DeniedReason = Literal['policy', 'scope', 'sandbox', 'network', 'approval',
                       'deny_default']


@dataclass(frozen=True)
class PolicyDecision:
    """一次准入判定的结果。

    allowed       是否放行
    reason        拒绝原因分类（allowed=True 时为空串）
    risk          风险等级
    needs_approval 是否需要人工审批
    detail        人可读的说明，进审计
    rule_id       命中的规则 id（可追溯到具体哪条规则）
    """

    allowed: bool
    reason: str = ''
    risk: Risk = 'low'
    needs_approval: bool = False
    detail: str = ''
    rule_id: str = ''

    @classmethod
    def allow(cls, *, risk: Risk = 'low', detail: str = '',
              rule_id: str = '') -> 'PolicyDecision':
        return cls(allowed=True, risk=risk, detail=detail, rule_id=rule_id)

    @classmethod
    def deny(cls, reason: str, *, detail: str = '',
             rule_id: str = '', risk: Risk = 'medium') -> 'PolicyDecision':
        return cls(allowed=False, reason=reason, risk=risk,
                   detail=detail, rule_id=rule_id)

    @classmethod
    def require_approval(cls, *, risk: Risk = 'medium', detail: str = '',
                          rule_id: str = '') -> 'PolicyDecision':
        """需要人工审批。

        注意方法名不能叫 needs_approval —— 那是同名的 dataclass 字段。
        撞名的后果很隐蔽：类体里后定义的 classmethod 覆盖了字段默认值，
        dataclass 于是把「类方法对象」当成 needs_approval 的默认值，
        每次构造都得到一个 bound method 而不是 False。
        """
        return cls(allowed=False, reason='deny_default', risk=risk,
                   needs_approval=True, detail=detail, rule_id=rule_id)

    def to_dict(self) -> dict:
        return {
            'allowed': self.allowed,
            'reason': self.reason,
            'risk': self.risk,
            'needs_approval': self.needs_approval,
            'detail': self.detail,
            'rule_id': self.rule_id,
        }


@dataclass(frozen=True)
class PolicyRule:
    """一条准入规则。

    action      allow | deny
    tool        匹配的工具名；'*' 表示全部
    tool_prefix 匹配的工具名前缀；与 tool 二选一
    effect      只对该副作用等级生效
    sandbox     只对该沙箱档位生效
    scopes      该规则授予/需要的 scope
    risk        允许的最高风险等级
    reason      命中后写进审计的理由
    id          规则 id（进审计，便于追溯）
    """

    action: Literal['allow', 'deny']
    id: str = ''
    tool: str = '*'
    tool_prefix: str = ''
    effect: str = ''
    sandbox: str = ''
    scopes: tuple[str, ...] = ()
    risk: Risk = 'high'
    reason: str = ''

    def matches(self, tool_name: str, *, effect: str = '',
                sandbox: str = '') -> bool:
        if self.tool not in ('*', '', tool_name):
            return False
        if self.tool_prefix and not tool_name.startswith(self.tool_prefix):
            return False
        if self.effect and self.effect != effect:
            return False
        if self.sandbox and self.sandbox != sandbox:
            return False
        return True


@runtime_checkable
class PolicyEngine(Protocol):
    """工具准入策略引擎。

    admit 返回一个**判定**，而不是直接执行：调用方（ToolGuard）负责
    根据 needs_approval 去问审批 broker。
    """

    def admit(self, tool: str, *, args: dict[str, Any] | None = None,
              spec: Any = None, identity: Any = None) -> PolicyDecision: ...


__all__ = [
    'PolicyDecision',
    'PolicyRule',
    'PolicyEngine',
    'Risk',
    'DeniedReason',
]
