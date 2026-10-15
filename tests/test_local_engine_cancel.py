# tests/test_local_engine_cancel.py
# 回归测试：模型加载途中被「终止」，start() 必须干净退出而不是抛 AttributeError。
#
# 现场（2026-10-12 06:41:54）：
#   用户在 bonsai:bonsai2:27B 加载途中点了终止 → unload 线程调用 stop()，
#   把 launcher._process 置为 None；而 start() 的就绪等待循环仍在下一次迭代里
#   执行 self._process.poll() → AttributeError: 'NoneType' object has no
#   attribute 'poll'。该异常冒泡成 500，前端表现为「模型其实已经加载完，
#   界面却一直卡在加载中」。

from __future__ import annotations

import sys
import threading
import time

import pytest

from infra.orchestrator.local_engine import (
    LaunchCancelled,
    LocalServerLauncher,
)


class _SlowLauncher(LocalServerLauncher):
    """永远不就绪的假引擎：命令行是一个长睡眠进程。"""

    engine_label = "FakeEngine"
    ready_paths = ("/health",)

    @property
    def base_url(self) -> str:
        # 无人监听的端口 → is_ready() 立刻连接失败，循环会持续轮询
        return "http://127.0.0.1:45999"

    def build_command(self) -> list[str]:
        return [sys.executable, "-c", "import time; time.sleep(60)"]

    def preflight(self) -> None:
        return None


@pytest.fixture()
def launcher():
    inst = _SlowLauncher()
    yield inst
    inst.stop()


def test_stop_during_start_raises_launch_cancelled(launcher):
    """加载途中 stop()：start() 抛 LaunchCancelled，绝不抛 AttributeError。"""
    result: dict = {}

    def _run():
        try:
            launcher.start(wait_ready=True, timeout=30.0)
            result["outcome"] = "returned"
        except BaseException as e:  # noqa: BLE001 - 测试要拿到任何异常类型
            result["outcome"] = "raised"
            result["exc"] = e

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    # 等 start() 真正进入等待循环（进程已拉起）
    deadline = time.time() + 10
    while time.time() < deadline and not launcher.is_running():
        time.sleep(0.05)
    assert launcher.is_running(), "假引擎进程未能拉起"

    launcher.stop()
    t.join(timeout=10)

    assert result.get("outcome") == "raised", f"start() 应抛取消异常，实际 {result!r}"
    exc = result["exc"]
    assert isinstance(exc, LaunchCancelled), f"期望 LaunchCancelled，实际 {type(exc).__name__}: {exc}"
    assert not isinstance(exc, AttributeError)
    assert "poll" not in str(exc)


def test_cancel_requested_flag_and_reset(launcher):
    """cancel_requested 反映取消状态；下一次 start() 会重置它。"""
    assert launcher.cancel_requested is False

    launcher.stop()
    assert launcher.cancel_requested is True

    # 新的一轮启动必须清掉上一轮的取消信号，否则会被误判为已取消
    launcher._cancel_event.clear()
    assert launcher.cancel_requested is False


def test_start_after_cancel_is_not_poisoned(launcher):
    """取消过一次之后，新的 start() 不应被旧信号影响（能正常走到超时）。"""
    launcher.stop()  # 置位取消信号
    assert launcher.cancel_requested is True

    started = time.time()
    with pytest.raises(TimeoutError):
        # 就绪永远不满足 → 应走超时分支，而不是被上一轮的取消信号打断
        launcher.start(wait_ready=True, timeout=1.0)
    elapsed = time.time() - started

    assert elapsed >= 0.9, f"应在超时后才返回，实际 {elapsed:.2f}s"


def test_process_exit_still_reports_failure(launcher):
    """子进程自己退出仍按失败处理（不能与用户取消混为一谈）。"""

    class _ExitingLauncher(_SlowLauncher):
        def build_command(self) -> list[str]:
            return [sys.executable, "-c", "raise SystemExit(3)"]

    inst = _ExitingLauncher()
    with pytest.raises(RuntimeError) as ei:
        inst.start(wait_ready=True, timeout=15.0)

    assert "返回码" in str(ei.value)
    assert not isinstance(ei.value, LaunchCancelled)
    inst.stop()
