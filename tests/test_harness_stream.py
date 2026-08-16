# tests/test_harness_stream.py
# 流式工具调用（AgentLoop.run_stream）单元测试。

from __future__ import annotations

import asyncio

import pytest

from harness import ToolRegistry
from harness.agent import AgentLoop, StreamEvent
from harness.models.base import ChatMessage, ChatResponse


class StreamingClient:
    """模拟 OpenAI 流式：文本增量 + tool_calls delta 分散在多个 chunk。"""

    def __init__(self, rounds):
        self.rounds = rounds  # [ (content_parts, tool_delta_chunks), ... ]
        self.calls = 0

    model = "fake"

    async def stream(self, messages, tools=None, **kw):
        self.calls += 1
        idx = self.calls - 1
        content, tool_chunks = self.rounds[idx]
        for part in content:
            yield part
        for tc in tool_chunks:
            yield {"tool_calls": [tc]}


def _delta(tc_index, tc_id, name, args):
    return {"index": tc_index, "id": tc_id, "name": name, "arguments": args}


def test_run_stream_text_only():
    """纯文本流：只产 delta + reply + done。"""
    client = StreamingClient([(["你", "好"], [])])
    loop = AgentLoop(client, None, max_steps=3)
    events = asyncio.run(_collect(loop, [ChatMessage.user("hi")]))
    kinds = [e.kind for e in events]
    assert "delta" in kinds and "reply" in kinds and "done" in kinds
    reply = next(e for e in events if e.kind == "reply")
    assert reply.reply == "你好"


def test_run_stream_executes_tools():
    """流式工具调用：delta 累积 → tool_call → tool_result → 第二轮 → reply。"""
    reg = ToolRegistry()
    reg.register_tool("math.add", "加法", lambda a, b: a + b,
                      {"type": "object", "properties": {"a": {}, "b": {}}})
    client = StreamingClient([
        # 第一轮：文本 + 分片的 tool_calls delta
        (["计算"], [
            _delta(0, "c1", "math.add", '{"a":'),
            _delta(0, "", "", " 1, "),
            _delta(0, "", "", '"b": 2}'),
        ]),
        # 第二轮：纯文本结束
        (["结果是 3"], []),
    ])
    loop = AgentLoop(client, reg, max_steps=3)
    events = asyncio.run(_collect(loop, [ChatMessage.user("1+2=?")]))
    kinds = [e.kind for e in events]
    assert "tool_call" in kinds
    assert "tool_result" in kinds
    tc = next(e for e in events if e.kind == "tool_call")
    assert tc.tool_call["name"] == "math.add"
    tr = next(e for e in events if e.kind == "tool_result")
    assert tr.tool_result["success"] is True
    assert tr.tool_result["output"] == 3
    reply = next(e for e in events if e.kind == "reply")
    assert reply.reply == "结果是 3"
    assert client.calls == 2


def test_run_stream_fallback_invoke():
    """客户端无 stream → 回退 invoke（整体作为 delta）。"""
    class PlainClient:
        model = "fake"

        def invoke(self, messages, tools=None, **kw):
            return ChatResponse(content="plain reply")

    loop = AgentLoop(PlainClient(), None, max_steps=2)
    events = asyncio.run(_collect(loop, [ChatMessage.user("hi")]))
    reply = next(e for e in events if e.kind == "reply")
    assert reply.reply == "plain reply"


def test_run_stream_toolbox_integration():
    """流式路径下 toolbox 两阶段激活生效：首轮只有 toolbox 索引。"""
    from harness.tools.toolbox import RegistryIndexSource, ToolboxManager

    reg = ToolRegistry()
    reg.register_tool("demo.echo", "回声", lambda x: x,
                      {"type": "object", "properties": {"x": {}}})
    seen_schemas = []

    class TbClient:
        model = "fake"

        async def stream(self, messages, tools=None, **kw):
            seen_schemas.append(tools or [])
            if len(seen_schemas) == 1:
                yield {"tool_calls": [_delta(0, "t1", "toolbox", '{"ids": ["demo.echo"]}')]}
            else:
                yield "完成"

    toolbox = ToolboxManager(RegistryIndexSource(reg))
    loop = AgentLoop(TbClient(), reg, toolbox=toolbox, max_steps=3)
    events = asyncio.run(_collect(loop, [ChatMessage.user("hi")]))
    assert len(seen_schemas[0]) == 1
    assert seen_schemas[0][0]["name"] == "toolbox"
    # 发给模型的是 wire 名（demo.echo → demo__echo）
    assert [s["name"] for s in seen_schemas[1]] == ["toolbox", "demo__echo"]
    assert any(e.kind == "reply" and e.reply == "完成" for e in events)


def test_run_stream_sync_generator_streams_incrementally():
    """同步生成器必须逐块 yield，不能先在线程里缓冲完整个流再返回。"""
    class SyncGenClient:
        model = "fake"

        def __init__(self):
            self.advanced_past_first = False

        def stream(self, messages, tools=None, **kw):
            yield "a"
            self.advanced_past_first = True
            yield "b"

    client = SyncGenClient()
    loop = AgentLoop(client, None, max_steps=2)

    async def consume():
        async for e in loop.run_stream([ChatMessage.user("hi")]):
            if e.kind == "delta" and e.content == "a":
                # 收到第一个 delta 时，生成器不应已被整个消费完。
                assert client.advanced_past_first is False

    asyncio.run(consume())
    assert client.advanced_past_first is True


async def _collect(loop, msgs):
    events = []
    async for e in loop.run_stream(msgs):
        events.append(e)
    return events
