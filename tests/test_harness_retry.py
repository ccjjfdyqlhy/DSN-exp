# tests/test_harness_retry.py
# RetryPolicy（harness/policy/retry.py）单元测试：重试/退避/熔断/限流。

from __future__ import annotations

import asyncio

import pytest

from harness.policy import RetryPolicy


class FlakyError(Exception):
    status_code = 503  # 可重试


class ClientError(Exception):
    status_code = 400  # 不可重试


def test_retry_succeeds_after_transient_failures():
    calls = {"n": 0}

    async def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise FlakyError("temporary")
        return "ok"

    p = RetryPolicy(max_retries=3, base_delay=0.01, jitter=0)
    result = asyncio.run(p.call(flaky))
    assert result == "ok"
    assert calls["n"] == 3
    assert p.stats.retries == 2
    assert p.stats.successes == 1


def test_retry_gives_up_after_max():
    async def always_fail(*a, **kw):
        raise FlakyError("boom")

    p = RetryPolicy(max_retries=2, base_delay=0.01, jitter=0)
    with pytest.raises(FlakyError):
        asyncio.run(p.call(always_fail))
    assert p.stats.failures == 3  # 1 + 2 次重试
    assert p.stats.retries == 2


def test_non_retryable_error_immediate():
    async def bad(*a, **kw):
        raise ClientError("bad request")

    p = RetryPolicy(max_retries=3, base_delay=0.01, jitter=0)
    with pytest.raises(ClientError):
        asyncio.run(p.call(bad))
    assert p.stats.retries == 0  # 4xx 不重试


def test_circuit_breaker_opens():
    async def always_fail(*a, **kw):
        raise FlakyError("boom")

    p = RetryPolicy(max_retries=0, circuit_break_after=2, circuit_cooldown=60)
    for _ in range(2):
        with pytest.raises(FlakyError):
            asyncio.run(p.call(always_fail))
    # 熔断开启 → 直接短路（不再调用 fn）
    calls = {"n": 0}

    async def counted(*a, **kw):
        calls["n"] += 1
        raise FlakyError("x")

    p2 = RetryPolicy(max_retries=0, circuit_break_after=2, circuit_cooldown=60)
    for _ in range(2):
        with pytest.raises(FlakyError):
            asyncio.run(p2.call(counted))
    with pytest.raises(RuntimeError, match="熔断"):
        asyncio.run(p2.call(counted))
    assert calls["n"] == 2  # 第三次未调用 fn
    assert p2.stats.circuit_open


def test_rate_limit_throttles():
    timestamps = []

    async def slow(*a, **kw):
        timestamps.append(asyncio.get_event_loop().time())
        return "ok"

    p = RetryPolicy(max_retries=0, rate_per_sec=5.0)  # 每秒 5 次
    for _ in range(10):
        asyncio.run(p.call(slow))
    # 10 次调用在 5/s 限流下至少需要约 1.8s（9 个间隔 * 0.2s）
    spans = [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)]
    assert sum(spans) >= 1.5
