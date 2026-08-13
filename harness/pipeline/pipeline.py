# harness/pipeline/pipeline.py
# Pipeline — 通用管线编排器。
#
# 编排顺序: INBOUND → PREPARE → MODEL_INVOKE → POST_PROCESS → OUTPUT
# - 各阶段交由 PluginManager 调度插件
# - 阶段结束后把 ctx.emit() 记录的事件交给 EventBus 广播
# - MODEL_INVOKE / OUTPUT 的具体实现由插件（如模型插件、渲染插件）承担

from __future__ import annotations

import logging
import time
from typing import AsyncGenerator, Optional

from .base import HookPoint, Context
from .manager import PluginManager
from .events import EventBus

logger = logging.getLogger("harness.pipeline")


class Pipeline:
    """通用消息管线。"""

    _HOOK_ORDER = [
        HookPoint.INBOUND,
        HookPoint.PREPARE,
        HookPoint.MODEL_INVOKE,
        HookPoint.POST_PROCESS,
        HookPoint.OUTPUT,
    ]

    def __init__(
        self,
        plugin_manager: PluginManager,
        event_bus: Optional[EventBus] = None,
    ):
        self.pm = plugin_manager
        self.events = event_bus or EventBus()

    def _drain_events(self, ctx: Context) -> None:
        pending = ctx.extra.pop("_events", [])
        for event, payload in pending:
            self.events.publish(event, payload)

    async def process(self, ctx: Context) -> Context:
        timing: dict[str, float] = {}
        t_total = time.perf_counter()

        for hook in self._HOOK_ORDER:
            t0 = time.perf_counter()
            ctx = await self.pm.dispatch(hook, ctx)
            timing[hook.value] = round((time.perf_counter() - t0) * 1000, 1)
            self._drain_events(ctx)
            if ctx.filtered:
                break

        timing["total_ms"] = round((time.perf_counter() - t_total) * 1000, 1)
        ctx.extra["_pipeline_timing"] = timing
        return ctx

    async def process_stream(
        self, ctx: Context,
    ) -> AsyncGenerator[dict, None]:
        """带阶段事件推送的流式处理。每个阶段前后 yield 状态。"""
        for hook in self._HOOK_ORDER:
            yield {"status": hook.value, "phase": "start"}
            ctx = await self.pm.dispatch(hook, ctx)
            self._drain_events(ctx)
            yield {"status": hook.value, "phase": "end", "filtered": ctx.filtered}
            if ctx.filtered:
                break
        yield {"status": "completed", "reply": ctx.reply}
