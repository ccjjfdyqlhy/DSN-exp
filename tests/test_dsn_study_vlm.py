"""本地 VLM（整卷入库 OCR）测试。

覆盖：
  1. infra.orchestrator.bonsai —— Bonsai 资源发现（二进制 / 模型 / 投影器配对）
  2. infra.resources.ResourceKind.VLM —— 资源种类扩展
  3. apps.dsn_study.models.vlm_service —— 资源注册、按需拉起、租约语义
  4. apps.dsn_study.models.resource_setup —— 空闲回收阈值的两级开关
  5. apps.dsn_study.question_bank.paper_import —— OCR 确实走本地端点

测试期间**绝不真的拉起 llama-server**（需 GPU + 7.2GB 权重加载）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("ASR_AUTOSTART", "false")
os.environ.setdefault("TTS_AUTOSTART", "false")
os.environ.setdefault("ASR_WARMUP", "false")
os.environ.setdefault("TTS_WARMUP", "false")
os.environ.setdefault("ASR_WARMUP_ON_LOAD", "false")
# 测试期间走 adopt 模式：只接入既有服务，绝不拉起进程
os.environ.setdefault("VLM_AUTOSTART", "false")


# ── 1. Bonsai 资源发现 ──

def _fake_bonsai(root: Path, *, with_mmproj=True, model_size=1024):
    """造一个假的 Bonsai-demo 目录。"""
    bin_dir = root / "bin" / "cuda"
    bin_dir.mkdir(parents=True, exist_ok=True)
    exe = bin_dir / "llama-server"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)

    model_dir = root / "models" / "bonsai2-gguf" / "27B"
    model_dir.mkdir(parents=True, exist_ok=True)
    model = model_dir / "Ternary-Bonsai-2-27B-PQ2_0.gguf"
    model.write_bytes(b"\0" * model_size)
    if with_mmproj:
        proj = model_dir / "Ternary-Bonsai-2-27B-mmproj-Q8_0.gguf"
        proj.write_bytes(b"\0" * 16)
    return root


def test_find_bonsai_binary_prefers_cuda(tmp_path):
    from infra.orchestrator.bonsai import find_bonsai_binary

    root = _fake_bonsai(tmp_path / "demo")
    got = find_bonsai_binary(root)
    assert got is not None
    assert got.endswith("bin/cuda/llama-server")


def test_scan_excludes_auxiliary_gguf(tmp_path):
    """mmproj 是投影器，不能被当成「主模型」注册。"""
    from infra.orchestrator.bonsai import scan_bonsai_models

    root = _fake_bonsai(tmp_path / "demo")
    models = scan_bonsai_models(root)
    assert len(models) == 1
    assert models[0].is_multimodal is True
    assert models[0].mmproj_path and "mmproj" in models[0].mmproj_path


def test_pick_multimodal_prefers_largest(tmp_path):
    """多个多模态模型时选体积最大的那个（OCR 场景的默认诉求）。"""
    from infra.orchestrator.bonsai import pick_multimodal_model

    root = _fake_bonsai(tmp_path / "demo")
    small_dir = root / "models" / "bonsai2-gguf" / "8B"
    small_dir.mkdir(parents=True, exist_ok=True)
    small = small_dir / "small.gguf"
    small.write_bytes(b"\0" * 16)
    (small_dir / "small-mmproj.gguf").write_bytes(b"\0" * 8)

    picked = pick_multimodal_model(root)
    assert picked is not None
    assert "27B" in picked.model_path


def test_pick_multimodal_returns_none_without_projector(tmp_path):
    """没有投影器 = 纯文本模型，无法做 OCR → 必须返回 None。"""
    from infra.orchestrator.bonsai import pick_multimodal_model

    root = _fake_bonsai(tmp_path / "demo", with_mmproj=False)
    assert pick_multimodal_model(root) is None


# ── 2. 资源种类 ──

def test_resource_kind_has_vlm():
    from infra.resources import ResourceKind

    assert ResourceKind.VLM.value == "vlm"


# ── 3. VLM 资源注册与租约 ──

@pytest.fixture
def clean_pool():
    """一个只带 VLM（假 load/unload）的池，避免真实拉起任何服务。"""
    from infra.resources import ResourceKind, ResourcePool, ResourceSpec

    pool = ResourcePool(max_concurrent=1)
    state = {"load_calls": 0, "unload_calls": 0}

    def _load():
        state["load_calls"] += 1
        return True

    def _unload():
        state["unload_calls"] += 1
        return True

    pool.register_resource(
        "vlm",
        ResourceSpec(
            kind=ResourceKind.VLM,
            display_name="测试 VLM",
            base_url="http://127.0.0.1:4503/v1",
            resident=True,
            immediate=False,
            idle_timeout=900,
            extra={"managed": True},
        ),
        _load,
        _unload,
    )
    pool._specs["vlm"].extra["managed"] = True
    return pool, state


def test_vlm_lease_triggers_lazy_start(clean_pool):
    """**按需拉起**：借租约才加载，租约期间不会重复加载。"""
    from apps.dsn_study.models.vlm_service import vlm_lease

    pool, state = clean_pool
    assert pool.snapshot()["vlm"]["loaded"] is False

    with vlm_lease(pool=pool) as lease:
        assert lease.name == "vlm"
        assert state["load_calls"] == 1
        assert pool.snapshot()["vlm"]["loaded"] is True

    # 归还租约后服务仍驻留（immediate=False），等空闲回收才停
    assert state["unload_calls"] == 0
    assert pool.snapshot()["vlm"]["loaded"] is True


def test_vlm_lease_raises_when_not_registered():
    """VLM 没注册时必须明确报错，而不是静默回退云端。"""
    from apps.dsn_study.models.vlm_service import VLMUnavailable, vlm_lease
    from infra.resources import ResourcePool

    pool = ResourcePool(max_concurrent=1)
    with pytest.raises(VLMUnavailable):
        with vlm_lease(pool=pool):
            pass


def test_vlm_disabled_raises(monkeypatch):
    from apps.dsn_study.config import Config
    from apps.dsn_study.models.vlm_service import VLMUnavailable, vlm_lease

    monkeypatch.setattr(Config, "VLM_ENABLED", False, raising=False)
    with pytest.raises(VLMUnavailable):
        with vlm_lease():
            pass


def test_local_vision_model_points_at_local_endpoint(monkeypatch):
    from apps.dsn_study.config import Config
    from apps.dsn_study.models.vlm_service import local_vision_model

    monkeypatch.setattr(Config, "VLM_BASE_URL", "http://127.0.0.1:4503/v1",
                        raising=False)
    vm = local_vision_model()
    assert vm.base_url == "http://127.0.0.1:4503/v1"
    assert vm.model_name == Config.VLM_MODEL_NAME
    # 本地服务不校验密钥，不应带云端的 Authorization 头
    assert not vm.api_key


# ── 4. 空闲回收阈值的两级开关 ──

def test_vlm_idle_timeout_follows_pool_switch(monkeypatch):
    from apps.dsn_study.config import Config
    from apps.dsn_study.models.resource_setup import _vlm_idle_timeout

    monkeypatch.setattr(Config, "VOICE_IDLE_SHUTDOWN", True, raising=False)
    monkeypatch.setattr(Config, "VLM_IDLE_SHUTDOWN", True, raising=False)
    monkeypatch.setattr(Config, "VLM_IDLE_TIMEOUT", 900, raising=False)
    assert _vlm_idle_timeout() == 900

    # VLM 自己的开关关掉 → 常驻不回收
    monkeypatch.setattr(Config, "VLM_IDLE_SHUTDOWN", False, raising=False)
    assert _vlm_idle_timeout() == 0


def test_pool_level_switch_disables_all_idle(monkeypatch):
    """池级总开关关闭 → 语音与视觉都不带空闲阈值，回收器也不启用。"""
    from apps.dsn_study.config import Config
    from apps.dsn_study.models.resource_setup import _idle_timeout, _vlm_idle_timeout

    monkeypatch.setattr(Config, "VOICE_IDLE_SHUTDOWN", False, raising=False)
    monkeypatch.setenv("RESOURCE_IDLE_SHUTDOWN", "")
    assert _idle_timeout("tts") == 0
    assert _idle_timeout("asr") == 0
    assert _vlm_idle_timeout() == 0

    # 显式打开池级开关 → 语音资源仍受语音级开关约束（这里是关的）
    monkeypatch.setenv("RESOURCE_IDLE_SHUTDOWN", "true")
    assert _idle_timeout("tts") == 0
    # 但视觉资源有自己的开关，可以独立参与回收
    monkeypatch.setattr(Config, "VLM_IDLE_SHUTDOWN", True, raising=False)
    monkeypatch.setattr(Config, "VLM_IDLE_TIMEOUT", 900, raising=False)
    assert _vlm_idle_timeout() == 900


def test_no_reaper_when_pool_switch_off(monkeypatch):
    """池级总开关关闭 → 不启用回收器。"""
    from apps.dsn_study.config import Config
    from apps.dsn_study.models import resource_setup as rs

    monkeypatch.setattr(Config, "VOICE_IDLE_SHUTDOWN", False, raising=False)
    monkeypatch.setattr(Config, "TTS_AUTOSTART", False, raising=False)
    monkeypatch.setattr(Config, "ASR_AUTOSTART", False, raising=False)
    monkeypatch.setattr(Config, "ASR_WARMUP_ON_LOAD", False, raising=False)
    monkeypatch.setenv("RESOURCE_IDLE_SHUTDOWN", "")

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


# ── 5. 入库 OCR 走本地 ──

def test_ocr_pages_uses_local_vlm(tmp_path, monkeypatch):
    """ocr_pages 必须借本地 VLM 租约并把请求打到本地端点。"""
    from apps.dsn_study.models import vlm_service
    from apps.dsn_study.question_bank.paper_import import PaperImporter

    calls = {"lease": 0, "asked": [], "base_url": ""}

    class _FakeVM:
        def encode_image(self, path):
            return "data:image/jpeg;base64,AAAA"

        def ask(self, data_url, prompt, max_tokens=4096, temperature=0.1):
            calls["asked"].append(prompt)
            return "1. 题目正文\n\n<!-- ANSWER -->"

    def _fake_lease(pool=None, timeout=None):
        calls["lease"] += 1

        class _Ctx:
            def __enter__(self):
                return object()

            def __exit__(self, *a):
                return False

        return _Ctx()

    def _fake_client(timeout=None):
        calls["base_url"] = "http://127.0.0.1:4503/v1"
        return _FakeVM()

    monkeypatch.setattr(vlm_service, "vlm_lease", _fake_lease)
    monkeypatch.setattr(vlm_service, "local_vision_model", _fake_client)

    img = tmp_path / "question_01.jpg"
    img.write_bytes(b"\xff\xd8\xff")

    imp = PaperImporter(workspace=str(tmp_path / "ws"))
    pages = imp.ocr_pages([str(img)])

    assert calls["lease"] == 1, "OCR 必须借一次本地 VLM 租约"
    assert calls["base_url"] == "http://127.0.0.1:4503/v1"
    assert len(calls["asked"]) == 1
    assert len(pages) == 1
    assert pages[0]["marked_answer"] is True
