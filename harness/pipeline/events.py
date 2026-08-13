# harness/pipeline/events.py
# EventBus — 通用发布/订阅事件总线。
#
# 用于替代"管线硬编码事件"（如叙事旁白、进度、通知），
# 让应用 bundle 通过订阅而非侵入管线核心来接收事件。

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

logger = logging.getLogger("harness.events")


class EventBus:
    """同步/异步订阅者混合的事件总线。"""

    def __init__(self):
        self._subs: dict[str, list[Callable[..., Any]]] = {}

    def subscribe(self, event: str, handler: Callable[..., Any]) -> Callable[[], None]:
        """订阅事件，返回取消订阅函数。handler 可为 sync 或 async。"""
        self._subs.setdefault(event, []).append(handler)

        def unsubscribe() -> None:
            handlers = self._subs.get(event)
            if handlers and handler in handlers:
                handlers.remove(handler)

        return unsubscribe

    def on(self, event: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """装饰器形式订阅。"""
        def decorator(handler: Callable[..., Any]) -> Callable[..., Any]:
            self.subscribe(event, handler)
            return handler
        return decorator

    def publish(self, event: str, payload: Any = None) -> None:
        """同步发布：async handler 会被调度到事件循环。"""
        for handler in list(self._subs.get(event, [])):
            try:
                if asyncio.iscoroutinefunction(handler):
                    try:
                        asyncio.get_running_loop()
                        asyncio.ensure_future(handler(payload))
                    except RuntimeError:
                        asyncio.run(handler(payload))
                else:
                    handler(payload)
            except Exception:
                logger.exception("事件 %s 处理器异常", event)

    async def publish_async(self, event: str, payload: Any = None) -> None:
        """异步发布：async handler 被 await。"""
        for handler in list(self._subs.get(event, [])):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(payload)
                else:
                    handler(payload)
            except Exception:
                logger.exception("事件 %s 处理器异常", event)

    def clear(self) -> None:
        self._subs.clear()

    def events(self) -> list[str]:
        return list(self._subs.keys())
