# harness/tools/spec.py
# 工具的契约化描述 —— 一个工具「能干什么、有多大副作用、需要什么权限」的声明。
#
# 为什么要它：以前 Tool 只有 name/description/parameters，工具的副作用等级、
# 沙箱需求、所需授权范围全靠人脑记住。于是「模型可以无审批地执行任意 shell」
# 这件事在代码里没有任何痕迹可查 —— 策略引擎没有输入，审计没有字段。
#
# ToolSpec 把这些属性变成**可声明、可校验、可评测**的一等数据：
#   - 准入策略（infra/policy/engine.py）按 spec 判定是否放行
#   - 审批（harness/approval/）按 spec.effect / spec.destructive 决定是否要人点头
#   - 幂等（infra/runtime/idempotency.py）按 spec.effect 决定恢复时能不能重放
#   - 评测（infra/eval/）按 spec.group 分组对比
#
# 设计原则（策划案 §3.3.1「默认拒绝」）：**未声明 = 最严格**。
# 一个工具不写 spec，就按 effectful + isolated + 需审批处理 —— 绝不因为
# 「忘写声明」而静默放开权限。

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal

#: 副作用分级 —— 决定恢复时能否自动重放（策划案 §4.2.3）
#:
#: pure        纯计算，重放无副作用
#: idempotent  写操作但重复执行无害（可自动重放）
#: effectful   发消息 / 扣款 / 改外部系统（**默认不自动重放**）
Effect = Literal['pure', 'idempotent', 'effectful']

#: 沙箱档位 —— 工具运行时的隔离强度（策划案 §4.4.4）
#:
#: none       不隔离（仅测试）
#: readonly   只读挂载
#: workspace  限定在工作区根目录内
#: isolated   独立命名空间 / 容器
SandboxLevel = Literal['none', 'readonly', 'workspace', 'isolated']

#: 网络档位（策划案 §4.4.6）
NetworkLevel = Literal['none', 'allowlist', 'full']

#: 隔离强度排序 —— 用于比较两个 spec 谁更严格
_SANDBOX_ORDER: dict[str, int] = {
    'none': 0,
    'readonly': 1,
    'workspace': 2,
    'isolated': 3,
}

_EFFECT_ORDER: dict[str, int] = {
    'pure': 0,
    'idempotent': 1,
    'effectful': 2,
}

_NETWORK_ORDER: dict[str, int] = {
    'none': 0,
    'allowlist': 1,
    'full': 2,
}


@dataclass(frozen=True)
class ToolSpec:
    """一个工具的契约。

    name            工具名（与 Tool.name 一致）
    version         语义化版本，参与控制面的版本治理（策划案 §4.4.2）
    summary         给人看的用途摘要
    params_schema   JSON Schema（与 Tool.parameters 一致，保留两份以便独立发现）
    effect          副作用分级，默认 effectful（最严格）
    scopes          调用所需的授权范围；不在 identity.scopes 内 → 拒绝
    sandbox         沙箱档位，默认 isolated（最严格）
    network         网络档位，默认 none
    destructive     是否不可逆操作（rm -rf / drop table）
    owner           责任归属，进控制面
    group           评测分组，用于对比时按能力分组
    """

    name: str
    version: str = '1.0'
    summary: str = ''
    params_schema: dict = field(default_factory=dict)
    effect: Effect = 'effectful'
    scopes: tuple[str, ...] = ()
    sandbox: SandboxLevel = 'isolated'
    network: NetworkLevel = 'none'
    destructive: bool = False
    owner: str = ''
    group: str = ''

    # ── 构造辅助 ───────────────────────────────────────────
    @classmethod
    def strict_default(cls, name: str, **kwargs: Any) -> 'ToolSpec':
        """未声明任何属性的工具：按最严格档生成一份 spec。

        这是「默认拒绝」的落点 —— 不是在策略里写 if-undeclared-then-allow，
        而是在**没有 spec 这件事本身**上就取最严格值。
        """
        return cls(name=name, **kwargs)

    @classmethod
    def read_only_default(cls, name: str, **kwargs: Any) -> 'ToolSpec':
        """只读工具的默认 spec：纯计算 + 只读沙箱 + 无网络。

        用于已有工具里明确声明了 read_only 的那些 —— 「只读」本身就是一条
        显式声明，所以可以据此收窄默认值。
        """
        kwargs.setdefault('effect', 'pure')
        kwargs.setdefault('sandbox', 'readonly')
        kwargs.setdefault('network', 'none')
        return cls(name=name, **kwargs)

    # ── 派生 ───────────────────────────────────────────────
    @property
    def is_effectful(self) -> bool:
        """是否有不可自动重放的外部副作用。"""
        return self.effect == 'effectful'

    @property
    def replay_safe(self) -> bool:
        """恢复时能否自动重放。

        pure 与 idempotent 可以；effectful 不行 —— 它要么根本不重放，
        要么在重放前必须重新走一次审批。
        """
        return self.effect in ('pure', 'idempotent')

    @property
    def requires_approval(self) -> bool:
        """是否必须人工点头。

        destructive 的工具永远要审批；effectful 的工具默认要审批
        （除非被策略显式放行）。
        """
        return self.destructive or self.effect == 'effectful'

    def with_version(self, version: str) -> 'ToolSpec':
        return replace(self, version=version)

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'version': self.version,
            'summary': self.summary,
            'effect': self.effect,
            'scopes': list(self.scopes),
            'sandbox': self.sandbox,
            'network': self.network,
            'destructive': self.destructive,
            'owner': self.owner,
            'group': self.group,
        }

    def catalog_entry(self) -> dict:
        """工具目录快照条目（策划案 §4.4.2 的 ToolDiscovery.list）。"""
        entry = self.to_dict()
        entry['params_schema'] = self.params_schema
        return entry


def stricter_than(left: 'ToolSpec', right: 'ToolSpec') -> 'ToolSpec':
    """逐字段取更严格的那一份。

    用途：当一个工具有多份声明（工具自带 spec + 注册时补充的 spec），
    合并时不能取宽松的那个 —— 否则补充声明反而放开了权限。
    """
    # 逐字段取更严格的那一份（用显式分支而不是「and/or 短路」表达式 ——
    # 后者读起来像 bug，而且一旦有人把比较方向写反就静默放宽了权限）。
    if _EFFECT_ORDER[left.effect] >= _EFFECT_ORDER[right.effect]:
        effect = left.effect
    else:
        effect = right.effect
    if _SANDBOX_ORDER[left.sandbox] >= _SANDBOX_ORDER[right.sandbox]:
        sandbox = left.sandbox
    else:
        sandbox = right.sandbox
    if _NETWORK_ORDER[left.network] >= _NETWORK_ORDER[right.network]:
        network = left.network
    else:
        network = right.network
    return ToolSpec(
        name=left.name or right.name,
        version=left.version or right.version,
        summary=left.summary or right.summary,
        params_schema=left.params_schema or right.params_schema,
        effect=effect,
        scopes=tuple(sorted(set(left.scopes) | set(right.scopes))),
        sandbox=sandbox,
        network=network,
        destructive=left.destructive or right.destructive,
        owner=left.owner or right.owner,
        group=left.group or right.group,
    )


def sandbox_at_least(level: str, minimum: str) -> bool:
    """level 的隔离强度是否不低于 minimum。"""
    return _SANDBOX_ORDER.get(level, 0) >= _SANDBOX_ORDER.get(minimum, 0)


def effect_at_least(level: str, minimum: str) -> bool:
    """level 的副作用等级是否不低于 minimum。"""
    return _EFFECT_ORDER.get(level, 0) >= _EFFECT_ORDER.get(minimum, 0)


__all__ = [
    'ToolSpec',
    'Effect',
    'SandboxLevel',
    'NetworkLevel',
    'stricter_than',
    'sandbox_at_least',
    'effect_at_least',
]
