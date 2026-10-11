# tests/test_dsn_ui_resources_perf.py
# 回归测试：/api/system/resources 的采集必须是「快 + 可缓存 + 不阻塞事件循环」。
#
# 现场问题：硬件页每 2s 轮询该端点，处理函数里直接执行
#   * psutil.cpu_percent(interval=0.1)  → 硬睡 100ms
#   * subprocess.run(["nvidia-smi"])    → 每次 fork/exec 一个新进程
# 二者都在 asyncio 事件循环上同步执行，于是每 2 秒把整个服务冻结上百毫秒，
# 连带拖慢 /v1/streams/lookup（打开会话）、/models（模型列表）与 SSE 推送。

from __future__ import annotations

import time
from unittest.mock import patch

import apps.dsn_ui.server as server


def test_get_system_resources_does_not_sleep():
    """采集不得包含 100ms 级别的固定睡眠。"""
    with patch.object(server, "_query_gpus", return_value=[]):
        start = time.monotonic()
        server.get_system_resources()
        elapsed = time.monotonic() - start

    # 原实现 cpu_percent(interval=0.1) 必然 >= 0.1s
    assert elapsed < 0.05, f"采集耗时 {elapsed:.3f}s，疑似仍在阻塞采样"


def test_gpu_query_is_cached_within_ttl():
    """同一 TTL 窗口内 nvidia-smi 只应执行一次。"""
    server._gpu_cache = None

    fake = type("R", (), {"returncode": 0, "stdout": "0, NVIDIA Test, 1000, 500, 500, 40, 10\n"})()

    with patch.object(server.shutil, "which", return_value="/usr/bin/nvidia-smi"), patch.object(
        server.subprocess, "run", return_value=fake
    ) as mock_run:
        first = server._query_gpus()
        second = server._query_gpus()
        third = server._query_gpus()

    assert mock_run.call_count == 1
    assert first == second == third
    assert first[0]["name"] == "NVIDIA Test"
    assert first[0]["percent"] == 50.0

    server._gpu_cache = None


def test_gpu_cache_expires(monkeypatch):
    """TTL 过期后应重新采样，保证显存数字会更新。"""
    server._gpu_cache = None
    monkeypatch.setattr(server, "_GPU_CACHE_TTL_S", 0.0)

    fake = type("R", (), {"returncode": 0, "stdout": "0, NVIDIA Test, 1000, 500, 500, 40, 10\n"})()

    with patch.object(server.shutil, "which", return_value="/usr/bin/nvidia-smi"), patch.object(
        server.subprocess, "run", return_value=fake
    ) as mock_run:
        server._query_gpus()
        server._query_gpus()

    assert mock_run.call_count == 2

    server._gpu_cache = None


def test_gpu_failure_is_tolerated_and_cached():
    """nvidia-smi 失败不应抛错，且失败结果同样进缓存（避免每轮都重试）。"""
    server._gpu_cache = None

    with patch.object(server.shutil, "which", return_value="/usr/bin/nvidia-smi"), patch.object(
        server.subprocess, "run", side_effect=OSError("boom")
    ) as mock_run:
        assert server._query_gpus() == []
        assert server._query_gpus() == []

    assert mock_run.call_count == 1

    server._gpu_cache = None
