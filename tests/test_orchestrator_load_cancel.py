# tests/test_orchestrator_load_cancel.py
# 回归测试：模型加载被取消时，编排器必须以 unloaded 收尾而不是 failed。
#
# 现场（2026-10-12 06:41:54）：用户在加载途中点「终止」→ stop() 置空 _process →
# start() 的等待循环抛 AttributeError → load_model 走通用 except，广播
# status_failed 并向上抛 500。前端因此无法把模型行从 loading 收回，
# 表现为「模型已经加载完，界面还卡在加载中」。

from __future__ import annotations

import pytest

from harness.orchestrator import LlamaServerConfig, ModelOrchestrator
from harness.orchestrator.local_engine import LaunchCancelled


@pytest.fixture(autouse=True)
def clean_orchestrator():
    ModelOrchestrator.reset_instance()
    yield
    ModelOrchestrator.reset_instance()


@pytest.fixture()
def orch_with_model():
    orch = ModelOrchestrator.get_instance(max_concurrent_slots=1)
    cfg = LlamaServerConfig(
        binary_path="/mock/bin/llama-server",
        model_path="/mock/model.gguf",
        port=8099,
    )
    orch.register_local_llamacpp("m1", cfg, priority=80)
    return orch


def test_cancelled_load_reports_unloaded(orch_with_model):
    """取消不是失败：应广播 unloaded 且返回 False（不抛异常）。"""
    orch = orch_with_model
    events: list[tuple] = []
    orch.add_status_listener(lambda name, status, extra: events.append((name, status, extra)))

    spec = orch.get_model_spec("m1")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            spec.launcher,
            "start",
            lambda **kwargs: (_ for _ in ()).throw(LaunchCancelled("已取消")),
        )
        result = orch.load_model("m1")

    assert result is False, "取消后应返回 False，而不是抛异常"
    statuses = [s for (_, s, _) in events]
    assert "unloaded" in statuses, f"应广播 unloaded，实际 {statuses}"
    assert "failed" not in statuses, f"取消不应被当成失败，实际 {statuses}"

    # 加载标记必须清干净，否则 UI 会一直认为还有加载在进行
    assert "m1" not in orch._loading_models


def test_cancelled_load_does_not_raise(orch_with_model):
    """确保取消路径不会把异常冒泡成 HTTP 500。"""
    orch = orch_with_model
    spec = orch.get_model_spec("m1")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            spec.launcher,
            "start",
            lambda **kwargs: (_ for _ in ()).throw(LaunchCancelled("已取消")),
        )
        try:
            orch.load_model("m1")
        except Exception as e:  # noqa: BLE001 - 这里就是要断言不抛
            pytest.fail(f"取消加载不应抛异常，实际抛出 {type(e).__name__}: {e}")


def test_genuine_launch_failure_still_reports_failed(orch_with_model):
    """真正的启动失败仍须广播 failed 并向上抛（不能与取消混淆）。"""
    orch = orch_with_model
    events: list[tuple] = []
    orch.add_status_listener(lambda name, status, extra: events.append((name, status, extra)))

    spec = orch.get_model_spec("m1")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            spec.launcher,
            "start",
            lambda **kwargs: (_ for _ in ()).throw(RuntimeError("显存不足")),
        )
        with pytest.raises(RuntimeError):
            orch.load_model("m1")

    statuses = [s for (_, s, _) in events]
    assert "failed" in statuses, f"真实失败应广播 failed，实际 {statuses}"
    assert "unloaded" not in statuses
