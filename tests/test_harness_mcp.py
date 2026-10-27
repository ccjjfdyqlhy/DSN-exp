# tests/test_harness_mcp.py
# 外部 MCP 工具源（harness/tools/mcp.py）单元测试。
#
# 单元用例全部经 StubManager 注入桩会话（覆写 _open_session），
# 不起子进程、不碰网络；真实 stdio 往返见文末 integration 用例。

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness import Agent
from harness.tools import MCPManager, MCPServerConfig, ToolRegistry, to_wire_name
from harness.tools.toolbox import RegistryIndexSource, ToolboxManager

REPO_ROOT = Path(__file__).resolve().parents[1]


# ── 桩会话：实现 MCPManager 用到的三个 ClientSession 方法 ──

def _remote_tool(name: str, description: str = "", schema: dict | None = None):
    return SimpleNamespace(
        name=name,
        description=description or f"{name} 描述",
        inputSchema=schema or {"type": "object",
                               "properties": {"x": {"type": "integer"}}},
    )


def _text(text: str):
    return SimpleNamespace(type="text", text=text)


class FakeSession:
    """可编程桩会话。responses: {(tool, kwargs_json): CallToolResult 形对象}。"""

    def __init__(self, tools=None, responses=None, call_fn=None, delay=0.0):
        self.tools = tools or []
        self.responses = responses or {}
        self.call_fn = call_fn
        self.delay = delay
        self.initialized = False
        self.calls: list[tuple[str, dict]] = []

    async def initialize(self):
        self.initialized = True

    async def list_tools(self, cursor=None):
        return SimpleNamespace(tools=list(self.tools), nextCursor=None)

    async def call_tool(self, name, arguments=None, read_timeout_seconds=None):
        self.calls.append((name, dict(arguments or {})))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.call_fn is not None:
            return self.call_fn(name, arguments or {})
        import json
        return self.responses.get((name, json.dumps(arguments, sort_keys=True)),
                                  SimpleNamespace(content=[_text("ok")],
                                                  structuredContent=None,
                                                  isError=False))


class StubManager(MCPManager):
    """用桩会话替换协议边界（_open_session），按服务器名取会话。"""

    def __init__(self, servers, sessions: dict[str, FakeSession]):
        super().__init__(servers)
        self._stub_sessions = sessions
        self.connect_count: dict[str, int] = {}

    async def _open_session(self, cfg, stack):
        self.connect_count[cfg.name] = self.connect_count.get(cfg.name, 0) + 1
        return self._stub_sessions[cfg.name]


def _stdio_cfg(name: str = "srv", **kw) -> MCPServerConfig:
    return MCPServerConfig(name=name, transport="stdio", command="python", **kw)


# ── 配置解析 ──

def test_config_validation():
    with pytest.raises(ValueError, match="name"):
        MCPServerConfig(name="")
    with pytest.raises(ValueError, match="传输类型"):
        MCPServerConfig(name="a", transport="grpc")
    with pytest.raises(ValueError, match="command"):
        MCPServerConfig(name="a", transport="stdio")


def test_config_env_expansion(monkeypatch):
    monkeypatch.setenv("MCP_TEST_TOKEN", "s3cret")
    monkeypatch.setenv("MCP_TEST_URL", "http://10.0.0.1:9000/mcp")
    cfg = MCPServerConfig.from_dict({
        "name": "remote", "transport": "http",
        "url": "${MCP_TEST_URL}",
        "headers": {"Authorization": "Bearer ${MCP_TEST_TOKEN}"},
        "args": ["--flag", "${MCP_TEST_TOKEN}"],
    })
    assert cfg.url == "http://10.0.0.1:9000/mcp"
    assert cfg.headers["Authorization"] == "Bearer s3cret"


def test_config_env_expansion_unset_warns(monkeypatch, caplog):
    monkeypatch.delenv("MCP_TEST_MISSING", raising=False)
    cfg = MCPServerConfig.from_dict({"name": "r", "transport": "http",
                                     "url": "http://x/mcp",
                                     "headers": {"Authorization": "${MCP_TEST_MISSING}"}})
    assert cfg.headers["Authorization"] == ""
    assert any("MCP_TEST_MISSING" in r.message for r in caplog.records)


def test_from_yaml(tmp_path):
    yaml_text = """
servers:
  - name: fetch
    transport: stdio
    command: uvx
    args: ["mcp-server-fetch"]
  - name: remote
    transport: http
    url: http://127.0.0.1:9000/mcp
"""
    p = tmp_path / "mcp_servers.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    manager = MCPManager.from_yaml(p)
    assert set(manager.servers) == {"fetch", "remote"}
    assert manager.servers["fetch"].args == ["mcp-server-fetch"]

    with pytest.raises(FileNotFoundError):
        MCPManager.from_yaml(tmp_path / "nope.yaml")


def test_from_yaml_null_servers(tmp_path):
    """YAML 只写 `servers:`（空值）不崩，视作无服务器。"""
    p = tmp_path / "null_servers.yaml"
    p.write_text("servers:\n", encoding="utf-8")
    assert MCPManager.from_yaml(p).servers == {}


def test_from_config_shapes():
    assert len(MCPManager.from_config({"servers": [{"name": "a", "command": "x"}]}).servers) == 1
    assert len(MCPManager.from_config([{"name": "a", "command": "x"}]).servers) == 1
    with pytest.raises((ValueError, TypeError)):
        MCPManager.from_config("bad")


# ── 工具注册与调用 ──

def _one_server_manager(tool_names=("search", "fetch")):
    session = FakeSession(
        tools=[_remote_tool(n) for n in tool_names],
        responses={("search", '{"x": 1}'): SimpleNamespace(
            content=[_text("结果A"), _text("结果B")],
            structuredContent={"ranked": [1, 2]}, isError=False)},
    )
    mgr = StubManager([_stdio_cfg("srv")], {"srv": session})
    return mgr, session


def test_load_tools_namespace_and_schema():
    mgr, _ = _one_server_manager()
    reg = ToolRegistry()
    errors = asyncio.run(mgr.load_tools(reg))
    assert errors == {}
    assert sorted(reg.names()) == ["mcp.srv.fetch", "mcp.srv.search"]
    schema = reg.require("mcp.srv.search").to_openai_schema()
    # wire 名：mcp.srv.search → mcp__srv__search（provider 安全校验）
    assert schema["name"] == "mcp__srv__search"
    # inputSchema 原样透传
    assert schema["parameters"]["properties"]["x"] == {"type": "integer"}
    assert schema["description"].startswith("[MCP:srv]")


def test_call_maps_text_structured_and_error():
    mgr, session = _one_server_manager()
    reg = ToolRegistry()
    asyncio.run(mgr.load_tools(reg))

    result = asyncio.run(reg.require("mcp.srv.search").run_async(x=1))
    assert result.success and result.output == "结果A\n结果B"
    assert result.data["structured"] == {"ranked": [1, 2]}
    assert session.calls == [("search", {"x": 1})]

    # isError → ToolResult.fail，文本仍回喂
    err_session = FakeSession(
        tools=[_remote_tool("boom")],
        call_fn=lambda n, a: SimpleNamespace(content=[_text("炸了")],
                                             structuredContent=None, isError=True))
    mgr2 = StubManager([_stdio_cfg("srv2")], {"srv2": err_session})
    reg2 = ToolRegistry()
    asyncio.run(mgr2.load_tools(reg2))
    r2 = asyncio.run(reg2.require("mcp.srv2.boom").run_async())
    assert not r2.success and "炸了" in (r2.error or "")


def test_allowlist_blocklist():
    session = FakeSession(tools=[_remote_tool(n) for n in ("a", "b", "c")])
    mgr = StubManager([_stdio_cfg("srv", tool_allowlist=["a", "b"],
                                  tool_blocklist=["b"])],
                      {"srv": session})
    reg = ToolRegistry()
    asyncio.run(mgr.load_tools(reg))
    assert reg.names() == ["mcp.srv.a"]


def test_call_timeout_returns_retry(monkeypatch):
    # 外层超时余量调小，避免单测白等 5 秒（见 mcp.py 的 _OUTER_TIMEOUT_MARGIN）
    monkeypatch.setattr("harness.tools.mcp._OUTER_TIMEOUT_MARGIN", 0.2)
    session = FakeSession(tools=[_remote_tool("slow")], delay=2.0)
    mgr = StubManager([_stdio_cfg("srv", call_timeout=0.1)], {"srv": session})
    reg = ToolRegistry()
    asyncio.run(mgr.load_tools(reg))
    result = asyncio.run(reg.require("mcp.srv.slow").run_async())
    assert not result.success and result.status == "retry"


def test_reconnect_once_on_call_failure():
    # 第一个会话调用必炸；重连后的第二个会话正常 → call 应自动恢复
    def _make(fail: bool):
        return FakeSession(
            tools=[_remote_tool("t")],
            call_fn=(lambda n, a: (_ for _ in ()).throw(RuntimeError("transport dead")))
            if fail else None)

    ok_session = _make(False)
    mgr = StubManager([_stdio_cfg("srv")], {"srv": _make(True)})
    # 预置会话为"坏"会话，重连时换成好会话
    orig_open = mgr._open_session

    async def _open(cfg, stack):
        if mgr.connect_count.get(cfg.name, 0) >= 1:
            mgr._stub_sessions[cfg.name] = ok_session
        return await orig_open(cfg, stack)

    mgr._open_session = _open  # type: ignore[method-assign]
    result = asyncio.run(mgr.call("srv", "t", {}))
    assert result.success
    assert mgr.connect_count["srv"] == 2


def test_connect_failure_isolation():
    class HalfBrokenManager(StubManager):
        async def _open_session(self, cfg, stack):
            if cfg.name == "bad":
                raise ConnectionError("refused")
            return await super()._open_session(cfg, stack)

    good = FakeSession(tools=[_remote_tool("t")])
    mgr = HalfBrokenManager(
        [_stdio_cfg("bad"), _stdio_cfg("good")],
        {"bad": FakeSession(), "good": good})
    reg = ToolRegistry()
    errors = asyncio.run(mgr.load_tools(reg))
    assert set(errors) == {"bad"}
    assert "good" not in errors
    assert reg.names() == ["mcp.good.t"]
    status = mgr.status()
    assert status["bad"]["connected"] is False and "refused" in status["bad"]["error"]
    assert status["good"]["connected"] is True and status["good"]["tools"] == 1


def test_load_tools_reregister_no_accumulation():
    mgr, _ = _one_server_manager(("only",))
    reg = ToolRegistry()
    asyncio.run(mgr.load_tools(reg))
    asyncio.run(mgr.load_tools(reg))
    assert reg.names() == ["mcp.srv.only"]


def test_close_then_reconnect():
    mgr, session = _one_server_manager(("t",))
    asyncio.run(mgr.ensure_connected("srv"))
    assert "srv" in mgr._sessions
    asyncio.run(mgr.close())
    assert "srv" not in mgr._sessions
    asyncio.run(mgr.ensure_connected("srv"))
    assert mgr.connect_count["srv"] == 2


def test_list_tools_pagination():
    class PagedSession(FakeSession):
        def __init__(self):
            super().__init__(tools=[_remote_tool("page1")])

        async def list_tools(self, cursor=None):
            if cursor is None:
                return SimpleNamespace(tools=[_remote_tool("page1")],
                                       nextCursor="c2")
            return SimpleNamespace(tools=[_remote_tool("page2")], nextCursor=None)

    mgr = StubManager([_stdio_cfg("srv")], {"srv": PagedSession()})
    tools = asyncio.run(mgr._list_remote_tools("srv"))
    assert sorted(t.name for t in tools) == ["page1", "page2"]


# ── toolbox 联动 ──

def test_toolbox_invalidate_after_mcp_register():
    mgr, _ = _one_server_manager(("search",))
    reg = ToolRegistry()
    toolbox = ToolboxManager(RegistryIndexSource(reg))
    schema = toolbox.build_schema(None)
    assert "mcp.srv.search" not in schema[0]["description"]

    asyncio.run(mgr.load_tools(reg))
    # 未失效：缓存索引仍是旧的
    schema = toolbox.build_schema(None)
    assert "mcp.srv.search" not in schema[0]["description"]
    # 失效后：索引包含 MCP 工具
    toolbox.invalidate()
    schema = toolbox.build_schema(None)
    assert "mcp.srv.search" in schema[0]["description"]


# ── SDK / Agent 全链路（桩模型 + 桩 MCP 服务器）──

class _ScriptedClient:
    """按脚本返回模型回复：先要一次工具调用，再给最终答复。"""

    def __init__(self, tool_name: str, args: dict):
        self.tool_name = tool_name
        self.args = args
        self.turn = 0

    async def invoke(self, messages, tools=None):
        from infra.models.base import ChatResponse, ToolCall
        self.turn += 1
        if self.turn == 1:
            return ChatResponse(content="", tool_calls=[
                ToolCall(id="c1", name=to_wire_name(self.tool_name),
                         arguments=self.args)])
        return ChatResponse(content="已调用工具")


def test_sdk_agent_mcp_end_to_end():
    session = FakeSession(
        tools=[_remote_tool("add", "加法",
                            {"type": "object",
                             "properties": {"a": {"type": "integer"},
                                            "b": {"type": "integer"}},
                             "required": ["a", "b"]})],
        call_fn=lambda n, a: SimpleNamespace(content=[_text(str(a["a"] + a["b"]))],
                                             structuredContent=None, isError=False))

    client = _ScriptedClient("mcp.srv.add", {"a": 2, "b": 3})
    agent = Agent(client, mcp=[{"name": "srv", "transport": "stdio",
                                "command": "x"}])
    # 装配期零连接（惰性）
    assert isinstance(agent._assembled.mcp, MCPManager)
    assert agent._assembled.mcp._sessions == {}

    # 用桩会话替换真实连接
    real_mcp = agent._assembled.mcp
    stub = StubManager(real_mcp.servers.values(), {"srv": session})
    agent._assembled.mcp = stub
    agent._mcp_ready = False

    reply = asyncio.run(agent.chat_async("算 2+3"))
    assert reply == "已调用工具"
    assert session.calls == [("add", {"a": 2, "b": 3})]
    # 惰性预热只发生一次
    assert agent._mcp_ready is True


def test_sdk_create_agent_mcp_params():
    from harness import create_agent

    agent = create_agent("m", api_key="k",
                         mcp_servers=[{"name": "s1", "command": "x"}],
                         mcp_config="mcp_servers.yaml")
    spec_mcp = agent.spec.mcp
    assert spec_mcp == {"servers": [{"name": "s1", "command": "x"}],
                        "config": "mcp_servers.yaml"}
    # 仓库根的默认配置文件可解析（servers: []）
    assert set(agent._assembled.mcp.servers) == {"s1"}


def test_assembler_mcp_spec_shapes():
    from harness.agent.assembler import AgentAssembler, AgentSpec

    client = _ScriptedClient("mcp.s.a", {})
    # dict 形式
    assembled = AgentAssembler(client).assemble(AgentSpec(
        name="t1", mcp={"servers": [{"name": "s", "command": "x"}]}))
    assert isinstance(assembled.mcp, MCPManager)
    assert set(assembled.mcp.servers) == {"s"}
    # str 形式 = YAML 路径
    assembled2 = AgentAssembler(client).assemble(AgentSpec(
        name="t2", mcp=str(REPO_ROOT / "mcp_servers.yaml")))
    assert assembled2.mcp is not None and len(assembled2.mcp.servers) == 0


def test_setup_mcp_noop_without_mcp():
    from harness.agent.assembler import AgentAssembler, AgentSpec

    client = _ScriptedClient("x", {})
    assembled = AgentAssembler(client).assemble(AgentSpec(name="t"))
    assert asyncio.run(assembled.setup_mcp()) == {}


# ── 真实 stdio 往返（integration，默认手动跑）──

@pytest.mark.integration
def test_stdio_roundtrip_real_server():
    pytest.importorskip("mcp")
    cfg = MCPServerConfig(
        name="demo", transport="stdio",
        command=sys.executable,
        args=[str(REPO_ROOT / "tests" / "fixtures" / "mcp_demo_server.py")],
        connect_timeout=30,
    )
    mgr = MCPManager([cfg])
    reg = ToolRegistry()

    async def _run():
        errors = await mgr.load_tools(reg)
        assert errors == {}, errors
        assert {"mcp.demo.add", "mcp.demo.echo"} <= set(reg.names())
        r1 = await mgr.call("demo", "add", {"a": 2, "b": 3})
        r2 = await reg.require("mcp.demo.echo").run_async(text="hi")
        await mgr.close()
        return r1, r2

    r1, r2 = asyncio.run(_run())
    assert r1.success and r1.output == "5"
    assert r2.success and r2.output == "echo: hi"
