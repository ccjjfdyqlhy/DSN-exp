# infra/control/identity.py
# Agent 身份与委托授权（策划案 §4.4.5）。
#
# ── 与用户态 Identity 的关系 ──
# infra/auth/base.py 的 Identity 是**用户**身份（uid + scopes），两者不混用：
# 一个回答「哪个人在操作」，一个回答「哪个 Agent 拿着什么权限在干活」。
# 策划案 §9.1 明确：保留用户 Identity，新增 AgentIdentity，两者不混用。
#
# ── 为什么委托必须是「子集」而不是「任意授予」 ──
# 父 Agent 把自己没有的权限授给子 Agent，等于凭空造权 —— 审计链上任何
# 一环都无法回答「这个权限最初从哪来」。所以子 scope 必须是父 scope 的
# 子集，且 delegation_chain 完整记录授权路径，越权即拒。
#
# ── 凭据 ──
# credential_refs 只存**引用**（如 'vault://prod/db'），明文永不落日志、
# 事件、trace。脱敏统一走 infra/observability/redact.py 的 redact()。

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger('aicf.infra.control.identity')


class DelegationError(RuntimeError):
    """一次不合法的授权传递（子 scope 超出父 scope，或链条断裂）。"""


@dataclass(frozen=True)
class AgentIdentity:
    """一个 Agent 的可审计身份。

    agent_id           Agent 的稳定标识（如 'research-assistant'）
    tenant             租户（rc0 多租户只设计不隔离，字段先占位）
    scopes             本 Agent 持有的授权范围
    delegated_by       直接授权来源（父 Agent id 或 'user'）
    delegation_chain   完整授权路径，从最初授权者到本 Agent；可审计、可截断
    credential_refs    凭据**引用**（不是凭据本身）
    """

    agent_id: str
    tenant: str = 'default'
    scopes: tuple[str, ...] = ()
    delegated_by: str | None = None
    delegation_chain: tuple[str, ...] = ()
    credential_refs: tuple[str, ...] = ()

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    def missing_scopes(self, required: Iterable[str]) -> tuple[str, ...]:
        """工具所需的 scope 里有哪些不在本身份内（策划案 §4.4.5「越权即拒」）。"""
        have = set(self.scopes)
        return tuple(s for s in required if s not in have)

    def to_dict(self) -> dict[str, Any]:
        return {
            'agent_id': self.agent_id,
            'tenant': self.tenant,
            'scopes': list(self.scopes),
            'delegated_by': self.delegated_by,
            'delegation_chain': list(self.delegation_chain),
            'credential_refs': list(self.credential_refs),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentIdentity:
        return cls(
            agent_id=str(data.get('agent_id') or ''),
            tenant=str(data.get('tenant') or 'default'),
            scopes=tuple(data.get('scopes') or ()),
            delegated_by=data.get('delegated_by'),
            delegation_chain=tuple(data.get('delegation_chain') or ()),
            credential_refs=tuple(data.get('credential_refs') or ()),
        )


def validate_delegation(parent: AgentIdentity,
                        child_scopes: Iterable[str]) -> tuple[str, ...]:
    """校验一次授权传递：子 scope 必须是父 scope 的子集。

    返回规范化后的子 scope 元组；越权时抛 DelegationError ——
    「越权即拒」，绝不静默截断后放行（截断是降级策略，不是授权策略）。
    """
    requested = tuple(child_scopes or ())
    parent_scopes = set(parent.scopes)
    missing = [s for s in requested if s not in parent_scopes]
    if missing:
        raise DelegationError(
            f'委托越权: {parent.agent_id} 试图把不在自己权限内的 scope '
            f'{missing} 授给子 Agent（父 scope: {sorted(parent_scopes)}）')
    return requested


def derive_child(parent: AgentIdentity, *, agent_id: str,
                 scopes: Iterable[str], tenant: str = '',
                 credential_refs: Iterable[str] = ()) -> AgentIdentity:
    """从父身份派生一个子 Agent 身份（校验 + 链条拼接）。

    delegation_chain 一定是**父链条 + 父自身**：审计时沿链回溯，
    「这个权限最初从哪来」这个问题的答案就是链条的第 0 个元素。
    """
    granted = validate_delegation(parent, scopes)
    chain = tuple(parent.delegation_chain) + (parent.agent_id,)
    return AgentIdentity(
        agent_id=agent_id,
        tenant=tenant or parent.tenant,
        scopes=granted,
        delegated_by=parent.agent_id,
        delegation_chain=chain,
        credential_refs=tuple(credential_refs or ()),
    )


@dataclass
class DelegationAudit:
    """一次委托的审计载荷（策划案 §4.4.7 audit.delegation）。"""

    from_: str
    to: str
    scopes: tuple[str, ...] = ()
    ts: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            'from': self.from_,
            'to': self.to,
            'scopes': list(self.scopes),
            'ts': self.ts or time.time(),
        }


def delegate(parent: AgentIdentity, *, agent_id: str,
             scopes: Iterable[str], tenant: str = '',
             credential_refs: Iterable[str] = (),
             audit: Any = None) -> tuple[AgentIdentity, DelegationAudit | None]:
    """委托一次授权：派生子身份 + 记审计。

    audit 是鸭子类型的审计器（infra/observability/audit.py 的 AuditLog 或
    任何提供 ``delegation(from_, to, scopes)`` 方法的对象）——
    infra/control 不 import aicf.infra.observability 的实现，靠注入保持可替换。
    审计写入失败**不阻断授权**（与 AuditLog.record 的同流失败同策略：
    丢审计比丢授权更糟——不对，授权是事实，审计失败记日志）。
    """
    child = derive_child(parent, agent_id=agent_id, scopes=scopes,
                         tenant=tenant, credential_refs=credential_refs)
    payload = DelegationAudit(
        from_=parent.agent_id, to=child.agent_id, scopes=child.scopes)
    if audit is not None:
        try:
            audit.delegation(parent.agent_id, child.agent_id, child.scopes)
        except Exception:
            # 审计后端故障不回滚授权本身（授权已成立，抛出会让调用方误以为
            # 授权失败而重试，产生第二条链），但也不能静默 —— 记日志留痕。
            logger.exception('授权审计写入失败 from=%s to=%s',
                             parent.agent_id, child.agent_id)
    return child, payload


def check_spawn_scopes(parent: AgentIdentity,
                       child_scopes: Iterable[str]) -> None:
    """子 Agent spawn 前的 scope 校验入口（策划案诚实清单第三条）。

    与 validate_delegation 同义，单独一个名字是为了让 spawn 调用点的
    意图可读：spawn 校验读起来像 spawn 校验，不像一般委托。
    """
    validate_delegation(parent, child_scopes)


__all__ = [
    'AgentIdentity',
    'DelegationAudit',
    'DelegationError',
    'check_spawn_scopes',
    'delegate',
    'derive_child',
    'validate_delegation',
]
