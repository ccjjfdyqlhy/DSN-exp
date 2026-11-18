# harness/approval/events.py
# 审批相关的事件构造。
#
# 单独一个模块的理由：事件的**载荷形状**要在一处定义，否则调用方各写各的，
# 消费方（审计、trace、评测）就得兼容好几种形状。策划案 §5.2 的词表里
# approval_request / approval_decision / approval_timeout 三种事件都归这里。

from __future__ import annotations

from typing import Any

from .base import ApprovalDecision, ApprovalRequest


def approval_request_event(request: ApprovalRequest) -> dict[str, Any]:
    """构造 approval_request 载荷。"""
    return {
        'id': request.id,
        'tool': request.tool,
        'args_preview': request.args_preview,
        'effect': request.effect,
        'risk': request.risk,
        'expires_at': request.expires_at,
        'session_id': request.session_id,
        'turn_id': request.turn_id,
        'destructive': request.destructive,
        'scopes_required': list(request.scopes_required),
        'detail': request.detail,
    }


def approval_decision_event(request_id: str, tool: str,
                            decision: ApprovalDecision) -> dict[str, Any]:
    """构造 approval_decision 载荷。"""
    return {
        'id': request_id,
        'tool': tool,
        'decision': decision.decision,
        'decided_by': decision.decided_by,
        'reason': decision.reason,
        'scope': decision.scope or '',
    }


def approval_timeout_event(request_id: str, tool: str) -> dict[str, Any]:
    """构造 approval_timeout 载荷。

    超时是**独立事件**而不是一条 deny —— 审计要能区分「人拒绝了」和
    「没人理」。这两种情况在事故复盘时的含义完全不同。
    """
    return {'id': request_id, 'tool': tool}


__all__ = [
    'approval_request_event',
    'approval_decision_event',
    'approval_timeout_event',
]
