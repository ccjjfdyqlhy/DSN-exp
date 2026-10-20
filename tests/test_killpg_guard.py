# tests/test_killpg_guard.py
# 回归测试：kill_process_tree() 绝不能把信号打到「调用者自己所在的进程组」。
#
# 现场（2026-10）：
#   infra/orchestrator/local_engine.py 的 kill_process_tree() 原先直接执行
#       os.killpg(os.getpgid(pid), signal.SIGTERM)
#   而 os.getpgid() 对**内核线程**返回 0（本机 PID 99 = kworker/R-blkcg）。
#   按 POSIX，killpg(0, sig) 等价于 kill(-0, sig) —— 给调用者自己所在的
#   进程组发信号，而不是给目标进程组发。
#
#   触发路径：tests/test_harness_strata.py 曾 mock proc.pid = 99，
#   atexit 的 _cleanup_active_launchers() → launcher.stop() →
#   kill_process_tree() → killpg(0, SIGTERM) → **pytest 进程被自己的
#   SIGTERM 打死**（exit 143），日志尾部只剩「已终止」，连外层 shell 进程组
#   一起带走；全量 pytest 更是在打印完统计后挂死，直到被 timeout 杀掉。
#
# 本文件锁住修复后的行为：
#   1. pgid 解析不出可信值时（0 / 与自己同组 / getpgid 抛错）→ 走 terminate；
#   2. 任何情况下都不会调用 os.killpg(0, ...)；
#   3. 正常场景（子进程独立进程组）仍然走 killpg，语义不回归。

from __future__ import annotations

import os
import signal
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from infra.orchestrator.local_engine import (
    _resolve_kill_pgid,
    kill_process_tree,
)


def _mock_proc(pid: int) -> MagicMock:
    """一个「还活着」的假进程：poll() 返回 None 表示尚未退出。"""
    proc = MagicMock()
    proc.pid = pid
    proc.poll.return_value = None
    return proc


# ── 1. pgid 解析的护栏 ──────────────────────────────────────────────

def test_resolve_pgid_rejects_zero():
    """pgid=0 表示「调用者自己的进程组」，必须判为不可信。"""
    with patch("os.getpgid", return_value=0):
        assert _resolve_kill_pgid(99) is None


def test_resolve_pgid_rejects_own_process_group():
    """目标与本进程同组时 killpg 会误伤自己，必须判为不可信。"""
    own = os.getpgid(0)
    with patch("os.getpgid", side_effect=lambda pid: own):
        assert _resolve_kill_pgid(12345) is None


def test_resolve_pgid_rejects_lookup_failure():
    """子进程已退出 / pid 非法 → getpgid 抛错 → 判为不可信。"""
    with patch("os.getpgid", side_effect=ProcessLookupError):
        assert _resolve_kill_pgid(4321) is None


def test_resolve_pgid_accepts_foreign_group():
    """正常场景：子进程在独立进程组里 → 照常返回该 pgid。"""
    own = os.getpgid(0)
    # pid=0 表示「查自己的进程组」，其余 pid 返回目标组的 pgid
    with patch("os.getpgid", side_effect=lambda pid: own if pid == 0 else 987654):
        assert _resolve_kill_pgid(4321) == 987654


# ── 2. kill_process_tree 绝不 killpg(0) ─────────────────────────────

@pytest.mark.parametrize("pgid_value", [0, -1])
def test_kill_process_tree_never_kills_own_group(pgid_value):
    """核心回归：pgid 解析为 0/负数时不得调用 killpg。"""
    proc = _mock_proc(99)
    with patch("os.getpgid", return_value=pgid_value), \
            patch("os.killpg") as mock_killpg:
        kill_process_tree(proc, timeout=0.5)

    mock_killpg.assert_not_called()
    assert proc.terminate.called, "不可信进程组时应退回 terminate()"


def test_kill_process_tree_falls_back_when_lookup_fails():
    """getpgid 抛错时退回 terminate()，且不调用 killpg。"""
    proc = _mock_proc(4321)
    with patch("os.getpgid", side_effect=ProcessLookupError), \
            patch("os.killpg") as mock_killpg:
        kill_process_tree(proc, timeout=0.5)

    mock_killpg.assert_not_called()
    assert proc.terminate.called


def test_kill_process_tree_does_not_signal_caller():
    """端到端：真起一个子进程，pgid 伪装成 0，调用方必须毫发无损。"""
    # 用「自己所在进程组」的真实 pgid 来触发误伤路径：
    # 若护栏失效，killpg 会把**本测试进程**一起 SIGTERM 掉。
    own_pgid = os.getpgid(0)
    proc = _mock_proc(4242)
    with patch("os.getpgid", side_effect=lambda pid: 0), \
            patch("os.killpg") as mock_killpg:
        kill_process_tree(proc, timeout=0.5)
    mock_killpg.assert_not_called()

    # 再验证「同组」这一条：pgid 解析成自己的组，也不能 killpg
    proc2 = _mock_proc(4243)
    with patch("os.getpgid", side_effect=lambda pid: own_pgid), \
            patch("os.killpg") as mock_killpg2:
        kill_process_tree(proc2, timeout=0.5)
    mock_killpg2.assert_not_called()


# ── 3. 正常路径不回归 ──────────────────────────────────────────────

@pytest.mark.skipif(not hasattr(os, "setsid"), reason="需要 POSIX setsid")
def test_kill_process_tree_still_kills_whole_group():
    """子进程在独立进程组时，仍然走 killpg 整组回收（语义不回归）。"""
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        preexec_fn=os.setsid,
    )
    try:
        assert _resolve_kill_pgid(proc.pid) == os.getpgid(proc.pid)
        kill_process_tree(proc, timeout=5.0)
        # SIGTERM 结束 → returncode 为 -15
        assert proc.poll() == -signal.SIGTERM
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5.0)
