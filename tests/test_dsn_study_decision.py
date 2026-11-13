"""dsn_study 的 System-1 决策接入测试。

覆盖：
  1. DecisionStatePlugin —— 语气提示注入、异常隔离、结果落到 ctx.extra
  2. probe_state —— 危机关键词预筛、情绪只在语音轮读、不可用时降级
  3. 情绪 → TTS 语速映射（tone_params）与 TTSPlugin 的接线
  4. 显存预检 —— 显存不够就不拉起决策模型（避免 OOM 掉同机其它服务）
  5. 决策资源在 study 资源池里的注册与空闲回收

全部打桩，不拉起真实模型。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("ASR_AUTOSTART", "false")
os.environ.setdefault("TTS_AUTOSTART", "false")
os.environ.setdefault("VLM_AUTOSTART", "false")

from harness.pipeline.base import Context, HookPoint  # noqa: E402


class _FakeState:
    """替身 StateProbe。"""

    def __init__(self, tone_hint="", degraded=False):
        self.tone_hint = tone_hint
        self.degraded = degraded

    def to_dict(self):
        return {"tone_hint": self.tone_hint, "degraded": self.degraded}


# ── 1. DecisionStatePlugin ──

def test_plugin_injects_tone_hint_and_records_state():
    from apps.dsn_study.pipeline.plugins import DecisionStatePlugin

    plugin = DecisionStatePlugin(probe=lambda text, is_voice=False:
                                 _FakeState(tone_hint="用户情绪低落：语气温和简短。"))
    ctx = Context(message="今天好累")
    plugin.on_hook(HookPoint.PRE_PROCESS, ctx)
    assert "语气温和简短" in ctx.message
    assert ctx.extra["decision"]["tone_hint"] == "用户情绪低落：语气温和简短。"


def test_plugin_is_silent_without_signal():
    from apps.dsn_study.pipeline.plugins import DecisionStatePlugin

    plugin = DecisionStatePlugin(probe=lambda text, is_voice=False: _FakeState())
    ctx = Context(message="今天好累")
    plugin.on_hook(HookPoint.PRE_PROCESS, ctx)
    assert ctx.message == "今天好累"


def test_plugin_survives_probe_failure():
    """决策是增强项 —— 探测炸了也不能打断对话。"""
    from apps.dsn_study.pipeline.plugins import DecisionStatePlugin

    def _boom(text, is_voice=False):
        raise RuntimeError("决策端点炸了")

    plugin = DecisionStatePlugin(probe=_boom)
    ctx = Context(message="你好")
    plugin.on_hook(HookPoint.PRE_PROCESS, ctx)
    assert ctx.message == "你好"


def test_plugin_passes_voice_flag():
    from apps.dsn_study.pipeline.plugins import DecisionStatePlugin

    seen = {}

    def _probe(text, is_voice=False):
        seen["is_voice"] = is_voice
        return _FakeState()

    plugin = DecisionStatePlugin(probe=_probe)
    plugin.on_hook(HookPoint.PRE_PROCESS, Context(message="喂", is_asr_input=True))
    assert seen["is_voice"] is True


# ── 2. probe_state ──

def _fake_service(monkeypatch, *, answers=None):
    """装一个假决策服务，返回固定结果。"""
    from harness.decisions.core import DecisionResult, choice_confidence

    calls = []

    def _decide(req):
        calls.append(req)
        if req.normalized_type() == "yes_no":
            p = float((answers or {}).get("yes", 0.9))
            return DecisionResult(type="yes_no", answer=p >= 0.5, probability=p,
                                  distribution={"Y": p, "N": 1 - p},
                                  confidence=abs(p - 0.5) * 2)
        options = req.normalized_options()
        labels = list(options)
        dist = {k: 1.0 / len(labels) for k in labels}
        dist[labels[0]] = 0.7
        total = sum(dist.values())
        dist = {k: v / total for k, v in dist.items()}
        best = max(dist, key=dist.get)
        return DecisionResult(type="choice", answer=best,
                              label=options.get(best, ""),
                              probability=dist[best], distribution=dist,
                              confidence=choice_confidence(dist))

    class _Svc:
        def decide(self, req):
            return _decide(req)

    import apps.dsn_study.models.decision_service as ds
    monkeypatch.setattr(ds, "get_decision_service", lambda pool=None: _Svc())
    return calls


def test_probe_state_reads_emotion_only_on_voice_turns(monkeypatch):
    import apps.dsn_study.models.decision_service as ds
    from apps.dsn_study.config import Config

    monkeypatch.setattr(Config, "DECISION_PROBE_SCOPE", "voice", raising=False)
    calls = _fake_service(monkeypatch)

    ds.probe_state("你好", is_voice=False)
    assert calls == []          # 文字轮不问模型

    ds.probe_state("你好", is_voice=True)
    assert len(calls) == 1      # 语音轮读一次情绪


def test_probe_state_skips_crisis_model_without_keywords(monkeypatch):
    import apps.dsn_study.models.decision_service as ds

    calls = _fake_service(monkeypatch)
    state = ds.probe_state("今天天气不错", is_voice=True)
    assert state.crisis.is_crisis is False
    # one emotion read and no crisis read, the keyword did not match
    assert len(calls) == 1
    assert "keyword" in (state.crisis.reason or "")


def test_probe_state_consults_model_on_crisis_keywords(monkeypatch):
    import apps.dsn_study.models.decision_service as ds

    calls = _fake_service(monkeypatch, answers={"yes": 0.95})
    state = ds.probe_state("我真的不想活了", is_voice=False)
    assert state.crisis.is_crisis is True
    assert state.crisis.confident is True
    assert len(calls) == 1
    # 危机时给主模型的提示是「先关怀」，不是「先讲道理」
    assert "关怀" in state.tone_hint


def test_probe_state_degrades_without_service(monkeypatch):
    import apps.dsn_study.models.decision_service as ds

    monkeypatch.setattr(ds, "get_decision_service", lambda pool=None: None)
    state = ds.probe_state("你好", is_voice=True)
    assert state.degraded is True
    assert state.tone_hint == ""


# ── 3. 情绪 → 语速 ──

def test_tone_params_maps_emotion_to_speed():
    from apps.dsn_study.voice import tone_params

    assert tone_params({"emotion": {"label": "低落", "degraded": False}}) == \
        {"speed_factor": 0.94}
    assert tone_params({"emotion": {"label": "开心", "degraded": False}}) == \
        {"speed_factor": 1.06}
    assert tone_params({"emotion": {"label": "平静", "degraded": False}}) == {}


def test_tone_params_crisis_overrides_emotion():
    from apps.dsn_study.voice import tone_params

    out = tone_params({"emotion": {"label": "开心", "degraded": False},
                       "crisis": {"is_crisis": True}})
    assert out["speed_factor"] < 1.0


def test_tone_params_ignores_degraded_state():
    from apps.dsn_study.voice import tone_params

    assert tone_params({"emotion": {"label": "低落", "degraded": True}}) == {}
    assert tone_params(None) == {}


def test_tts_plugin_passes_tone_params():
    from apps.dsn_study.pipeline.plugins import TTSPlugin

    seen = {}

    class _Voice:
        def synthesize_b64(self, text, params_override=None):
            seen["params"] = params_override
            return "AUDIO", ""

    ctx = Context(message="你好", reply="好的", tts_enabled=True)
    ctx.extra["decision"] = {"emotion": {"label": "低落", "degraded": False}}
    TTSPlugin(voice=_Voice()).on_hook(HookPoint.POST_TTS, ctx)
    assert seen["params"] == {"speed_factor": 0.94}
    assert ctx.audio_b64 == "AUDIO"


def test_tts_plugin_without_decision_uses_default_params():
    from apps.dsn_study.pipeline.plugins import TTSPlugin

    seen = {}

    class _Voice:
        def synthesize_b64(self, text, params_override=None):
            seen["params"] = params_override
            return "AUDIO", ""

    ctx = Context(message="你好", reply="好的", tts_enabled=True)
    TTSPlugin(voice=_Voice()).on_hook(HookPoint.POST_TTS, ctx)
    assert seen["params"] == {}


# ── 4. 显存预检 ──

def test_vram_guard_blocks_when_not_enough(monkeypatch):
    import apps.dsn_study.models.decision_service as ds
    from apps.dsn_study.config import Config

    monkeypatch.setattr(Config, "DECISION_VRAM_REQUIRED_MB", 20000, raising=False)
    monkeypatch.setattr(ds, "free_vram_mb", lambda: 4096)
    with pytest.raises(Exception):
        ds.vram_guard()


def test_vram_guard_passes_when_enough(monkeypatch):
    import apps.dsn_study.models.decision_service as ds
    from apps.dsn_study.config import Config

    monkeypatch.setattr(Config, "DECISION_VRAM_REQUIRED_MB", 17000, raising=False)
    monkeypatch.setattr(ds, "free_vram_mb", lambda: 18000)
    ds.vram_guard()   # 不抛即通过


def test_vram_guard_allows_when_model_already_running(monkeypatch):
    """模型已经在跑时，那块显存就是它自己的 —— 不能按「空闲显存」误判。"""
    import apps.dsn_study.models.decision_service as ds
    from apps.dsn_study.config import Config

    monkeypatch.setattr(Config, "DECISION_VRAM_REQUIRED_MB", 17000, raising=False)
    monkeypatch.setattr(ds, "free_vram_mb", lambda: 2000)

    class _Pool:
        def snapshot(self):
            return {"decision": {"loaded": True}}

        def get_spec(self, name):
            return None

    monkeypatch.setattr(ds, "get_study_pool", lambda: _Pool(), raising=False)
    ds.vram_guard(_Pool())     # 不抛即通过


def test_vram_guard_ignores_unknown_free_memory(monkeypatch):
    """取不到显存（没装 nvidia-smi）时不要拦住决策。"""
    import apps.dsn_study.models.decision_service as ds
    from apps.dsn_study.config import Config

    monkeypatch.setattr(Config, "DECISION_VRAM_REQUIRED_MB", 17000, raising=False)
    monkeypatch.setattr(ds, "free_vram_mb", lambda: -1)
    ds.vram_guard()


# ── 5. 资源注册 ──

def test_study_pool_registers_decision_resource(monkeypatch):
    from infra.resources import ResourcePool
    from infra.resources.decision_service import DECISION_RESOURCE
    import apps.dsn_study.models.decision_service as ds
    from apps.dsn_study.config import Config

    monkeypatch.setattr(Config, "DECISION_ENABLED", True, raising=False)
    monkeypatch.setattr(Config, "DECISION_IDLE_TIMEOUT", 900, raising=False)

    class _FakeLauncher:
        def create_scheduler_hooks(self, load_timeout=180, on_status=None):
            return (lambda: True), (lambda: True)

        def is_running(self):
            return False

        def command_string(self):
            return "fake"

    import infra.resources.decision_service as ids
    monkeypatch.setattr(ids, "build_decision_launcher", lambda cfg: _FakeLauncher())
    monkeypatch.setattr(ids, "resolve_decision_model", lambda cfg: type(
        "M", (), {"name": "jev:test", "model_path": "/tmp/fake.gguf",
                  "mmproj_path": "", "is_multimodal": False})())
    monkeypatch.setattr(ids, "resolve_decision_binary", lambda: "/usr/bin/true")

    pool = ResourcePool(max_concurrent=1)
    ds.register_study_decision(pool)
    spec = pool.get_spec(DECISION_RESOURCE)
    assert spec is not None
    assert spec.idle_timeout == 900
    assert spec.resident is True
