"""语音计算资源「空闲自动关闭 + 请求时重启」测试。

覆盖：
  1. infra.resources.IdleReaper —— 空闲判定与回收边界
  2. ResourcePool.reclaim_idle_resource —— 回收的排他性与状态同步
  3. 回收后的重启语义 —— 下次请求必须重新拉起资源
  4. 应用层配置 —— 总开关 / 统一阈值 / 单资源覆盖的解析规则
  5. dsn_study 接线 —— 注册时挂载 idle_timeout 并启用回收器
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 测试期间绝不真的拉起语音服务（需 conda 环境 + GPU + 分钟级权重加载）
os.environ.setdefault("ASR_AUTOSTART", "false")
os.environ.setdefault("TTS_AUTOSTART", "false")
os.environ.setdefault("ASR_WARMUP", "false")
os.environ.setdefault("TTS_WARMUP", "false")
os.environ.setdefault("ASR_WARMUP_ON_LOAD", "false")


# ── 公共夹具 ──

def _make_pool(name="tts", *, idle_timeout=3600, managed=True, resident=True):
    """建一个只带假 load/unload 的资源池，避免真实拉起任何服务。"""
    from infra.resources import ResourceKind, ResourcePool, ResourceSpec

    state = {"load_calls": 0, "unload_calls": 0}

    def _load():
        state["load_calls"] += 1
        return True

    def _unload():
        state["unload_calls"] += 1
        return True

    pool = ResourcePool(max_concurrent=1)
    pool.register_resource(
        name,
        ResourceSpec(
            kind=ResourceKind.TTS,
            display_name="测试资源",
            base_url="http://127.0.0.1:9880",
            resident=resident,
            idle_timeout=idle_timeout,
            extra={"managed": managed},
        ),
        _load,
        _unload,
    )
    return pool, state


def _reaper(pool, *, ahead=4000):
    """造一个「时间快进了 ahead 秒」的回收器，用来模拟长时间闲置。"""
    from infra.resources.idle import IdleReaper

    return IdleReaper(pool, clock=lambda: time.time() + ahead)


# ── 1. IdleReaper 判定 ──

def test_idle_reaper_reclaims_idle_managed_resource():
    """闲置超过阈值且池能控制 → 回收，资源被卸载。"""
    pool, state = _make_pool(idle_timeout=3600, managed=True)
    assert pool.ensure_running("tts")
    assert state["load_calls"] == 1

    reclaimed = _reaper(pool).reap_once()

    assert reclaimed == ["tts"]
    assert state["unload_calls"] == 1, "回收必须真正调用 unload_fn 停掉服务"
    assert pool.snapshot()["tts"]["loaded"] is False


def test_idle_reaper_keeps_resource_within_timeout():
    """闲置时间没到阈值 → 不回收。"""
    pool, state = _make_pool(idle_timeout=3600)
    pool.ensure_running("tts")

    # 只前进 60 秒，远不到 3600 秒阈值
    reclaimed = _reaper(pool, ahead=60).reap_once()

    assert reclaimed == []
    assert state["unload_calls"] == 0


def test_idle_reaper_skips_resource_in_use():
    """正被使用的资源 → 绝不回收（不能打断进行中的请求）。"""
    pool, state = _make_pool(idle_timeout=3600)
    pool.ensure_running("tts")

    lease = pool.acquire("tts")
    try:
        assert _reaper(pool).reap_once() == []
        assert state["unload_calls"] == 0
    finally:
        lease.release()


def test_idle_reaper_skips_adopt_resource():
    """adopt 模式（池不控制进程生命周期）→ 无从停起，跳过。"""
    pool, state = _make_pool(idle_timeout=3600, managed=False)
    pool.ensure_running("tts")

    assert _reaper(pool).reap_once() == []
    assert state["unload_calls"] == 0


def test_idle_reaper_skips_zero_timeout():
    """idle_timeout=0（该资源常驻不回收）→ 跳过。"""
    pool, state = _make_pool(idle_timeout=0, managed=True)
    pool.ensure_running("tts")

    assert _reaper(pool).reap_once() == []
    assert state["unload_calls"] == 0


def test_idle_reaper_skips_unloaded_resource():
    """本来就没加载 → 不需要回收。"""
    pool, state = _make_pool(idle_timeout=3600)

    assert _reaper(pool).reap_once() == []
    assert state["unload_calls"] == 0


# ── 2. 回收的排他性与状态同步 ──

def test_reclaim_refuses_when_resource_in_use():
    """reclaim_idle_resource 在有引用时拒绝回收。"""
    pool, state = _make_pool(idle_timeout=3600)
    pool.ensure_running("tts")

    lease = pool.acquire("tts")
    try:
        assert pool.reclaim_idle_resource("tts") is False
        assert state["unload_calls"] == 0
    finally:
        lease.release()


def test_reclaim_marks_scheduler_state_unloaded():
    """回收后调度器状态必须同步为未加载，否则状态接口会一直报 loaded。"""
    pool, state = _make_pool(idle_timeout=3600)
    pool.ensure_running("tts")
    assert pool.snapshot()["tts"]["loaded"] is True

    assert pool.reclaim_idle_resource("tts") is True

    snap = pool.snapshot()["tts"]
    assert snap["loaded"] is False
    assert snap["refcount"] == 0


# ── 3. 回收后的重启语义 ──

def test_reclaimed_resource_is_reloaded_on_next_request():
    """核心语义：空闲关闭后，下次请求必须把资源重新拉起来。"""
    pool, state = _make_pool(idle_timeout=3600)
    pool.ensure_running("tts")
    assert state["load_calls"] == 1

    assert _reaper(pool).reap_once() == ["tts"]
    assert state["unload_calls"] == 1
    assert state["load_calls"] == 1

    # 下次请求 → 调度器走加载路径重新拉起
    with pool.lease("tts"):
        pass

    assert state["load_calls"] == 2, "回收后下次请求必须重新拉起资源"
    assert pool.snapshot()["tts"]["loaded"] is True


def test_request_waits_for_in_progress_reclaim():
    """回收进行中到达的请求必须等待，不能撞上正在被杀的服务。"""
    pool, state = _make_pool(idle_timeout=3600)
    pool.ensure_running("tts")

    reclaim_started = threading.Event()
    release_reclaim = threading.Event()

    def slow_unload():
        reclaim_started.set()
        release_reclaim.wait(10)
        state["unload_calls"] += 1
        return True

    with pool._condition:  # noqa: SLF001 —— 替换成慢速卸载以制造竞态窗口
        pool._models["tts"].unload_fn = slow_unload

    reaper = _reaper(pool)
    reaper_thread = threading.Thread(target=reaper.reap_once, daemon=True)
    reaper_thread.start()
    assert reclaim_started.wait(5), "回收线程应已开始卸载"

    request_done = threading.Event()

    def _request():
        with pool.lease("tts"):
            pass
        request_done.set()

    request_thread = threading.Thread(target=_request, daemon=True)
    request_thread.start()

    time.sleep(0.3)
    assert not request_done.is_set(), "回收进行中时请求必须等待，不能直接使用"

    release_reclaim.set()
    reaper_thread.join(10)
    request_thread.join(10)

    assert request_done.is_set(), "回收结束后请求应继续完成"
    assert state["load_calls"] == 2, "等待结束后应重新加载资源"


# ── 4. 应用层配置 ──

def test_idle_timeout_zero_when_master_switch_off(monkeypatch):
    """总开关关闭 → 谁都不回收。"""
    from apps.dsn_study.config import Config
    from apps.dsn_study.models import resource_setup as rs

    monkeypatch.setattr(Config, "VOICE_IDLE_SHUTDOWN", False, raising=False)
    monkeypatch.setattr(Config, "TTS_IDLE_TIMEOUT", 3600, raising=False)
    monkeypatch.setattr(Config, "ASR_IDLE_TIMEOUT", 3600, raising=False)

    assert rs._idle_timeout("tts") == 0  # noqa: SLF001
    assert rs._idle_timeout("asr") == 0  # noqa: SLF001


def test_idle_timeout_per_resource_override(monkeypatch):
    """单资源可覆盖：ASR 显式设为 0 → ASR 常驻，只有 TTS 回收。"""
    from apps.dsn_study.config import Config
    from apps.dsn_study.models import resource_setup as rs

    monkeypatch.setattr(Config, "VOICE_IDLE_SHUTDOWN", True, raising=False)
    monkeypatch.setattr(Config, "VOICE_IDLE_TIMEOUT", 3600, raising=False)
    monkeypatch.setattr(Config, "TTS_IDLE_TIMEOUT", 3600, raising=False)
    monkeypatch.setattr(Config, "ASR_IDLE_TIMEOUT", 0, raising=False)

    assert rs._idle_timeout("tts") == 3600  # noqa: SLF001
    assert rs._idle_timeout("asr") == 0  # noqa: SLF001


def test_idle_timeout_follows_unified_value(monkeypatch):
    """未单独配置时跟随统一阈值。"""
    from apps.dsn_study.config import Config
    from apps.dsn_study.models import resource_setup as rs

    monkeypatch.setattr(Config, "VOICE_IDLE_SHUTDOWN", True, raising=False)
    monkeypatch.setattr(Config, "VOICE_IDLE_TIMEOUT", 1800, raising=False)
    monkeypatch.setattr(Config, "TTS_IDLE_TIMEOUT", 1800, raising=False)
    monkeypatch.setattr(Config, "ASR_IDLE_TIMEOUT", 1800, raising=False)

    assert rs._idle_timeout("tts") == 1800  # noqa: SLF001
    assert rs._idle_timeout("asr") == 1800  # noqa: SLF001


# ── 5. dsn_study 接线 ──

def test_setup_study_resources_enables_idle_reaper(monkeypatch):
    """启用后：资源带上 idle_timeout，池上挂起回收器。"""
    from apps.dsn_study.config import Config
    from apps.dsn_study.models import resource_setup as rs

    monkeypatch.setattr(Config, "VOICE_IDLE_SHUTDOWN", True, raising=False)
    monkeypatch.setattr(Config, "VOICE_IDLE_TIMEOUT", 3600, raising=False)
    monkeypatch.setattr(Config, "VOICE_IDLE_CHECK_INTERVAL", 60, raising=False)
    monkeypatch.setattr(Config, "TTS_IDLE_TIMEOUT", 3600, raising=False)
    monkeypatch.setattr(Config, "ASR_IDLE_TIMEOUT", 3600, raising=False)
    monkeypatch.setattr(Config, "TTS_AUTOSTART", False, raising=False)
    monkeypatch.setattr(Config, "ASR_AUTOSTART", False, raising=False)
    monkeypatch.setattr(Config, "ASR_WARMUP_ON_LOAD", False, raising=False)

    saved_state = dict(rs._state)
    rs._state["pool"] = None
    pool = None
    try:
        pool = rs.setup_study_resources()

        status = pool.idle_status()
        assert status["enabled"] is True
        assert status["reaper"]["running"] is True

        rows = {r["name"]: r for r in pool.list_resources()}
        assert rows["tts"]["idle_timeout"] == 3600
        assert rows["asr"]["idle_timeout"] == 3600
        # 状态视图应带上空闲信息，供前端展示
        assert "idle_seconds" in rows["tts"]
    finally:
        if pool is not None:
            pool.disable_idle_shutdown()
        rs._state.clear()
        rs._state.update(saved_state)


def test_setup_study_resources_no_reaper_without_switch(monkeypatch):
    """总开关关闭 → 不启用回收器，资源也不带空闲阈值。"""
    from apps.dsn_study.config import Config
    from apps.dsn_study.models import resource_setup as rs

    # 池级总开关优先于语音开关（config.resource_idle_shutdown_enabled 读环境变量），
    # 所以这里必须显式清空它 —— 否则 .env 里开了总开关的机器上这条会误判。
    # 与 tests/test_dsn_study_vlm.py 的同名处理保持一致。
    monkeypatch.setenv("RESOURCE_IDLE_SHUTDOWN", "")
    monkeypatch.setattr(Config, "VOICE_IDLE_SHUTDOWN", False, raising=False)
    monkeypatch.setattr(Config, "TTS_AUTOSTART", False, raising=False)
    monkeypatch.setattr(Config, "ASR_AUTOSTART", False, raising=False)
    monkeypatch.setattr(Config, "ASR_WARMUP_ON_LOAD", False, raising=False)

    saved_state = dict(rs._state)
    rs._state["pool"] = None
    pool = None
    try:
        pool = rs.setup_study_resources()
        assert pool.idle_status()["enabled"] is False
        rows = {r["name"]: r for r in pool.list_resources()}
        assert rows["tts"]["idle_timeout"] == 0
        assert rows["asr"]["idle_timeout"] == 0
    finally:
        if pool is not None:
            pool.disable_idle_shutdown()
        rs._state.clear()
        rs._state.update(saved_state)


def test_asr_load_triggers_warmup(monkeypatch):
    """池拉起 ASR 后必须补一次模型预热（替代原 systemd 的 ExecStartPost）。

    ASR 模型是懒加载的：sidecar 起来了但权重还没进显存，
    不预热则冷启动后首个识别请求要独自承担全部加载耗时。
    """
    from apps.dsn_study.config import Config
    from apps.dsn_study.models import resource_setup as rs

    calls = []

    class _FakeClient:
        def __init__(self, base_url, timeout=120.0):
            calls.append(("init", base_url))

        def warmup(self, timeout=600.0):
            calls.append(("warmup", timeout))
            return True

    monkeypatch.setattr(Config, "ASR_WARMUP_ON_LOAD", True, raising=False)
    monkeypatch.setattr(Config, "ASR_LOAD_TIMEOUT", 600, raising=False)

    import apps.dsn_study.models.asr_client as asr_client_mod

    monkeypatch.setattr(asr_client_mod, "ASRClient", _FakeClient)

    wrapped = rs._with_asr_warmup(lambda: True, "http://127.0.0.1:9881")  # noqa: SLF001
    assert wrapped() is True
    assert ("warmup", 600.0) in calls


def test_asr_warmup_failure_does_not_break_load(monkeypatch):
    """预热失败不应让整个加载失败 —— 服务已就绪，模型可懒加载。"""
    from apps.dsn_study.config import Config
    from apps.dsn_study.models import resource_setup as rs

    monkeypatch.setattr(Config, "ASR_WARMUP_ON_LOAD", True, raising=False)
    monkeypatch.setattr(Config, "ASR_LOAD_TIMEOUT", 600, raising=False)

    import apps.dsn_study.models.asr_client as asr_client_mod

    class _BoomClient:
        def __init__(self, base_url, timeout=120.0):
            pass

        def warmup(self, timeout=600.0):
            raise RuntimeError("预热炸了")

    monkeypatch.setattr(asr_client_mod, "ASRClient", _BoomClient)

    wrapped = rs._with_asr_warmup(lambda: True, "http://127.0.0.1:9881")  # noqa: SLF001
    assert wrapped() is True
