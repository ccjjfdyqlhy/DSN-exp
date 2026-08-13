# tests/test_harness_agent.py
from __future__ import annotations

import asyncio

from harness.agent import AgentLoop, NativeToolCallAdapter, TaggedToolCallAdapter
from harness.models.base import ChatMessage, ChatResponse, ToolCall
from harness.models.stub import StubChatClient
from harness.tools import ToolRegistry


def _make_loop(stub, tools, adapter=None, **kw):
    return AgentLoop(stub, tools, adapter=adapter, max_steps=kw.pop("max_steps", 5), **kw)


def test_agent_loop_native_single_tool_call():
    # 第一次调用返回工具调用，第二次返回最终文本
    stub = StubChatClient(responses=[
        ChatResponse(content="", tool_calls=[ToolCall(id="1", name="math.add", arguments={"a": 1, "b": 2})]),
        ChatResponse(content="结果是 3", model="stub"),
    ])
    tools = ToolRegistry()
    tools.register_tool("math.add", "加法", lambda a, b: a + b,
                        {"type": "object", "properties": {"a": {}, "b": {}}})

    loop = _make_loop(stub, tools)
    result = asyncio.run(loop.run_async([ChatMessage.user("1+2=?")]))

    assert result.reply == "结果是 3"
    assert len(result.tool_executions) == 1
    assert result.tool_executions[0].result.output == 3
    assert result.steps == 2


def test_agent_loop_no_tools_returns_directly():
    stub = StubChatClient(responses=[ChatResponse(content="直接回答", model="stub")])
    tools = ToolRegistry()
    loop = _make_loop(stub, tools)
    result = asyncio.run(loop.run_async([ChatMessage.user("hi")]))
    assert result.reply == "直接回答"
    assert result.tool_executions == []


def test_agent_loop_missing_tool_reports_error():
    stub = StubChatClient(responses=[
        ChatResponse(content="", tool_calls=[ToolCall(id="1", name="ghost", arguments={})]),
        ChatResponse(content="工具不可用", model="stub"),
    ])
    tools = ToolRegistry()
    loop = _make_loop(stub, tools)
    result = asyncio.run(loop.run_async([ChatMessage.user("x")]))
    assert result.reply == "工具不可用"
    assert not result.tool_executions[0].result.success


def test_tagged_adapter_parse_and_loop():
    raw = '好的。\n<toolcall>\n{"name": "math.add", "arguments": {"a": 3, "b": 4}}\n</toolcall>'
    stub = StubChatClient(responses=[
        ChatResponse(content=raw, model="stub"),
        ChatResponse(content="和是 7", model="stub"),
    ])
    tools = ToolRegistry()
    tools.register_tool("math.add", "加法", lambda a, b: a + b,
                        {"type": "object", "properties": {"a": {}, "b": {}}})
    loop = _make_loop(stub, tools, adapter=TaggedToolCallAdapter())
    result = asyncio.run(loop.run_async([ChatMessage.user("3+4")]))
    assert result.reply == "和是 7"
    assert result.tool_executions[0].result.output == 7


def test_progress_callbacks_fire():
    stub = StubChatClient(responses=[
        ChatResponse(content="", tool_calls=[ToolCall(id="1", name="t", arguments={})]),
        ChatResponse(content="done", model="stub"),
    ])
    tools = ToolRegistry()
    tools.register_tool("t", "t", lambda: None)
    progress = []
    loop = _make_loop(stub, tools, on_progress=lambda s, m, names: progress.append((s, names)))
    asyncio.run(loop.run_async([ChatMessage.user("x")]))
    assert progress, "progress 回调应被触发"


def test_hit_max_steps():
    # 模型永远返回工具调用 → 达到步数上限
    responses = [ChatResponse(content="", tool_calls=[ToolCall(id=str(i), name="t", arguments={})])
                 for i in range(10)]
    stub = StubChatClient(responses=responses)
    tools = ToolRegistry()
    tools.register_tool("t", "t", lambda: None)
    loop = _make_loop(stub, tools, max_steps=3)
    result = asyncio.run(loop.run_async([ChatMessage.user("x")]))
    assert result.hit_max_steps is True
    assert len(result.tool_executions) == 3
