# harness/policy/warmer.py
# CacheWarmer — 前缀缓存保活策略（场景无关）。
#
# 从 dekacode cache_warmer.py 提炼并引擎化：
#   - 空闲期周期性发送 1-token keepalive，保持服务端 prefix cache 活跃
#   - 与 IChatClient 解耦：注入任何实现 invoke 的对象即可
#   - 失败静默（不影响主流程）

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

logger = logging.getLogger("harness.policy.warmer")

KEEPALIVE_INTERVAL = 30.0


class CacheWarmer:
    """空闲 keepalive 循环。

    用法:
        warmer = CacheWarmer(client, request_builder=lambda: msgs)
        warmer.start()   # 后台任务
        warmer.stop()
    """

    def __init__(
        self,
        client: Any,
        request_builder: Optional[Callable[[], list]] = None,
        *,
        interval: float = KEEPALIVE_INTERVAL,
        max_tokens: int = 1,
        temperature: float = 0.0,
    ):
        self._client = client
        self._builder = request_builder
        self._interval = interval
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._task: Optional[asyncio.Task] = None
        self._keepalives: int = 0

    def set_request_builder(self, builder: Callable[[], list]) -> None:
        """设置 keepalive 请求构建器（返回消息列表）。"""
        self._builder = builder

    @property
    def keepalives(self) -> int:
        return self._keepalives

    def start(self) -> None:
        if self._task is not None or self._builder is None:
            return
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                if self._builder is not None:
                    msgs = self._builder()
                    if msgs:
                        invoke = getattr(self._client, "invoke", None)
                        if invoke is not None:
                            if asyncio.iscoroutinefunction(invoke):
                                await invoke(msgs, max_tokens=self._max_tokens,
                                             temperature=self._temperature)
                            else:
                                invoke(msgs, max_tokens=self._max_tokens,
                                       temperature=self._temperature)
                            self._keepalives += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug("keepalive 失败（静默）")
            await asyncio.sleep(self._interval)

    def __repr__(self) -> str:
        return (f"<CacheWarmer running={self._task is not None} "
                f"keepalives={self._keepalives} interval={self._interval}s>")
