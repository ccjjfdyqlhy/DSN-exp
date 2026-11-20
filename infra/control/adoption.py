# infra/control/adoption.py
# Managed 与 BYO 的统一纳管（策划案 §4.5.4 / rc1 C4）。
#
# ── 统一纳管的关键是**协议**而非实现 ──
# BYO（Bring Your Own）的进程只要能：
#   1. 按 RuntimeClient 协议上报事件（emit / record_tool_intent / …），
#   2. 按策略接受工具准入（本地强制或中心下发），
# 平台就能对它做发布、评测与成本归因。它自己用什么框架、跑在哪个进程，
# 平台不关心。
#
# 这里做三件事：
#   AdoptionRecord   一条接入登记（谁、什么模式、什么能力）
#   ByoRegistry      接入登记表（不持久化 —— 接入是运行时事实）
#   RuntimeClientView 把外部进程的「能上报」面校验并收敛成 RuntimeClient 协议
#
# 刻意**不做**：网络传输、心跳保活、权限下发 —— 那是部署形态的事，
# 策划案把 BYO 的范围钉死在「协议接入」这一层。

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger('infra.control.adoption')

#: RuntimeClient 协议要求的方法（策划案 §5.3；harness/runtime_client.py 同形）
RUNTIME_CLIENT_METHODS: tuple[str, ...] = (
    'emit',
    'record_tool_intent',
    'record_tool_result',
    'lookup_tool_result',
    'idempotency_key',
    'checkpoint',
)


class AdoptionError(RuntimeError):
    """外部进程不能按 RuntimeClient 协议接入。"""


@dataclass
class AdoptionRecord:
    """一条 BYO 接入登记。"""

    id: str
    agent_id: str
    mode: str = 'byo'                      # managed | byo
    capabilities: tuple[str, ...] = ()     # 声明自己能上报什么
    endpoint: str = ''                     # 描述性（进程标识 / 地址），平台不主动连
    adopted_at: float = 0.0
    labels: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'agent_id': self.agent_id,
            'mode': self.mode,
            'capabilities': list(self.capabilities),
            'endpoint': self.endpoint,
            'adopted_at': self.adopted_at,
            'labels': dict(self.labels),
        }


class RuntimeClientView:
    """把外部进程收敛成 RuntimeClient 协议的视图。

    构造时校验宿主真的有协议要求的方法 —— 缺一个就拒绝接入。
    事件在转发给宿主的同时**镜像**给平台侧的观察者（telemetry / ledger），
    这样评测与成本归因对 BYO 进程与 Managed 进程一视同仁。
    """

    def __init__(self, host: Any, *,
                 record: AdoptionRecord,
                 mirror: Any = None) -> None:
        missing = [m for m in RUNTIME_CLIENT_METHODS
                   if not callable(getattr(host, m, None))]
        if missing:
            raise AdoptionError(
                f'BYO 进程 {record.agent_id} 缺少 RuntimeClient 协议方法: '
                f'{missing}（策划案 §4.5.4：能上报才能纳管）')
        self._host = host
        self.record = record
        self._mirror = mirror

    def _mirrored(self, method: str, payload: Any) -> None:
        if self._mirror is None:
            return
        try:
            mirror_method = getattr(self._mirror, method, None)
            if callable(mirror_method):
                mirror_method(payload)
        except Exception:
            # 镜像失败不阻断宿主：纳管的目的是观察，不是拦截。但也不能静默
            # —— 丢了镜像意味着评测与成本归因少了数据，必须留痕。
            logger.exception('BYO 事件镜像失败 agent=%s method=%s',
                             self.record.agent_id, method)

    # ── 协议转发（事件镜像给平台）────────────────────────
    def emit(self, kind: str, payload: dict) -> None:
        self._host.emit(kind, payload)
        self._mirrored('emit', {'kind': kind, 'payload': dict(payload or {}),
                                'agent_id': self.record.agent_id})

    def record_tool_intent(self, intent: Any) -> None:
        self._host.record_tool_intent(intent)
        self._mirrored('record_tool_intent', intent)

    def record_tool_result(self, idempotency_key: str, result: Any, *,
                           effect: str = 'pure') -> None:
        self._host.record_tool_result(idempotency_key, result, effect=effect)
        self._mirrored('record_tool_result',
                       {'idempotency_key': idempotency_key,
                        'effect': effect,
                        'agent_id': self.record.agent_id})

    def lookup_tool_result(self, idempotency_key: str) -> Any | None:
        return self._host.lookup_tool_result(idempotency_key)

    def idempotency_key(self, session_id: str, turn_seq: int, tool: str,
                        args: Any = None) -> str:
        return self._host.idempotency_key(session_id, turn_seq, tool, args)

    def checkpoint(self, state: dict) -> str | None:
        return self._host.checkpoint(state)


class ByoRegistry:
    """BYO 接入登记表。"""

    def __init__(self, *, mirror: Any = None) -> None:
        self._records: dict[str, AdoptionRecord] = {}
        self._views: dict[str, RuntimeClientView] = {}
        self._mirror = mirror

    def adopt(self, agent_id: str, host: Any, *,
              capabilities: Iterable[str] = (),
              endpoint: str = '',
              labels: Mapping[str, Any] | None = None) -> RuntimeClientView:
        """接入一个外部进程：校验协议 → 登记 → 返回纳管视图。"""
        if not str(agent_id or '').strip():
            raise AdoptionError('BYO 接入必须给出 agent_id')
        record = AdoptionRecord(
            id=f'adopt_{uuid.uuid4().hex[:12]}',
            agent_id=str(agent_id),
            mode='byo',
            capabilities=tuple(capabilities or ()),
            endpoint=endpoint,
            adopted_at=time.time(),
            labels=dict(labels or {}),
        )
        view = RuntimeClientView(host, record=record, mirror=self._mirror)
        self._records[record.agent_id] = record
        self._views[record.agent_id] = view
        return view

    def get(self, agent_id: str) -> RuntimeClientView | None:
        return self._views.get(agent_id)

    def record_of(self, agent_id: str) -> AdoptionRecord | None:
        return self._records.get(agent_id)

    def agents(self) -> list[AdoptionRecord]:
        return [self._records[k] for k in sorted(self._records)]

    def release(self, agent_id: str) -> bool:
        """解除纳管（进程下线）。"""
        return self._views.pop(agent_id, None) is not None


__all__ = [
    'RUNTIME_CLIENT_METHODS',
    'AdoptionError',
    'AdoptionRecord',
    'ByoRegistry',
    'RuntimeClientView',
]
