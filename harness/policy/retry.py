# harness/policy/retry.py
# RetryPolicy — 调用重试/退避/限流/熔断策略（场景无关）。
#
# 对齐 DSH 的 dsh-llm-retry（重试策略）与限流能力，引擎化为一等公民策略：
#   - 指数退避 + 抖动：避免重试风暴
#   - 可重试错误分类：网络/超时/429/5xx 可重试；4xx 客户端错误直接失败
#   - 熔断：连续失败达阈值后短路（open），冷却后半开探测
#   - 限流：令牌桶（每秒速率），超限排队等待
#
# 用法:
#     policy = RetryPolicy(max_retries=3, base_delay=1.0, rate_per_sec=5.0,
#                          circuit_break_after=5)
#     result = await policy.call(chat.invoke, messages, tools=tools)
#     # 或同步: policy.call_sync(chat.invoke, ...)

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger("harness.policy.retry")

# 可重试的 HTTP 状态码
RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}


@dataclass
class RetryStats:
    attempts: int = 0
    retries: int = 0
    failures: int = 0
    successes: int = 0
    circuit_open: bool = False
    last_error: str = ""
    history: list[tuple[float, str]] = field(default_factory=list)  # (ts, event)


class RetryPolicy:
    """指数退避 + 抖动 + 熔断 + 限流。

    参数:
        max_retries        最大重试次数（默认 3）
        base_delay         退避基数秒（默认 1.0）
        max_delay          退避上限秒（默认 30.0）
        jitter             抖动比例 0..1（默认 0.3）
        rate_per_sec       限流速率（每秒调用数；0 = 不限流）
        circuit_break_after  连续失败熔断阈值（0 = 不熔断）
        circuit_cooldown   熔断冷却秒（默认 30）
        retryable_statuses 可重试状态码集合
    """

    def __init__(
        self,
        *,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        jitter: float = 0.3,
        rate_per_sec: float = 0.0,
        circuit_break_after: int = 0,
        circuit_cooldown: float = 30.0,
        retryable_statuses: Optional[set] = None,
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self.rate_per_sec = rate_per_sec
        self.circuit_break_after = circuit_break_after
        self.circuit_cooldown = circuit_cooldown
        self.retryable_statuses = retryable_statuses or RETRYABLE_STATUS
        self.stats = RetryStats()
        # 熔断状态
        self._consecutive_failures = 0
        self._circuit_until = 0.0
        # 限流令牌桶
        self._tokens = 0.0
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    # ── 熔断 ──

    def _circuit_open(self) -> bool:
        if self._circuit_until > time.monotonic():
            return True
        return False

    def _record_failure(self, error: str) -> None:
        self._consecutive_failures += 1
        if (self.circuit_break_after and
                self._consecutive_failures >= self.circuit_break_after):
            self._circuit_until = time.monotonic() + self.circuit_cooldown
            self.stats.circuit_open = True
            logger.warning("熔断开启: 连续 %d 次失败, 冷却 %ds",
                           self._consecutive_failures, self.circuit_cooldown)

    def _record_success(self) -> None:
        self._consecutive_failures = 0
        self._circuit_until = 0.0
        self.stats.circuit_open = False

    # ── 限流 ──

    async def _acquire_token(self) -> None:
        if self.rate_per_sec <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            self._tokens = min(self.rate_per_sec,
                               self._tokens + (now - self._last_refill) * self.rate_per_sec)
            self._last_refill = now
            while self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self.rate_per_sec
                await asyncio.sleep(wait)
                now = time.monotonic()
                self._tokens = min(self.rate_per_sec,
                                   self._tokens + (now - self._last_refill) * self.rate_per_sec)
                self._last_refill = now
            self._tokens -= 1.0

    # ── 错误分类 ──

    @staticmethod
    def _is_retryable(error: Exception, retryable_statuses: set) -> bool:
        """网络/超时/429/5xx 可重试；4xx 客户端错误不可重试。"""
        status = getattr(error, "status_code", None)
        if status is None:
            status = getattr(error, "code", None)
        if status is not None:
            return int(status) in retryable_statuses
        import socket
        if isinstance(error, (ConnectionError, socket.timeout, TimeoutError)):
            return True
        # openai 风格 APIError
        for cls_name in ("APIConnectionError", "APITimeoutError", "RateLimitError",
                         "InternalServerError"):
            if type(error).__name__ == cls_name:
                return True
        return False

    # ── 调用 ──

    async def call(self, fn: Callable[..., Awaitable[Any]], *args,
                   **kwargs) -> Any:
        """异步调用：限流 → 熔断检查 → 重试循环。"""
        self.stats.attempts += 1
        if self._circuit_open():
            raise RuntimeError("熔断开启，调用被短路")
        await self._acquire_token()

        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                result = await fn(*args, **kwargs)
                self._record_success()
                self.stats.successes += 1
                self.stats.history.append((time.time(), "ok"))
                return result
            except Exception as e:
                last_error = e
                self.stats.failures += 1
                self._record_failure(str(e))
                if attempt >= self.max_retries or not self._is_retryable(e, self.retryable_statuses):
                    break
                delay = min(self.max_delay, self.base_delay * (2 ** attempt))
                if self.jitter > 0:
                    delay *= 1.0 + random.uniform(-self.jitter, self.jitter)
                self.stats.retries += 1
                self.stats.history.append((time.time(), f"retry:{type(e).__name__}"))
                logger.debug("重试 %d/%d 在 %.1fs 后 (%s)", attempt + 1,
                             self.max_retries, delay, type(e).__name__)
                await asyncio.sleep(max(0.0, delay))
        assert last_error is not None
        raise last_error

    def call_sync(self, fn: Callable[..., Any], *args, **kwargs) -> Any:
        """同步便捷入口。"""
        return asyncio.run(self.call(
            lambda *a, **kw: asyncio.to_thread(fn, *a, **kw), *args, **kwargs))

    def __repr__(self) -> str:
        return (f"<RetryPolicy retries={self.stats.retries} "
                f"failures={self.stats.failures} "
                f"circuit={'OPEN' if self.stats.circuit_open else 'closed'}>")
