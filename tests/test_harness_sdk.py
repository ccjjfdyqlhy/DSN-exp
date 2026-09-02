# tests/test_harness_sdk.py
# 测试 harness 作为 SDK 嵌入外部项目时的功能

import asyncio
import pytest

from harness import Agent, create_agent, tool, ToolResult
from harness.models.stub import StubChatClient
from harness.models.base import ChatMessage, ChatResponse, ToolCall


def test_sdk_tool_decorator():
    @tool
    def multiply(a: int, b: int) -> int:
        """两数相乘"""
        return a * b

    assert multiply.name == "multiply"
    assert "两数相乘" in multiply.description
    res = multiply.run(a=3, b=4)
    assert res.success is True
    assert res.output == 12


def test_sdk_create_agent_chat():
    stub = StubChatClient(responses=[
        ChatResponse(content="你好！我是通过 SDK 嵌入的助手。"),
        ChatResponse(content="第二轮回复"),
    ])
    agent = create_agent(client=stub, system_prompt="系统设定")

    reply = agent.chat("你好呀")
    assert reply == "你好！我是通过 SDK 嵌入的助手。"
    assert len(agent.conversation.messages) == 2
    assert agent.conversation.messages[0].content == "你好呀"
    assert agent.conversation.messages[1].content == "你好！我是通过 SDK 嵌入的助手。"

    # 第二轮对话
    reply2 = agent.chat("再见")
    assert reply2 == "第二轮回复"
    assert len(agent.conversation.messages) == 4


def test_sdk_agent_with_custom_tool():
    @tool
    def calc_area(width: int, height: int) -> int:
        """计算面积"""
        return width * height

    # 构造两轮交互：第一轮返回 tool_call，第二轮返回最终文本
    scripted = StubChatClient(responses=[
        ChatResponse(
            content="",
            tool_calls=[ToolCall(id="call_1", name="calc_area", arguments={"width": 10, "height": 20})],
        ),
        ChatResponse(content="计算得到面积为 200。"),
    ])

    agent = create_agent(
        client=scripted,
        tools=[calc_area],
    )

    reply = agent.chat("算一下 10 宽 20 高的面积")
    assert reply == "计算得到面积为 200。"
    assert agent.tools.has("calc_area")


def test_sdk_dynamic_add_tool():
    stub = StubChatClient(responses=[ChatResponse(content="ok")])
    agent = create_agent(client=stub)

    assert not agent.tools.has("my_dynamic_tool")

    def my_dynamic_tool(msg: str) -> str:
        return f"echo: {msg}"

    agent.add_tool(my_dynamic_tool)
    assert agent.tools.has("my_dynamic_tool")


@pytest.mark.asyncio
async def test_sdk_chat_stream():
    stub = StubChatClient(responses=[ChatResponse(content="流式回复文本")])
    agent = create_agent(client=stub)

    events = []
    async for ev in agent.chat_stream("测试流"):
        events.append(ev)

    assert len(events) > 0
    done_events = [e for e in events if e.kind == "done"]
    assert len(done_events) == 1
    assert done_events[0].reply == "流式回复文本"
    assert agent.conversation.messages[-1].content == "流式回复文本"


def test_sdk_stateless_run():
    stub = StubChatClient(responses=[ChatResponse(content="无状态单次运行")])
    agent = create_agent(client=stub)

    result = agent.run("单次任务")
    assert result.reply == "无状态单次运行"
    # run 不计入 conversation 历史
    assert len(agent.conversation.messages) == 0
