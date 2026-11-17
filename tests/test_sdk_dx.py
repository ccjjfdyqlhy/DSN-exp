# tests/test_sdk_dx.py
# SDK 开发者体验（DX）改进的回归测试。
#
# 这组用例守的是「上手时最容易踩、且不报错」的几件事：
#   * 工具装饰器在哪儿都能 import；
#   * Agent 真的把工具交给了模型（曾经静默丢失）；
#   * 用户工具能拿到自己注入的应用状态；
#   * run() 的结果能当字符串用；
#   * create_agent 的参数只有前 7 个是常用的；
#   * 多智能体一行能起一个 Team。

from __future__ import annotations

import asyncio

import pytest

from harness import Agent, Team, create_agent, tool
from harness.agent.loop import AgentRunResult
from harness.tools import ToolDeps, current_deps
from harness.tools.context import ToolContext
from infra.models.base import ToolCall
from infra.orchestrator import ChatResponse, StubChatClient


# ── ① 工具装饰器：三个导入路径都通 ──────────────────────────────────────

def test_tool_decorator_is_importable_from_every_obvious_path():
    from harness import tool as t_top
    from harness.sdk import tool as t_sdk
    from harness.tools import tool as t_tools

    assert t_top is t_sdk is t_tools


def test_tool_decorator_builds_a_working_tool():
    @tool
    def add(a: int, b: int) -> int:
        """把两个数相加"""
        return a + b

    assert add.name == "add"
    assert add.parameters["properties"]["a"]["type"] == "integer"


# ── ② SDK 曾静默丢弃用户工具（DX-2026-11-18 修复）────────────────────

def test_agent_registers_user_tools_into_the_loop():
    """回归：Agent(client, tools=[...]) 的工具必须真的进到 loop 里。

    原来合并时写的是 `if self._assembled.loop.tools:`，而空注册表是 falsy
    → 用户工具从未注册 → 模型收不到工具 schema → 工具调用永不发生，
    且没有任何报错。
    """
    @tool
    def ping() -> str:
        """ping"""
        return "pong"

    agent = Agent(StubChatClient(responses=[ChatResponse(content="hi")]),
                  tools=[ping])
    assert "ping" in agent._assembled.loop.tools


def test_model_actually_sees_the_tool_schema():
    """模型侧必须收到工具 schema（上一个用例的可见后果）。"""
    seen: list = []

    def respond(messages, tools):
        seen.append(tools or [])
        return ChatResponse(content="ok")

    @tool
    def ping() -> str:
        """ping"""
        return "pong"

    agent = Agent(StubChatClient(respond=respond), tools=[ping])
    agent.run("ping 一下")
    assert seen and seen[0], "模型第一次调用没收到任何工具 schema"


def test_tool_call_runs_the_registered_tool():
    calls = {"n": 0}

    def respond(messages, tools):
        calls["n"] += 1
        if calls["n"] == 1:
            return ChatResponse(content="", tool_calls=[
                ToolCall(id="c1", name="ping", arguments={})])
        return ChatResponse(content="done")

    @tool
    def ping() -> str:
        """ping"""
        return "pong"

    agent = Agent(StubChatClient(respond=respond), tools=[ping])
    result = agent.run("ping 一下")
    assert [t.name for t in result.tool_executions] == ["ping"]
    assert result.tool_executions[0].result.output == "pong"


# ── ③ 依赖注入：用户工具拿到自己的应用状态 ────────────────────────────

def test_tool_can_reach_injected_deps():
    db: list = []

    @tool
    def save(text: str) -> str:
        """保存一条"""
        deps = current_deps()
        assert deps is not None
        deps.extra["db"].append(text)
        return f"saved {len(deps.extra['db'])}"

    calls = {"n": 0}

    def respond(messages, tools):
        calls["n"] += 1
        if calls["n"] == 1:
            return ChatResponse(content="", tool_calls=[
                ToolCall(id="c1", name="save", arguments={"text": "x"})])
        return ChatResponse(content="ok")

    agent = Agent(StubChatClient(respond=respond), tools=[save],
                  deps={"extra": {"db": db}})
    agent.run("save x")
    assert db == ["x"]


def test_deps_accept_a_tooldeps_instance():
    deps = ToolDeps(extra={"db": []})
    agent = Agent(StubChatClient(responses=[ChatResponse(content="x")]),
                  tools=[], deps=deps)
    assert agent.spec.tool_deps == {"extra": {"db": []}}


def test_current_deps_is_none_without_injection():
    ctx = ToolContext()
    assert ctx.deps is None


# ── ④ run() 的结果可以当字符串用 ───────────────────────────────────────

def test_run_result_behaves_like_a_string():
    result = AgentRunResult(reply="今天晴")
    assert str(result) == "今天晴"
    assert result == "今天晴"
    assert result.text == "今天晴"
    assert "晴" in result
    assert bool(result) is True
    assert len(result) == 3


def test_run_result_compares_with_another_result():
    assert AgentRunResult(reply="a") == AgentRunResult(reply="a")
    assert AgentRunResult(reply="a") != AgentRunResult(reply="b")


def test_agent_run_result_is_string_like():
    agent = Agent(StubChatClient(responses=[ChatResponse(content="答案")]))
    result = agent.run("问题")
    assert result == "答案"
    assert str(result) == "答案"


# ── ⑤ create_agent：常用参数收敛到前 7 个 ─────────────────────────────

def test_create_agent_routes_options():
    agent = create_agent(
        client=StubChatClient(responses=[ChatResponse(content="x")]),
        max_steps=5, enable_memory=True, workspace="/tmp",
    )
    assert agent.spec.max_steps == 5
    assert agent.spec.memory is True
    assert agent.spec.workspace == "/tmp"


def test_create_agent_forwards_unknown_options_to_the_model_client():
    agent = create_agent(model="deepseek-chat", api_key="sk-x", temperature=0.3)
    assert agent.spec.name == "embedded-agent"


def test_create_agent_builds_budget_config():
    agent = create_agent(client=StubChatClient(responses=[ChatResponse(content="x")]),
                         budget_cap=1.5, token_cap=1000)
    assert agent.spec.budget == {"cost_cap": 1.5, "token_cap": 1000}


# ── ⑥ Team：多智能体一行起 ────────────────────────────────────────────

def test_team_runs_a_turn_and_returns_the_reply():
    @tool
    def search(query: str) -> str:
        """搜索资料"""
        return "结果"

    async def scenario():
        client = StubChatClient(responses=[ChatResponse(content="总结如下")])
        async with Team(client, worker_tools=[search]) as team:
            return await team.run("查资料并总结")

    assert asyncio.run(scenario()) == "总结如下"


def test_team_registers_worker_types():
    async def scenario():
        client = StubChatClient(responses=[ChatResponse(content="ok")])
        async with Team(client) as team:
            team.register_worker("researcher", system="你是研究员", tools=[])
            return team.manager.agent_type("researcher")

    spec = asyncio.run(scenario())
    assert spec is not None
    assert spec.name == "researcher"
    assert spec.system == "你是研究员"
