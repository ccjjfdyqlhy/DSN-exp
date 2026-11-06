# tests/test_infra_openai_client.py
"""infra/orchestrator/openai.py 的 OpenAI 兼容客户端测试。

重点是**强制 SSE 的网关**：实测有一批 newapi 系网关无视 stream=false，
直接返回 text/event-stream。openai SDK 这时给回来的是原始字符串而不是
Completion 对象——不兜住就直接炸（'str' object has no attribute 'choices'），
而教师链路（harness/learning/teacher.py）走的正是 invoke。
"""

from __future__ import annotations

from typing import Any

import pytest

from infra.orchestrator.openai import OpenAICompatClient


class _FakeDelta:
    def __init__(self, content=None, tool_calls=None, reasoning_content=None):
        self.content = content
        self.tool_calls = tool_calls
        self.reasoning_content = reasoning_content


class _FakeChoice:
    def __init__(self, delta, finish_reason=None):
        self.delta = delta
        self.finish_reason = finish_reason


class _FakeChunk:
    def __init__(self, content=None, tool_calls=None, reasoning_content=None,
                 finish_reason=None, usage=None):
        self.choices = [_FakeChoice(_FakeDelta(content, tool_calls, reasoning_content), finish_reason)]
        self.usage = usage


class _FakeToolCallDelta:
    def __init__(self, index, call_id, name, arguments):
        self.index = index
        self.id = call_id
        self.function = type("F", (), {"name": name, "arguments": arguments})()


class _FakeMessage:
    def __init__(self, content):
        self.content = content
        self.tool_calls = []
        self.reasoning_content = None


class _FakeCompletion:
    """普通（非流式）响应：choice.message.content。"""

    def __init__(self, content):
        choice = _FakeChoice(_FakeDelta(content), "stop")
        choice.message = _FakeMessage(content)
        self.choices = [choice]
        self.usage = None


class _FakeStream:
    """openai SDK 的流式响应是上下文管理器，假装它一下。"""

    def __init__(self, chunks):
        self._chunks = list(chunks)

    def __enter__(self):
        return iter(self._chunks)

    def __exit__(self, *exc):
        return False


class _FakeCompletions:
    """假装是 openai SDK 的 chat.completions。"""

    def __init__(self, sse_mode: bool):
        self.sse_mode = sse_mode
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            return _FakeStream([
                _FakeChunk(content="你", reasoning_content=" thinking…"),
                _FakeChunk(content="好"),
                _FakeChunk(finish_reason="stop",
                           usage=type("U", (), {"model_dump": lambda self: {"total_tokens": 7}})()),
            ])
        if self.sse_mode:
            # 网关无视 stream=false：SDK 交回的是原始文本，不是 Completion 对象
            return 'data: {"choices":[]}\n\ndata: [DONE]\n'
        return _FakeCompletion("普通响应")


class _FakeSDK:
    def __init__(self, sse_mode: bool):
        self.chat = type("Chat", (), {"completions": _FakeCompletions(sse_mode)})()


def _client(sse_mode: bool) -> tuple[OpenAICompatClient, _FakeCompletions]:
    client = OpenAICompatClient(api_key="k", base_url="https://example.invalid/v1", model="m")
    fake = _FakeSDK(sse_mode)
    client._client = fake
    return client, fake.chat.completions


def test_invoke_normal_json_response():
    client, _ = _client(sse_mode=False)
    resp = client.invoke([{"role": "user", "content": "hi"}])
    assert resp.content == "普通响应"
    assert resp.finish_reason == "stop"


def test_invoke_falls_back_to_stream_when_gateway_forces_sse():
    """网关强制 SSE 时，invoke 必须自己兜住（教师链路全靠它）。"""
    client, completions = _client(sse_mode=True)
    resp = client.invoke([{"role": "user", "content": "hi"}])

    assert resp.content == "你好", "应把 SSE 增量拼成一次普通响应"
    assert resp.finish_reason == "stop"
    # 第一次是非流式（被网关无视），第二次才是流式兜底
    assert len(completions.calls) == 2
    assert completions.calls[0].get("stream") is not True
    assert completions.calls[1].get("stream") is True
    # 思维链不能混进 content（框架约定：思维链单独走 reasoning_content）
    assert resp.reasoning_content == " thinking…"
    assert "thinking" not in resp.content


def test_invoke_stream_fallback_collects_tool_calls():
    client, _ = _client(sse_mode=True)

    class _ToolCompletions(_FakeCompletions):
        def create(self, **kwargs):
            self.calls.append(kwargs)
            if kwargs.get("stream"):
                return _FakeStream([
                    _FakeChunk(tool_calls=[_FakeToolCallDelta(0, "call_1", "read_file", '{"path":')]),
                    _FakeChunk(tool_calls=[_FakeToolCallDelta(0, None, None, '"a.txt"}')]),
                ])
            return 'data: [DONE]'

    fake = _FakeSDK(sse_mode=True)
    fake.chat.completions = _ToolCompletions(sse_mode=True)
    client._client = fake

    resp = client.invoke([{"role": "user", "content": "读文件"}])
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "read_file"
    assert resp.tool_calls[0].arguments == {"path": "a.txt"}


def test_invoke_stream_fallback_survives_broken_tool_arguments():
    """网关把参数切碎了：宁可给空参，也不要把半个 JSON 传下去。"""
    client, _ = _client(sse_mode=True)

    class _BadCompletions(_FakeCompletions):
        def create(self, **kwargs):
            self.calls.append(kwargs)
            if kwargs.get("stream"):
                return _FakeStream([_FakeChunk(tool_calls=[_FakeToolCallDelta(0, "c1", "f", '{"path":')])])
            return 'data: [DONE]'

    fake = _FakeSDK(sse_mode=True)
    fake.chat.completions = _BadCompletions(sse_mode=True)
    client._client = fake

    resp = client.invoke([{"role": "user", "content": "x"}])
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].arguments == {}
