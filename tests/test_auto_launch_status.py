# tests/test_auto_launch_status.py
# 回归测试：请求时「自动拉起」本地引擎必须同步状态。
#
# 现场问题：没有加载模型时重试之前发过的消息，后端会自行把上次用过的模型
# 拉起来（OpenAICompatChat._ensure_launcher_running），但这条路不经过
# ModelOrchestrator.load_model()：
#   * 不广播 status_loading / status_loaded → 前端不切换加载状态；
#   * 不调用 scheduler.mark_preloaded() → /models 与 /api/system/resources
#     仍报告"未加载"，显存调度页和模型列表里看不到可用模型。
# 于是模型明明已经在跑，界面上却像什么都没发生。

from __future__ import annotations

import pytest

from infra.orchestrator import LlamaServerConfig, ModelOrchestrator
from infra.orchestrator.local_chat import OpenAICompatChat


class _FakeLauncher:
    """可控的假 launcher：先不就绪，start() 后变就绪且进程存活。"""

    def __init__(self):
        self.ready = False
        self.started = 0
        self.running = False

    def is_ready(self, timeout: float = 2.0) -> bool:
        return self.ready

    def is_running(self) -> bool:
        # status() 会用真实进程存活状态做自愈校正，假 launcher 必须一起模拟
        return self.running

    def start(self, wait_ready: bool = True, timeout: float = 180.0, **kwargs) -> bool:
        self.started += 1
        self.ready = True
        self.running = True
        return True


def test_client_reports_loading_then_loaded():
    """客户端自拉起时按顺序上报 loading → loaded。"""
    launcher = _FakeLauncher()
    events: list[tuple] = []

    client = OpenAICompatChat(
        base_url="http://127.0.0.1:9",
        model_name="m",
        launcher=launcher,
        on_status=lambda status, **extra: events.append((status, extra)),
    )

    client._ensure_launcher_running()

    assert [e[0] for e in events] == ["loading", "loaded"], f"实际 {events!r}"
    assert launcher.started == 1


def test_client_reports_failure():
    """拉起失败要上报 failed，不能静默。"""
    class _BoomLauncher(_FakeLauncher):
        def start(self, wait_ready=True, timeout=180.0, **kwargs):
            raise RuntimeError("显存不足")

    events: list[str] = []
    client = OpenAICompatChat(
        base_url="http://127.0.0.1:9",
        model_name="m",
        launcher=_BoomLauncher(),
        on_status=lambda status, **extra: events.append(status),
    )

    with pytest.raises(RuntimeError):
        client._ensure_launcher_running()

    assert events == ["loading", "failed"], f"实际 {events!r}"


def test_client_no_op_when_already_ready():
    """已就绪时不应重复上报（否则每次请求都刷一条状态）。"""
    launcher = _FakeLauncher()
    launcher.ready = True
    events: list[str] = []

    client = OpenAICompatChat(
        base_url="http://127.0.0.1:9",
        model_name="m",
        launcher=launcher,
        on_status=lambda status, **extra: events.append(status),
    )

    client._ensure_launcher_running()

    assert events == []
    assert launcher.started == 0


@pytest.fixture(autouse=True)
def clean_orchestrator():
    ModelOrchestrator.reset_instance()
    yield
    ModelOrchestrator.reset_instance()


def test_orchestrator_syncs_status_on_auto_launch():
    """端到端：自动拉起后，调度器与状态监听者都必须被更新。"""
    orch = ModelOrchestrator.get_instance(max_concurrent_slots=2)
    cfg = LlamaServerConfig(
        binary_path="/mock/bin/llama-server",
        model_path="/mock/model.gguf",
        port=8099,
    )
    orch.register_local_llamacpp("m1", cfg, priority=80)

    seen: list[tuple] = []
    orch.add_status_listener(lambda name, status, extra: seen.append((name, status)))

    spec = orch.get_model_spec("m1")
    fake = _FakeLauncher()
    launcher = spec.client_instance._launcher  # type: ignore[attr-defined]
    launcher.is_ready = fake.is_ready      # type: ignore[method-assign]
    launcher.is_running = fake.is_running  # type: ignore[method-assign]
    launcher.start = fake.start            # type: ignore[method-assign]

    # 自动拉起前：状态里是未加载
    before = {m["name"]: m["loaded"] for m in orch.status()["models"]}
    assert before["m1"] is False

    spec.client_instance._ensure_launcher_running()

    statuses = [s for (_, s) in seen]
    assert statuses == ["loading", "loaded"], f"实际 {statuses!r}"

    # 关键断言：模型列表/显存页读的就是这个 status()
    after = {m["name"]: m["loaded"] for m in orch.status()["models"]}
    assert after["m1"] is True, "自动拉起后 status() 仍报告未加载，模型列表/显存页会空"

    assert "m1" not in orch._loading_models


def test_orchestrator_marks_unloaded_on_failure():
    """自动拉起失败时，调度器必须回到未加载（避免 UI 卡在 loading）。"""
    orch = ModelOrchestrator.get_instance(max_concurrent_slots=2)
    cfg = LlamaServerConfig(
        binary_path="/mock/bin/llama-server",
        model_path="/mock/model.gguf",
        port=8099,
    )
    orch.register_local_llamacpp("m1", cfg, priority=80)

    seen: list[str] = []
    orch.add_status_listener(lambda name, status, extra: seen.append(status))

    spec = orch.get_model_spec("m1")
    client = spec.client_instance

    def _boom(*args, **kwargs):
        raise RuntimeError("启动失败")

    client._launcher.is_ready = lambda timeout=2.0: False  # type: ignore[method-assign]
    client._launcher.start = _boom                          # type: ignore[method-assign]

    with pytest.raises(RuntimeError):
        client._ensure_launcher_running()

    assert seen == ["loading", "failed"], f"实际 {seen!r}"
    assert "m1" not in orch._loading_models
