# tests/test_harness_models.py
# harness 模型契约测试：dsn 对话客户端符合 IChatClient，经 harness 提供商注册。

from __future__ import annotations

import asyncio

from harness.models import IChatClient, ChatMessage, ChatResponse, ModelProviderRegistry


def test_dsn_openai_chat_conforms_ichatclient():
    """dsn OpenAIChat 结构上符合 harness IChatClient。"""
    from apps.dsn.models.clients import OpenAIChat
    chat = OpenAIChat(api_key="test-key", model="m", api_url="http://x/v1")
    assert isinstance(chat, IChatClient), "OpenAIChat 未实现 IChatClient"
    assert chat.model == "m"


def test_dsn_openai_chat_invoke_normalizes_messages():
    """invoke 把 harness ChatMessage 归一化为 dict 并返回 ChatResponse。"""
    from apps.dsn.models.clients import OpenAIChat
    chat = OpenAIChat(api_key="test-key", model="m", api_url="http://x/v1")
    chat._call_and_append = lambda **kw: "你好，我是助手"
    resp = chat.invoke([ChatMessage.user("你好")])
    assert isinstance(resp, ChatResponse)
    assert resp.content == "你好，我是助手"
    assert chat.messages == [{"role": "user", "content": "你好"}]


def test_dsn_openai_chat_invoke_parses_tool_calls():
    """invoke 解析 last_tool_calls 为 harness ToolCall 列表。"""
    from apps.dsn.models.clients import OpenAIChat
    chat = OpenAIChat(api_key="test-key", model="m", api_url="http://x/v1")
    chat._call_and_append = lambda **kw: ""
    chat._last_message = {
        "role": "assistant", "content": "",
        "tool_calls": [{"id": "c1", "type": "function",
                        "function": {"name": "math.add", "arguments": "{\"a\": 1}"}}],
    }
    resp = chat.invoke([ChatMessage.user("1+1")])
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "math.add"
    assert resp.tool_calls[0].arguments == {"a": 1}


def test_dsn_lmstudio_chat_conforms_ichatclient():
    from apps.dsn.models.clients import LMStudioChat
    chat = LMStudioChat(base_url="http://localhost:9", managed=False)
    assert isinstance(chat, IChatClient), "LMStudioChat 未实现 IChatClient"
    assert chat.model == "lmstudio"  # 未指定模型时回退


def test_model_provider_registry_with_dsn_backends():
    """dsn 后端经 harness ModelProviderRegistry 注册并可解析为 IChatClient。"""
    from apps.dsn.models.clients import OpenAIChat
    reg = ModelProviderRegistry()
    reg.register_chat("openai", lambda: OpenAIChat(api_key="k", model="m", api_url="http://x/v1"))
    client = reg.get_chat_client("openai")
    assert isinstance(client, IChatClient)
    assert reg.chat_keys() == ["openai"]
