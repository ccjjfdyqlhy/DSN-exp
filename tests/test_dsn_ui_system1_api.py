"""dsn_ui 的 System-1 决策接口（/v1/decide）契约测试。

前端（decide.service.ts / DecisionPanel.svelte）依赖这里的响应字段，
所以契约必须被锁住：字段名、类型、错误码。

打桩：不连真实模型，用假客户端返回固定的 logprobs 分布。
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.dsn_ui import system1_api  # noqa: E402
from infra.decision.client import DecisionUnavailable, RawDecision  # noqa: E402


class _StubLauncher:
    def __init__(self, base_url="http://127.0.0.1:8090"):
        self.base_url = base_url
        self.running = True

    def is_running(self):
        return self.running


class _StubSpec:
    def __init__(self, model_path="/models/JEV-27B-VL.Q4_K_M.gguf", base_url="http://127.0.0.1:8090"):
        self.base_url = base_url
        self.launcher = _StubLauncher(base_url)
        self.llama_config = type("Cfg", (), {
            "model_path": model_path,
            "mmproj_path": "/models/JEV-27B-VL.mmproj.gguf",
        })()


class _StubOrchestrator:
    def __init__(self, specs):
        self._specs = specs
        self._scheduler = None

    def get_default_model(self):
        return next(iter(self._specs), None)


class _StubClient:
    model = "jev:test"

    def __init__(self, candidates=None, fail=False):
        self._candidates = candidates or {"Y": 0.9, "N": 0.1}
        self._fail = fail

    def candidates(self, messages, **kw):
        if self._fail:
            raise DecisionUnavailable("端点不可达")
        return RawDecision(candidates=dict(self._candidates), model="jev:test", latency_ms=12.0)

    def probe(self, expect_model_path=""):
        return True, ""


def _make_client(monkeypatch, *, candidates=None, fail=False, specs=None):
    specs = specs or {"jev:JEV-27B-VL": _StubSpec()}
    engine = type("Engine", (), {"orchestrator": _StubOrchestrator(specs)})()

    @contextmanager
    def _fake_backend(orchestrator, model_name, *, timeout=None):
        yield _StubClient(candidates=candidates, fail=fail)

    monkeypatch.setattr(system1_api, "orchestrator_decision_client", _fake_backend)
    monkeypatch.setattr(
        system1_api, "scan_jev_models",
        lambda: [type("M", (), {
            "model_path": "/models/JEV-27B-VL.Q4_K_M.gguf",
            "mmproj_path": "/models/JEV-27B-VL.mmproj.gguf",
        })()],
    )

    app = FastAPI()
    system1_api.register_system1_routes(app, engine)
    return TestClient(app)


# ── 决策主路径 ──

def test_decide_yes_no_returns_contract_fields(monkeypatch):
    client = _make_client(monkeypatch)
    r = client.post("/v1/decide", json={
        "type": "yes_no", "question": "威胁取消订阅吗？", "state": "邮件正文"})
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "yes_no"
    assert body["answer"] is True
    assert body["probability"] == pytest.approx(0.9)
    assert set(body["distribution"]) == {"Y", "N"}
    assert body["model"] == "jev:test"
    assert body["latency_ms"] == pytest.approx(12.0)
    assert "raw_candidates" in body


def test_decide_choice_returns_label(monkeypatch):
    client = _make_client(monkeypatch, candidates={"A": 0.7, "B": 0.3})
    r = client.post("/v1/decide", json={
        "type": "choice", "question": "分派给谁？", "options": ["billing", "technical"]})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "A"
    assert body["label"] == "billing"


def test_decide_score_returns_expectation(monkeypatch):
    client = _make_client(monkeypatch, candidates={"0": 0.2, "1": 0.2, "2": 0.2, "3": 0.4})
    r = client.post("/v1/decide", json={
        "type": "score", "question": "多紧急？", "max_score": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == 3
    assert body["expectation"] == pytest.approx(1.8)


# ── 错误路径 ──

def test_decide_rejects_unknown_type(monkeypatch):
    client = _make_client(monkeypatch)
    r = client.post("/v1/decide", json={"type": "wat"})
    assert r.status_code == 400


def test_decide_rejects_choice_without_options(monkeypatch):
    client = _make_client(monkeypatch)
    r = client.post("/v1/decide", json={"type": "choice", "question": "q"})
    assert r.status_code == 400


def test_decide_rejects_unknown_model(monkeypatch):
    client = _make_client(monkeypatch)
    r = client.post("/v1/decide", json={"type": "yes_no", "model": "nope"})
    assert r.status_code == 404


def test_decide_upstream_failure_is_502(monkeypatch):
    client = _make_client(monkeypatch, fail=True)
    r = client.post("/v1/decide", json={"type": "yes_no", "question": "q"})
    assert r.status_code == 502
    assert r.json()["error"]["type"] == "upstream_error"


# ── 能力探测 ──

def test_capabilities_reports_system1_for_decision_model(monkeypatch):
    client = _make_client(monkeypatch)
    r = client.get("/v1/decide/capabilities")
    assert r.status_code == 200
    body = r.json()
    assert body["system1"] is True
    assert body["supported_types"] == ["yes_no", "choice", "score"]
    assert body["max_choice_options"] == 256
    assert body["vision"] is True


def test_capabilities_disables_system1_for_plain_model(monkeypatch):
    """普通模型没有决策头 —— 概率没校准，必须报告不支持。"""
    specs = {"gemma:3-4b": _StubSpec(model_path="/models/gemma-3-4b-it-Q4_K_M.gguf")}
    client = _make_client(monkeypatch, specs=specs)
    r = client.get("/v1/decide/capabilities")
    body = r.json()
    assert body["system1"] is False
    assert body["supported_types"] == []
    assert body["max_choice_options"] == 0
