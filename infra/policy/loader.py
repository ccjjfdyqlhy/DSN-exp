# infra/policy/loader.py
# 策略文件的加载器（策划案 §6.1 的 policies/ 目录：approval.yaml / network.yaml）。
#
# 策划案 §4.5.3 的「策略」要素：审批、网络、沙箱档位都写进 artifact 的
# spec.policies；但**规则本身**（谁放行、谁拒绝、按什么阈值自动放行）
# 应该是可独立评审、可独立下发的文件 —— 这就是 policies/*.yaml 的定位。
#
# 加载结果就是 RulePolicyEngine —— 不发明第二种策略格式：
#   rules:            与 PolicyRule 的字段一一对应
#   auto_approve_risk 风险阈值自动放行
#   allow_readonly    只读工具白名单
#
# fail-closed 原则在加载层面同样成立：字段写错 → 抛错，不静默忽略
# —— 一条被忽略的 deny 规则就是一次静默放权。

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .base import PolicyRule
from .engine import RulePolicyEngine

try:
    import yaml
except ImportError:  # pragma: no cover - 与仓库其它 yaml 消费点同策略
    yaml = None  # type: ignore[assignment]

#: PolicyRule 允许的字段（多写一个字 = 报错，不吞）
_RULE_FIELDS = ('action', 'id', 'tool', 'tool_prefix', 'effect', 'sandbox',
                'scopes', 'risk', 'reason')
#: 引擎级字段
_ENGINE_FIELDS = ('auto_approve_risk', 'allow_readonly',
                  'deny_unknown_tools', 'require_approval_effects')


class PolicyFileError(ValueError):
    """策略文件不合法。"""


def load_policy_file(path: str | Path) -> RulePolicyEngine:
    """从 yaml 加载策略引擎。文件不存在 → 报错（默认拒绝不等于默认不加载）。"""
    p = Path(path)
    if not p.exists():
        raise PolicyFileError(f'策略文件不存在: {p}')
    if yaml is None:
        raise PolicyFileError('PyYAML 未安装，无法解析策略文件')
    try:
        data = yaml.safe_load(p.read_text(encoding='utf-8')) or {}
    except yaml.YAMLError as error:
        raise PolicyFileError(f'策略文件不是合法 YAML: {error}') from error
    return policy_from_dict(data, where=str(p))


def policy_from_dict(data: Mapping[str, Any], *, where: str = '') -> RulePolicyEngine:
    if not isinstance(data, Mapping):
        raise PolicyFileError(f'{where}: 策略文件顶层必须是映射')
    rules_data = data.get('rules') or []
    if not isinstance(rules_data, list):
        raise PolicyFileError(f'{where}: rules 必须是列表')
    rules: list[PolicyRule] = []
    for i, item in enumerate(rules_data):
        if not isinstance(item, Mapping):
            raise PolicyFileError(f'{where}: rules[{i}] 必须是映射')
        unknown = set(item) - set(_RULE_FIELDS)
        if unknown:
            raise PolicyFileError(
                f'{where}: rules[{i}] 有未知字段 {sorted(unknown)}'
                f'（允许: {_RULE_FIELDS}）—— 拼错的字段等于丢失的规则')
        if str(item.get('action') or '') not in ('allow', 'deny'):
            raise PolicyFileError(
                f"{where}: rules[{i}].action 必须是 allow/deny")
        kwargs: dict[str, Any] = {}
        for field in _RULE_FIELDS:
            if field in item and item[field] not in (None, ''):
                kwargs[field] = item[field]
        if 'scopes' in kwargs and not isinstance(kwargs['scopes'], (list, tuple)):
            kwargs['scopes'] = (str(kwargs['scopes']),)
        else:
            kwargs['scopes'] = tuple(kwargs.get('scopes') or ())
        rules.append(PolicyRule(**kwargs))
    engine_kwargs: dict[str, Any] = {}
    for field in _ENGINE_FIELDS:
        if field in data and data[field] is not None:
            value = data[field]
            if field == 'require_approval_effects':
                value = tuple(value or ())
            engine_kwargs[field] = value
    return RulePolicyEngine(rules=rules, **engine_kwargs)


__all__ = ['PolicyFileError', 'load_policy_file', 'policy_from_dict']
