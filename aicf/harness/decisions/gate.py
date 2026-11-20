# harness/decisions/gate.py
# ToolGuard decision-gate adapter (W5.4): turns a DecisionService into the
# guard's optional pre-execution consult. The guard owns the slot and the
# refuse path; this adapter owns the mapping from a tool call to a yes/no
# decision request.

from __future__ import annotations

import json
from typing import Any

from .core import DecisionRequest


class DecisionToolGate:
    """System-1 gate for tool calls, wired into ToolGuard(decision_gate=...)."""

    def __init__(self, service: Any, *, question: str = ''):
        self._service = service
        self._question = question or ('The agent wants to run a tool. Decide '
                                      'whether that is appropriate right now.')

    def check(self, *, tool: str, args: dict | None = None,
              spec: Any = None) -> dict | None:
        result = self._service.decide(DecisionRequest(
            type='yes_no',
            state=f'tool={tool} args={json.dumps(args or {}, ensure_ascii=False)}',
            question=self._question,
        ))
        if getattr(result, 'type', '') != 'yes_no':
            return None  # not a yes/no verdict: the gate abstains
        allow = bool(result.answer)
        if allow:
            return None  # pass: the guard keeps its normal flow
        return {'allow': False,
                'reason': f'decision model refused {tool} '
                          f'(probability {result.probability:.2f})'}


__all__ = ['DecisionToolGate']
