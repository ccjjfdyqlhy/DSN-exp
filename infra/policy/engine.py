# infra/policy/engine.py
# 工具准入策略引擎 —— 「这个工具能不能被调用」的判定中心。
#
# 为什么需要它（策划案 §2.2 缺口矩阵）：审批 / 沙箱 / 审计三件事都需要一个
# **共同的判定输入**。没有引擎时，每个调用点各自拍脑袋，于是「要不要审批」
# 变成一个散落在代码各处的 if，而审计根本无从记录。
#
# 求值顺序（策划案 §4.4.3，先命中先生效）：
#   1. 显式 deny 规则 —— 永远赢，哪怕后面有 allow 规则
#   2. 越权检查（工具所需 scope 不在身份 scope 内）→ 拒绝
#   3. 显式 allow 规则（如只读工具白名单）
#   4. 风险等级阈值（risk <= threshold 自动放行）
#   5. 默认拒绝 → 需要人工审批
#
# fail-closed 是硬要求：任何判定不出来的情况一律走「需要审批」，
# 绝不默认放行。

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from .base import PolicyDecision, PolicyRule

logger = logging.getLogger("infra.policy")

#: 风险等级排序（用于比较大小）
_RISK_ORDER = {'low': 0, 'medium': 1, 'high': 2}


def _risk_at_most(risk: str, threshold: str) -> bool:
    return _RISK_ORDER.get(risk, 2) <= _RISK_ORDER.get(threshold, 0)


def compute_risk(spec: Any) -> str:
    """按工具契约算风险等级。

    spec 只需要有 ``effect`` / ``destructive`` / ``network`` / ``sandbox``
    四个属性 —— 不 import harness 的 ToolSpec（infra 不得依赖 harness）。
    这与 infra/eval 只认自己定义的 Trace/ToolCall 是同一个做法：
    端口在两边各自定义，靠属性对齐。

    三个上调因子：
      - destructive（不可逆操作）→ 直接 high
      - effectful（对外副作用）→ high
      - network='full' → 升一级（数据可能外流）
      - sandbox='none' → 升一级（没有隔离，逃逸代价高）
    """
    effect = str(getattr(spec, 'effect', '') or 'effectful')
    destructive = bool(getattr(spec, 'destructive', False))
    network = str(getattr(spec, 'network', '') or 'none')
    sandbox = str(getattr(spec, 'sandbox', '') or 'none')

    if destructive:
        risk = 'high'
    elif effect == 'effectful':
        risk = 'high'
    elif effect == 'idempotent':
        risk = 'medium'
    else:
        risk = 'low'

    if network == 'full' and risk != 'high':
        risk = 'medium' if risk == 'low' else 'high'
    if sandbox == 'none' and risk == 'low':
        risk = 'medium'
    return risk


def _identity_scopes(identity: Any) -> Optional[set[str]]:
    """取身份上的 scope 集合；没有身份时返回 None（表示「不检查越权」）。"""
    if identity is None:
        return None
    scopes = getattr(identity, 'scopes', None)
    if scopes is None:
        return None
    return set(scopes)


@dataclass(frozen=True)
class _SpecView:
    """工具契约的统一视图（infra 侧的本地副本）。

    只保留策略判定需要的字段。刻意**不** import harness 的 ToolSpec ——
    依赖方向是 harness → infra，infra 反向依赖就是违规。
    """

    name: str = ''
    version: str = '1.0'
    effect: str = 'effectful'
    scopes: tuple[str, ...] = ()
    sandbox: str = 'isolated'
    network: str = 'none'
    destructive: bool = False


@dataclass
class RulePolicyEngine:
    """基于规则的工具准入引擎。

    rules            规则列表（先 deny 后 allow 的顺序由 admit 内部保证）
    identity         默认身份；admit 时可逐次覆盖
    auto_approve_risk 低于等于该风险等级自动放行（默认 'low'）
    require_approval_effects 哪些副作用等级必须走审批
    deny_unknown_tools  工具没有 spec 时按最严格处理（默认 True）
    allow_readonly     是否放行只读工具（默认 True）

    用法:
        engine = RulePolicyEngine(rules=[
            PolicyRule(action='allow', tool='fs.read', id='r-read'),
            PolicyRule(action='deny', tool='shell', id='r-no-shell'),
        ])
        decision = engine.admit('fs.read', spec=spec, identity=identity)
    """

    rules: list[PolicyRule] = field(default_factory=list)
    identity: Any = None
    auto_approve_risk: str = 'low'
    require_approval_effects: tuple[str, ...] = ('effectful',)
    deny_unknown_tools: bool = True
    allow_readonly: bool = True

    def add_rule(self, rule: PolicyRule) -> 'RulePolicyEngine':
        self.rules.append(rule)
        return self

    # ── 主判定 ────────────────────────────────────────────
    def admit(self, tool: str, *, args: dict[str, Any] | None = None,
              spec: Any = None, identity: Any = None) -> PolicyDecision:
        """判定一次工具调用。

        返回值是**判定**而不是执行结果 —— 需要审批时由调用方去问 broker。
        """
        effective_spec = self._coerce_spec(tool, spec)
        risk = compute_risk(effective_spec)
        ident = identity if identity is not None else self.identity

        # 1. 显式 deny —— 永远赢
        for rule in self.rules:
            if rule.action != 'deny':
                continue
            if rule.matches(tool, effect=effective_spec.effect,
                            sandbox=effective_spec.sandbox):
                return PolicyDecision.deny(
                    'policy',
                    detail=rule.reason or f'规则 {rule.id or "(匿名)"} 拒绝 {tool}',
                    rule_id=rule.id,
                    risk=risk)

        # 2. 越权检查 —— 工具所需 scope 不在身份 scope 内
        scope_decision = self._check_scopes(effective_spec, ident, risk)
        if scope_decision is not None:
            return scope_decision

        # 3. 显式 allow
        for rule in self.rules:
            if rule.action != 'allow':
                continue
            if rule.matches(tool, effect=effective_spec.effect,
                            sandbox=effective_spec.sandbox):
                return PolicyDecision.allow(
                    risk=risk,
                    detail=rule.reason or f'规则 {rule.id or "(匿名)"} 放行 {tool}',
                    rule_id=rule.id)

        # 4. 风险阈值自动放行
        if _risk_at_most(risk, self.auto_approve_risk):
            return PolicyDecision.allow(risk=risk,
                                        detail=f'风险 {risk} 不超过自动放行阈值')

        # 4b. 只读工具白名单（默认放行，但 destructive 的一律不适用）
        if (self.allow_readonly and effective_spec.effect == 'pure'
                and not effective_spec.destructive):
            return PolicyDecision.allow(risk=risk, detail='只读工具自动放行')

        # 5. 默认拒绝 → 需要人工审批
        needs = effective_spec.effect in self.require_approval_effects
        if not needs:
            # 不在「必须审批」的副作用等级里，但风险超过自动放行阈值 ——
            # 仍然需要审批（只是风险等级低一些）。
            needs = True
        return PolicyDecision.require_approval(
            risk=risk,
            detail=(f'{tool} 风险 {risk}，无放行规则，需要人工审批'))

    # ── 内部 ──────────────────────────────────────────────
    def _coerce_spec(self, tool: str, spec: Any) -> '_SpecView':
        """把任意来源的 spec 归一成统一视图。

        没有 spec 时按最严格档生成 —— 「忘写声明」不等于「默认放开」。

        视图是本地的 dataclass 而不是 harness 的 ToolSpec：infra 不得
        依赖 harness，所以这里按属性取值，harness 那边传什么都能吃。
        """
        if isinstance(spec, _SpecView):
            return spec
        if spec is None:
            return _SpecView(name=tool)
        return _SpecView(
            name=str(getattr(spec, 'name', tool) or tool),
            version=str(getattr(spec, 'version', '1.0')),
            effect=str(getattr(spec, 'effect', 'effectful') or 'effectful'),
            scopes=tuple(getattr(spec, 'scopes', ()) or ()),
            sandbox=str(getattr(spec, 'sandbox', 'isolated') or 'isolated'),
            network=str(getattr(spec, 'network', 'none') or 'none'),
            destructive=bool(getattr(spec, 'destructive', False)),
        )

    def _check_scopes(self, spec: ToolSpec, identity: Any,
                      risk: str) -> Optional[PolicyDecision]:
        """越权检查。没有身份时不做检查（本地单用户场景）。"""
        if not spec.scopes:
            return None
        scopes = _identity_scopes(identity)
        if scopes is None:
            return None
        missing = [s for s in spec.scopes if s not in scopes]
        if not missing:
            return None
        return PolicyDecision.deny(
            'scope',
            detail=f'{spec.name} 需要 scope {missing}，当前身份 {sorted(scopes)}',
            risk=risk)


def default_policy_engine(*, identity: Any = None,
                           allow_readonly: bool = True) -> RulePolicyEngine:
    """默认引擎：只读工具自动放行，其余走审批。

    这是「deny-by-default，但不是一刀切不可用」的平衡点 ——
    纯计算工具（读文件、算数）不该每次都问人。
    """
    return RulePolicyEngine(identity=identity, allow_readonly=allow_readonly)


__all__ = ['RulePolicyEngine', 'compute_risk', 'default_policy_engine']
