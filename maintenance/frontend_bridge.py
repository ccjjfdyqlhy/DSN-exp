# maintenance/frontend_bridge.py
# SSE 前端通信桥 — 维护事件通过此模块推送到前端

from __future__ import annotations

import json
import logging
import queue
import threading
from typing import Any

logger = logging.getLogger("maintenance.bridge")

_sse_queues: list[queue.Queue] = []
_lock = threading.Lock()


def broadcast(event: str, data: dict[str, Any]) -> None:
    """向所有已连接的 SSE 客户端推送事件"""
    payload = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    with _lock:
        for q in _sse_queues:
            try:
                q.put_nowait(payload)
            except queue.Full:
                pass


def subscribe() -> queue.Queue:
    """订阅 SSE 事件流，返回一个 Queue"""
    q: queue.Queue = queue.Queue(maxsize=500)
    with _lock:
        _sse_queues.append(q)
    return q


def unsubscribe(q: queue.Queue) -> None:
    """取消订阅"""
    with _lock:
        if q in _sse_queues:
            _sse_queues.remove(q)
