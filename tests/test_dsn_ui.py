# tests/test_dsn_ui.py
# DSN-UI Web 服务端与 temp/ui_template 全量 API 协议自动化测试。

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from apps.dsn_ui.engine import DSNUIEngine
from apps.dsn_ui.server import create_app
from harness.orchestrator import ChatResponse, ModelOrchestrator


@pytest.fixture
def client():
    ModelOrchestrator.reset_instance()
    engine = DSNUIEngine(max_concurrent_slots=2)
    # 注册测试模型
    engine.orchestrator.register_api_openai(
        name="test-gpt",
        api_key="sk-dummy",
        base_url="https://api.openai.com/v1",
    )
    app = create_app(engine)
    with TestClient(app) as c:
        yield c
    ModelOrchestrator.reset_instance()


def test_health_check(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "app": "dsn_ui"}


def test_props_api_for_ui_template(client):
    """验证 /props 接口满足 temp/ui_template 的 PropsService 契约。"""
    res = client.get("/props")
    assert res.status_code == 200
    data = res.json()
    assert data["role"] == "router"
    assert "default_generation_settings" in data
    assert "params" in data["default_generation_settings"]
    assert data["total_slots"] >= 1


def test_models_list_apis(client):
    """验证 /models 与 /v1/models 满足 temp/ui_template 的 ModelsService 契约。"""
    for endpoint in ("/models", "/v1/models"):
        res = client.get(endpoint)
        assert res.status_code == 200
        data = res.json()
        assert data["object"] == "list"
        assert len(data["data"]) >= 1
        model_entry = next(m for m in data["data"] if m["id"] == "test-gpt")
        assert "status" in model_entry
        assert "value" in model_entry["status"]
        assert "architecture" in model_entry


def test_models_load_and_unload_apis(client):
    """验证 /models/load 与 /models/unload 端点。"""
    res_load = client.post("/models/load", json={"model": "test-gpt"})
    assert res_load.status_code == 200
    assert res_load.json()["success"] is True

    res_unload = client.post("/models/unload", json={"model": "test-gpt"})
    assert res_unload.status_code == 200
    assert res_unload.json()["success"] is True


def test_slots_api(client):
    """验证 /slots 槽位端点。"""
    res = client.get("/slots")
    assert res.status_code == 200
    slots = res.json()
    assert isinstance(slots, list)
    assert len(slots) >= 1
    assert "is_processing" in slots[0]


def test_system_resources_api(client):
    """验证 /api/system/resources 接口返回 RAM、CPU 与 GPU 数据。"""
    res = client.get("/api/system/resources")
    assert res.status_code == 200
    data = res.json()
    assert "ram" in data
    assert "cpu" in data
    assert "gpus" in data
    assert "orchestrator" in data


def test_settings_api(client):
    """验证 /api/settings 接口读取与更新。"""
    res = client.get("/api/settings")
    assert res.status_code == 200
    data = res.json()
    assert "orchestrator" in data
    assert "memory" in data
    assert "voice" in data

    update_res = client.post("/api/settings", json={"orchestrator": {"max_concurrent_slots": 3}})
    assert update_res.status_code == 200


def test_v1_chat_completions(client):
    """验证 /v1/chat/completions 推理。"""
    with patch.object(
        ModelOrchestrator.get_instance().get_client("test-gpt"),
        "invoke",
        return_value=ChatResponse(content="Hello from DSN-UI", reasoning_content="think: ok", model="test-gpt"),
    ):
        res = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-gpt",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": False,
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["choices"][0]["message"]["content"] == "Hello from DSN-UI"
        assert data["choices"][0]["message"]["reasoning_content"] == "think: ok"


def test_static_ui_template_assets(client):
    """验证 temp/ui_template 前端静态文件（HTML/SPA）托管。"""
    res = client.get("/")
    assert res.status_code == 200
    assert "llama-ui" in res.text or "sveltekit" in res.text or "<!doctype html>" in res.text

    manifest_res = client.get("/manifest.webmanifest")
    assert manifest_res.status_code == 200
