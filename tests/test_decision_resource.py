"""System-1 决策资源的生命周期测试。

覆盖：
  1. infra.resources.ResourceKind —— 新增 DECISION 种类
  2. infra.resources.decision_service —— 注册、按需拉起、租约语义
  3. **空闲自动回收** —— 决策模型闲置后必须像 TTS 一样自动释放显存
  4. adopt 模式不被回收（只接入、不杀进程）
  5. harness.decisions.DecisionService —— 门面串接（租约覆盖整个决策过程）

测试期间**绝不真的拉起 llama-server**（需 GPU + 16GB 权重）。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infra.resources import ResourceKind, ResourcePool  # noqa: E402
from infra.resources.decision_service import (  # noqa: E402
    DECISION_RESOURCE,
    DecisionConfig,
    decision_lease,
    decision_provider,
    decision_status,
    register_decision_resource,
)


class _FakeLauncher:
    """假 launcher：记录拉起/停掉次数，不起真进程。"""

    def __init__(self):
        self.loads = 0
        self.unloads = 0
        self.running = False

    def create_scheduler_hooks(self, load_timeout: int = 180, on_status=None):
        def _load() -> bool:
            self.loads += 1
            self.running = True
            return True

        def _unload() -> bool:
            self.unloads += 1
            self.running = False
            return True

        return _load, _unload

    def is_running(self) -> bool:
        return self.running

    def command_string(self):
        return "fake-llama-server"


@pytest.fixture()
def fake_launcher(monkeypatch):
    """把 decision_service 的模型/二进制解析与 launcher 全部换掉。"""
    from infra.decision.jev import JevModel
    from infra.resources import decision_service as ds

    model = JevModel(
        name="jev:test",
        model_path="/tmp/fake/JEV-27B-VL.Q4_K_M.gguf",
        mmproj_path="/tmp/fake/JEV-27B-VL.mmproj.gguf",
        directory="fake",
    )
    launcher = _FakeLauncher()

    monkeypatch.setattr(ds, "resolve_decision_model", lambda cfg: model)
    monkeypatch.setattr(ds, "resolve_decision_binary", lambda: "/usr/bin/true")
    monkeypatch.setattr(ds, "LlamaServerLauncher", lambda cfg, log_file=None: launcher)
    monkeypatch.setattr(ds, "build_decision_launcher",
                        lambda cfg: _install(ds, launcher, model))
    return launcher


def _install(ds, launcher, model):
    ds._state["launcher"] = launcher
    ds._state["model"] = model
    return launcher


# ── 1. 资源种类 ──

def test_resource_kind_has_decision():
    assert ResourceKind.DECISION.value == "decision"


# ── 2. 注册与按需拉起 ──

def test_register_decision_resource_marks_managed(fake_launcher):
    pool = ResourcePool(max_concurrent=1)
    register_decision_resource(pool, DecisionConfig(port=8099, idle_timeout=900))
    spec = pool.get_spec(DECISION_RESOURCE)
    assert spec is not None
    assert spec.kind == ResourceKind.DECISION
    assert spec.resident is True          # 绝不被槽位压力驱逐
    assert spec.immediate is False        # 归还租约不立刻卸载
    assert spec.idle_timeout == 900
    assert spec.extra["managed"] is True


def test_lease_triggers_lazy_start(fake_launcher):
    """注册时不启动；第一次取租约才拉起。"""
    pool = ResourcePool(max_concurrent=1)
    register_decision_resource(pool, DecisionConfig(port=8099))
    assert fake_launcher.loads == 0

    with decision_lease(pool, DecisionConfig(port=8099)):
        assert fake_launcher.loads == 1
        assert pool.snapshot()[DECISION_RESOURCE]["loaded"] is True


def test_lease_release_keeps_service_running_until_idle(fake_launcher):
    """归还租约**不**立刻卸载 —— 要等空闲回收。"""
    pool = ResourcePool(max_concurrent=1)
    cfg = DecisionConfig(port=8099, idle_timeout=900)
    register_decision_resource(pool, cfg)
    with decision_lease(pool, cfg):
        pass
    assert fake_launcher.unloads == 0
    assert pool.snapshot()[DECISION_RESOURCE]["loaded"] is True


def test_lease_raises_when_not_registered(fake_launcher):
    pool = ResourcePool(max_concurrent=1)
    with pytest.raises(Exception):
        with decision_lease(pool, DecisionConfig()):
            pass


# ── 3. 空闲自动回收（核心要求）──

def test_idle_reaper_releases_decision_resource(fake_launcher):
    """闲置超过阈值 → 自动停掉进程、释放显存。

    这条与 TTS 用的是同一套 IdleReaper —— 决策模型同样是「用完可以扔」
    的重量级服务，不能一直占着双卡。
    """
    pool = ResourcePool(max_concurrent=1)
    cfg = DecisionConfig(port=8099, idle_timeout=1)
    register_decision_resource(pool, cfg)

    with decision_lease(pool, cfg):
        pass
    assert fake_launcher.unloads == 0

    reaper = pool.enable_idle_shutdown(interval=1.0)
    try:
        deadline = time.time() + 8
        while time.time() < deadline and fake_launcher.unloads == 0:
            time.sleep(0.2)
    finally:
        reaper.stop()

    assert fake_launcher.unloads >= 1
    assert pool.snapshot()[DECISION_RESOURCE]["loaded"] is False


def test_idle_reaper_skips_adopt_resource(fake_launcher):
    """adopt 模式（只接入既有服务）没有 unload 能力，不该被回收。"""
    pool = ResourcePool(max_concurrent=1)
    cfg = DecisionConfig(port=8099, idle_timeout=1, autostart=False)
    register_decision_resource(pool, cfg)

    reaper = pool.enable_idle_shutdown(interval=1.0)
    try:
        time.sleep(2.5)
    finally:
        reaper.stop()
    assert fake_launcher.unloads == 0


def test_reclaimed_resource_is_reloaded_on_next_request(fake_launcher):
    """回收之后下一次请求必须能重新拉起来。"""
    pool = ResourcePool(max_concurrent=1)
    cfg = DecisionConfig(port=8099, idle_timeout=1)
    register_decision_resource(pool, cfg)
    with decision_lease(pool, cfg):
        pass

    pool.reclaim_idle_resource(DECISION_RESOURCE)
    assert fake_launcher.unloads == 1

    with decision_lease(pool, cfg):
        pass
    assert fake_launcher.loads == 2


# ── 4. 状态视图 ──

def test_decision_status_reports_registration(fake_launcher):
    pool = ResourcePool(max_concurrent=1)
    register_decision_resource(pool, DecisionConfig(port=8099, idle_timeout=900))
    info = decision_status(pool)
    assert info["registered"] is True
    assert info["managed"] is True
    assert info["idle_timeout"] == 900
    assert "fake/JEV-27B-VL.Q4_K_M.gguf" in info["model"]


# ── 5. 租约与门面 ──

def test_lease_holds_pool_refcount(fake_launcher):
    """决策进行中必须持有租约 —— 否则空闲回收器可能把服务停掉。"""
    pool = ResourcePool(max_concurrent=1)
    cfg = DecisionConfig(port=8099)
    register_decision_resource(pool, cfg)

    with decision_lease(pool, cfg):
        assert pool.snapshot()[DECISION_RESOURCE]["refcount"] >= 1
        assert pool.used_slots() >= 1
    assert pool.snapshot()[DECISION_RESOURCE]["refcount"] == 0


def test_decision_service_holds_provider_context():
    """门面必须把 provider 的上下文覆盖到整个决策过程。"""
    from contextlib import contextmanager

    from harness.decisions import DecisionService
    from infra.decision.client import RawDecision

    events = []

    class _StubClient:
        model = "fake"

        def candidates(self, messages, **kw):
            events.append("decide")
            return RawDecision(candidates={"Y": 0.9, "N": 0.1}, model="fake", latency_ms=1.0)

    @contextmanager
    def _provider():
        events.append("enter")
        yield _StubClient()
        events.append("exit")

    svc = DecisionService(_provider)
    res = svc.decide_yes_no("问题", "状态")
    assert res.answer is True
    assert res.probability == pytest.approx(0.9)
    assert events == ["enter", "decide", "exit"]
