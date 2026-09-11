# tests/test_orchestrator.py
# 统一模型路由器与双轨制调度系统 (ModelOrchestrator) 完整测试。

from __future__ import annotations

import os
import pytest
from unittest.mock import MagicMock, patch

from harness.orchestrator import (
    ChatMessage,
    ChatResponse,
    IChatClient,
    LlamaServerConfig,
    ModelOrchestrator,
    ModelSourceType,
    ModelProviderRegistry,
)


@pytest.fixture(autouse=True)
def clean_orchestrator():
    ModelOrchestrator.reset_instance()
    yield
    ModelOrchestrator.reset_instance()


def test_orchestrator_singleton_and_slots():
    """测试 Orchestrator 单例与最大插槽数配置。"""
    orch = ModelOrchestrator.get_instance(max_concurrent_slots=2)
    assert orch.max_concurrent_slots == 2
    orch.max_concurrent_slots = 3
    assert orch.max_concurrent_slots == 3
    assert orch._scheduler.max_concurrent == 3


def test_orchestrator_register_and_routing():
    """测试本地 llama.cpp、LMStudio 与 OpenAI API 三种模型的注册与路由状态。"""
    orch = ModelOrchestrator.get_instance(max_concurrent_slots=1)

    # 1. 注册本地 llama.cpp 模型
    llama_cfg = LlamaServerConfig(
        binary_path="/mock/bin/llama-server",
        model_path="/mock/model.gguf",
        port=8080,
    )
    orch.register_local_llamacpp("local-qwen", llama_cfg, priority=80)

    # 2. 注册 LMStudio 调度模型
    orch.register_api_lmstudio("lmstudio-gemma", base_url="http://localhost:4501", priority=60)

    # 3. 注册 OpenAI API 模型
    orch.register_api_openai("openai-deepseek", api_key="sk-test", base_url="https://api.test.com/v1")

    status = orch.status()
    assert status["max_concurrent_slots"] == 1
    assert status["total_models"] == 3
    names = [m["name"] for m in status["models"]]
    assert "local-qwen" in names
    assert "lmstudio-gemma" in names
    assert "openai-deepseek" in names

    # 验证本地与调度属性
    qwen_info = next(m for m in status["models"] if m["name"] == "local-qwen")
    assert qwen_info["is_local"] is True
    assert qwen_info["is_scheduled"] is True
    assert qwen_info["priority"] == 80

    openai_info = next(m for m in status["models"] if m["name"] == "openai-deepseek")
    assert openai_info["is_local"] is False
    assert openai_info["is_scheduled"] is False  # 不占用本地硬件插槽


def test_orchestrator_invoke_delegates_to_client():
    """测试统一 invoke 调用入口。"""
    orch = ModelOrchestrator.get_instance(max_concurrent_slots=1)
    orch.register_api_openai("mock-api", api_key="sk-test", base_url="https://api.test.com/v1")

    client = orch.get_client("mock-api")
    with patch.object(client, "invoke", return_value=ChatResponse(content="测试回复", model="mock-api")) as mock_invoke:
        resp = orch.invoke([ChatMessage.user("hello")], model_name="mock-api")
        assert resp.content == "测试回复"
        mock_invoke.assert_called_once()


def test_orchestrator_slot_eviction_between_local_models():
    """测试多个本地受管模型在达到最大插槽数时的优先级排队与替换。"""
    orch = ModelOrchestrator.get_instance(max_concurrent_slots=1)
    events = []

    cfg1 = LlamaServerConfig(binary_path="/mock/bin/llama-server", model_path="/mock/m1.gguf")
    cfg2 = LlamaServerConfig(binary_path="/mock/bin/llama-server", model_path="/mock/m2.gguf")

    orch.register_local_llamacpp("m1", cfg1, priority=90)
    orch.register_local_llamacpp("m2", cfg2, priority=30, immediate=True)

    c1 = orch.get_client("m1")
    c2 = orch.get_client("m2")

    with patch.object(orch._specs["m1"].launcher, "start", side_effect=lambda **kw: events.append("load_m1") or True):
        with patch.object(orch._specs["m1"].launcher, "stop", side_effect=lambda **kw: events.append("unload_m1") or True):
            with patch.object(orch._specs["m2"].launcher, "start", side_effect=lambda **kw: events.append("load_m2") or True):
                with patch.object(orch._specs["m2"].launcher, "stop", side_effect=lambda **kw: events.append("unload_m2") or True):
                    # 加载 m1
                    orch.load_model("m1")
                    # 使用调度器运行 m2 (immediate 抢占 m1)
                    with orch._scheduler.use("m2", timeout=1, immediate=True):
                        pass

    assert "load_m1" in events
    assert "unload_m1" in events
    assert "load_m2" in events


def test_provider_registry_bridges_to_orchestrator():
    """测试 ModelProviderRegistry 自动解析 Orchestrator 中的模型。"""
    orch = ModelOrchestrator.get_instance()
    orch.register_api_openai("bridge-model", api_key="sk-test", base_url="https://api.test.com/v1")

    reg = ModelProviderRegistry()
    client = reg.get_chat_client("bridge-model")
    assert isinstance(client, IChatClient)
    assert client.model == "bridge-model"
