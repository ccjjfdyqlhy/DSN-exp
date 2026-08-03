# maintenance/state.py
# 服务器三态定义 + 状态机

from __future__ import annotations

import logging
from enum import Enum
from typing import Callable

logger = logging.getLogger("maintenance.state")


class ServerState(Enum):
    READY = "ready"
    MAINTENANCE = "maint"
    STANDBY = "standby"


class StateTransitionError(RuntimeError):
    pass


_StateListener = Callable[[ServerState, ServerState], None]


class ServerStateMachine:
    """
    三态机，控制服务器状态转换。

    ┌──────────┐     无请求持续 1h     ┌──────────┐
    │  待命    │ ──────────────────→  │  待机    │
    │ (ready)  │                      │ (standby)│
    └────┬─────┘                      └────┬─────┘
         │                                │
         │ 预定维护时间到                  │ 用户请求 / 预定维护时间到
         ↓                                ↓
    ┌──────────┐     维护完成/重启     ┌──────────┐
    │  整理    │ ──────────────────→  │  待命    │
    │ (maint)  │                      │ (ready)  │
    └──────────┘                      └──────────┘

    待机状态下定时检修（如 /hibernate archive every 5m）仍应能进入维护，
    避免服务器空闲后周期性检修停止。
    """

    _ALLOWED_TRANSITIONS = {
        ServerState.READY: {ServerState.MAINTENANCE, ServerState.STANDBY},
        ServerState.MAINTENANCE: {ServerState.READY},
        ServerState.STANDBY: {ServerState.READY, ServerState.MAINTENANCE},
    }

    def __init__(self):
        self._state = ServerState.READY
        self._listeners: list[_StateListener] = []

    @property
    def state(self) -> ServerState:
        return self._state

    def transition(self, target: ServerState) -> bool:
        allowed = self._ALLOWED_TRANSITIONS.get(self._state, set())
        if target not in allowed:
            logger.warning("非法状态转换: %s → %s", self._state.value, target.value)
            return False
        old = self._state
        self._state = target
        logger.info("状态转换: %s → %s", old.value, target.value)
        for cb in self._listeners:
            try:
                cb(old, target)
            except Exception:
                logger.exception("状态转换回调异常")
        return True

    def on_transition(self, callback: _StateListener) -> None:
        self._listeners.append(callback)
