# tests/test_harness_agent_runtime.py
from __future__ import annotations

from harness import AgentRuntime
from harness.models.base import ChatResponse, ToolCall
from harness.models.provider import ModelProviderRegistry
from harness.models.stub import StubChatClient


def _two_step_client(tool_name, tool_args, final_text):
    return StubChatClient(responses=[
        ChatResponse(content="", tool_calls=[ToolCall(id="1", name=tool_name, arguments=tool_args)]),
        ChatResponse(content=final_text, model="stub"),
    ])


def test_agent_runtime_register_and_run():
    client = _two_step_client("calc.add", {"a": 1, "b": 2}, "等于 3")
    rt = AgentRuntime(client)
    rt.register_tool("calc.add", "加法", lambda a, b: a + b,
                     {"type": "object", "properties": {"a": {}, "b": {}}})
    reply = rt.run("1+2")
    assert reply == "等于 3"
    assert rt.memory.count() == 1


def test_agent_runtime_sessions():
    client = StubChatClient(responses=[ChatResponse(content="hi", model="stub")])
    rt = AgentRuntime(client)
    c1 = rt.session("s1")
    c2 = rt.session("s1")
    assert c1 is c2
    c3 = rt.session("other")
    assert c3 is not c1


def test_model_provider_registry():
    reg = ModelProviderRegistry()
    reg.register_chat("main", lambda: StubChatClient())
    client = reg.get_chat_client("main")
    assert isinstance(client, StubChatClient)
    # 同一 key 返回同一实例（缓存）
    assert reg.get_chat_client("main") is client
    assert "main" in reg.chat_keys()


def test_model_provider_missing_raises():
    import pytest
    reg = ModelProviderRegistry()
    with pytest.raises(KeyError):
        reg.get_chat_client("nope")
