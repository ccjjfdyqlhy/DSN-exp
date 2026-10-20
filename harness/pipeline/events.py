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
        # 持有 fire-and-forget 任务的强引用，防止被 GC 提前回收（见 publish）。
        # 修复说明：原实现写成局部变量 \`_bus_tasks\`，而 publish() 里当作全局名引用，
        # 导致任何 async 订阅者在同步 publish 时都会抛 NameError 并被外层 except 吞掉 ——
        # 表现为「订阅了异步处理器但永远收不到事件」。必须是实例属性 self._bus_tasks。
        self._bus_tasks: set[asyncio.Task] = set()

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
                    except RuntimeError:
                        # 修复说明：原实现在无运行 loop 时降级为 asyncio.run()，
                        # 会**同步阻塞**调用方，且在嵌套 loop 场景直接抛错。
                        # 同步上下文里发布事件却订阅了 async 处理器属于调用方
                        # 用法错误，显式告警比静默丢弃/阻塞更容易定位。
                        logger.warning(
                            "事件 %s 的 async 处理器 %s 在无事件循环的同步上下文中发布，已跳过；"
                            "请改用 await bus.publish_async(...)",
                            event, getattr(handler, "__qualname__", handler),
                        )
                        continue
                    # 修复说明：原实现 ensure_future 后既不保存引用也不挂回调，
                    # 任务可能被 GC 提前回收，且处理器抛出的异常只会在解释器
                    # 退出时以 "Task exception was never retrieved" 的形式出现，
                    # 既不进 logger 也不反馈给调用方 —— 订阅者静默丢事件。
                    task = asyncio.ensure_future(handler(payload))
                    self._bus_tasks.add(task)
                    task.add_done_callback(self._bus_tasks.discard)
                    task.add_done_callback(
                        lambda t, _e=event: t.cancelled() or (
                            t.exception() and logger.exception(
                                "事件 %s 异步处理器异常", _e, exc_info=t.exception()
                            )
                        )
                    )
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
        self._bus_tasks.clear()

    def events(self) -> list[str]:
        return list(self._subs.keys())
