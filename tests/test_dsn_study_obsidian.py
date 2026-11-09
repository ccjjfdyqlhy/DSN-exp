"""dsn_study × Obsidian MCP 集成测试。

覆盖：MCP 配置装载 / MCPBridge 生命周期 / obsidian_notes 技能 /
异步工具桥接 / 控制 API 路由 / 真实 MCP 往返（可选）。
"""

from __future__ import annotations

import asyncio
import os

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── 1. 配置 ──

def test_mcp_config_declares_obsidian_server():
    from harness.tools import MCPManager
    path = os.path.join(REPO_ROOT, "apps", "dsn_study", "mcp_servers.yaml")
    assert os.path.isfile(path)
    mgr = MCPManager.from_yaml(path)
    assert "obsidian" in mgr.servers
    cfg = mgr.servers["obsidian"]
    assert cfg.transport == "stdio"
    assert cfg.enabled is True
    assert any("obsidian-mcp" in a for a in cfg.args)
    assert any("--vault" in a for a in cfg.args)


def test_mcp_config_expands_vault_env(monkeypatch):
    """vault 路径用环境变量占位，加载时展开。"""
    from harness.tools import MCPManager
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "/tmp/vault-x")
    path = os.path.join(REPO_ROOT, "apps", "dsn_study", "mcp_servers.yaml")
    mgr = MCPManager.from_yaml(path)
    joined = " ".join(mgr.servers["obsidian"].args)
    assert "/tmp/vault-x" in joined
    assert "$" not in joined


# ── 2. MCPBridge ──

class _FakeAgent:
    def __init__(self):
        self.registered = []

    def register(self, tool):
        self.registered.append(tool)
        return tool


def test_mcp_bridge_missing_config_is_noop():
    from apps.dsn_study.mcp_bridge import MCPBridge
    bridge = MCPBridge(_FakeAgent(), config_path="/nonexistent/mcp.yaml")
    assert bridge.start() is False
    status = bridge.status()
    assert status["connected"] is False
    assert status["tool_count"] == 0
    bridge.close()


def test_mcp_bridge_status_shape():
    from apps.dsn_study.mcp_bridge import MCPBridge
    bridge = MCPBridge(_FakeAgent(), config_path="")
    status = bridge.status()
    for key in ("enabled", "connected", "tool_count", "tools", "errors", "servers"):
        assert key in status


def test_mcp_bridge_call_without_connection_raises():
    from apps.dsn_study.mcp_bridge import MCPBridge
    bridge = MCPBridge(_FakeAgent(), config_path="")

    async def _go():
        await bridge.call("obsidian", "obsidian_list_vaults", {})

    with pytest.raises(RuntimeError):
        asyncio.run(_go())


# ── 3. obsidian_notes 技能 ──

class _StubManager:
    """假的 MCPManager：记录调用，回放预设结果。"""

    def __init__(self, results=None):
        self.calls = []
        self.results = results or {}

    async def call(self, server, tool, arguments=None):
        from harness.tools.base import ToolResult
        self.calls.append((server, tool, arguments or {}))
        payload = self.results.get(tool)
        if payload is None:
            return ToolResult.ok("ok")
        # 与真实 obsidian-mcp 一致：已存在等业务性提示按**成功**返回，
        # 文本里带 ALREADY_EXISTS 标记（不是 MCP 层错误）。
        return ToolResult.ok(payload)


class _StubBridge:
    def __init__(self, manager=None):
        self.manager = manager
        self.tools = ["mcp.obsidian.obsidian_create_note"]

    async def call(self, server, tool, arguments=None):
        if self.manager is None:
            raise RuntimeError("MCP 未连接")
        return await self.manager.call(server, tool, arguments)


class _StubGraphStore:
    def __init__(self, nodes=None):
        self._nodes = nodes or []

    def get_nodes_by_subject(self, subject):
        return [n for n in self._nodes if n.get("subject") == subject]

    def get_user_states(self, user_id, subject=None):
        return []


def _tool(manager=None, nodes=None):
    from apps.dsn_study.skills.builtin.obsidian_notes.tools.obsidian_tools import (
        ObsidianNotesTool,
    )
    bridge = _StubBridge(manager if manager is not None else _StubManager())
    return ObsidianNotesTool(mcp_bridge=bridge,
                              graph_store=_StubGraphStore(nodes)), bridge


def test_index_knowledge_points_writes_notes():
    nodes = [{"kp_code": "KP-1", "name": "顶点公式", "subject": "math",
              "description": "y=ax^2+bx+c 的顶点"}]
    manager = _StubManager()
    tool, bridge = _tool(manager, nodes)
    result = asyncio.run(tool.index_knowledge_points(subject="math"))
    assert result["success"] is True
    assert result["indexed"] == 1
    tools_used = [c[1] for c in manager.calls]
    assert "obsidian_create_directory" in tools_used
    assert "obsidian_create_note" in tools_used
    create = [c for c in manager.calls if c[1] == "obsidian_create_note"][0]
    path, content = create[2]["path"], create[2]["content"]
    assert path.startswith("知识点库/")
    assert path.endswith("KP-1.md")
    assert "kp_code" in content and "顶点公式" in content
    assert "tags:" in content


def test_index_knowledge_points_skips_existing_without_overwrite():
    nodes = [{"kp_code": "KP-2", "name": "x", "subject": "math"}]
    manager = _StubManager({"obsidian_create_note": "ALREADY_EXISTS: exists"})
    tool, _ = _tool(manager, nodes)
    result = asyncio.run(tool.index_knowledge_points(subject="math"))
    assert result["indexed"] == 0
    assert result["skipped"] == 1


def test_index_knowledge_points_overwrite_updates():
    nodes = [{"kp_code": "KP-3", "name": "y", "subject": "math"}]
    manager = _StubManager({"obsidian_create_note": "ALREADY_EXISTS: exists"})
    tool, _ = _tool(manager, nodes)
    result = asyncio.run(tool.index_knowledge_points(subject="math",
                                                     overwrite=True))
    assert result["indexed"] == 1
    assert any(c[1] == "obsidian_edit_note" for c in manager.calls)


def test_index_without_graph_store_degrades():
    from apps.dsn_study.skills.builtin.obsidian_notes.tools.obsidian_tools import (
        ObsidianNotesTool,
    )
    tool = ObsidianNotesTool(mcp_bridge=_StubBridge(_StubManager()))
    result = asyncio.run(tool.index_knowledge_points(subject="math"))
    assert "error" in result


def test_write_study_note_creates_note():
    manager = _StubManager()
    tool, _ = _tool(manager)
    result = asyncio.run(tool.write_study_note("二次函数复盘", "顶点公式要背熟",
                                            tags="数学,错题"))
    assert result["success"] is True
    assert result["path"].startswith("学习笔记/")
    create = [c for c in manager.calls if c[1] == "obsidian_create_note"][0]
    content = create[2]["content"]
    assert "二次函数复盘" in content
    assert "错题" in content


def test_write_study_note_appends_when_exists():
    """已存在时走 **obsidian_edit_note(operation="append")**。

    2026-11-08 修正：此前用的是 `obsidian_append_to_note` —— 但 obsidian-mcp@2
    的 12 个工具里**没有这个工具**（只有 edit_note 的 operation 枚举含 append），
    所以「给已存在的笔记追加内容」这条路径在真实 MCP 上必然失败。
    """
    manager = _StubManager({"obsidian_create_note": "ALREADY_EXISTS: exists"})
    tool, _ = _tool(manager)
    result = asyncio.run(tool.write_study_note("t", "c"))
    assert result.get("appended") is True
    assert any(c[1] == "obsidian_edit_note" for c in manager.calls), \
        "应调用 obsidian_edit_note（不存在 obsidian_append_to_note 这个工具）"
    edit_calls = [c for c in manager.calls if c[1] == "obsidian_edit_note"]
    assert edit_calls and edit_calls[0][2].get("operation") == "append"


def test_safe_name_strips_path_separators():
    from apps.dsn_study.skills.builtin.obsidian_notes.tools.obsidian_tools import (
        ObsidianNotesTool,
    )
    assert "/" not in ObsidianNotesTool._safe_name("a/b c")
    assert ObsidianNotesTool._safe_name("") == "未命名"


# ── 3.5 MCP 工具 schema 透传 ──

def test_mcp_tool_schema_reads_both_sdk_attribute_names():
    """SDK 1.x 是 inputSchema，2.x 是 input_schema —— 两个都要读到。

    读不到就会退化成空 schema，模型不知道该传什么参数。
    """
    from types import SimpleNamespace

    from harness.tools.mcp import MCPManager, MCPServerConfig

    mgr = MCPManager([MCPServerConfig(name="s", transport="stdio",
                                      command="true")])
    cfg = mgr.servers["s"]
    schema = {"type": "object",
              "properties": {"path": {"type": "string"}}}

    remote_v1 = SimpleNamespace(name="t1", description="d",
                                inputSchema=schema)
    remote_v2 = SimpleNamespace(name="t2", description="d",
                                input_schema=schema)

    t1 = mgr._make_tool(cfg, remote_v1)
    t2 = mgr._make_tool(cfg, remote_v2)
    assert t1.parameters.get("properties"), "SDK 1.x 的 inputSchema 未透传"
    assert t2.parameters.get("properties"), "SDK 2.x 的 input_schema 未透传"


# ── 4. 异步工具桥接 ──

def test_async_skill_tool_registered_once():
    """协程工具只能注册一次（否则 AgentLoop 报「工具已注册」）。"""
    from apps.dsn_study import boot
    app = boot.create_application()
    agent = boot.engine.agent
    names = list(agent.tools.names())
    assert len(names) == len(set(names)), "存在重复注册的工具"
    assert "obsidian_notes.index_knowledge_points" in names


def test_skill_dependency_injection_hits_obsidian_tool():
    """依赖注入的 key 必须与工具属性名一致（否则被静默跳过）。"""
    from apps.dsn_study import boot
    boot.create_application()
    insts = boot.engine.skill_registry.get_tool_instances("obsidian_notes")
    assert insts
    for inst in insts:
        assert inst.mcp_bridge is not None, "MCP 桥未注入"
        assert inst.graph_store is not None, "知识图谱未注入"


# ── 5. API ──

def test_obsidian_routes_registered():
    from apps.dsn_study import boot
    app = boot.create_application()
    rules = {r.rule for r in app.url_map.iter_rules()}
    assert "/api/obsidian/status" in rules
    assert "/api/obsidian/index" in rules


# ── 6. 真实 MCP 往返（可选） ──

@pytest.mark.skipif(os.environ.get("MCP_LIVE_TEST") != "1",
                    reason="需 MCP_LIVE_TEST=1；会真实拉起 npx obsidian-mcp 子进程")
def test_live_obsidian_mcp_roundtrip(tmp_path):
    """真实 MCP：连接 obsidian-mcp → 建目录 → 写笔记 → 读回。"""
    from harness.tools import MCPManager, MCPServerConfig, ToolRegistry

    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)

    cfg = MCPServerConfig(
        name="obsidian",
        transport="stdio",
        command="npx",
        args=["-y", "obsidian-mcp@2", "serve", "--vault", "t=" + str(vault)],
        connect_timeout=120,
        call_timeout=60,
    )
    mgr = MCPManager([cfg])
    reg = ToolRegistry()

    async def _run():
        errors = await mgr.load_tools(reg)
        assert errors == {}, errors
        assert any(n.startswith("mcp.obsidian.") for n in reg.names())
        r = await mgr.call("obsidian", "obsidian_create_note",
                           {"vault": "t", "path": "a/b.md",
                            "content": "hello"})
        assert r.success, r.error
        r2 = await mgr.call("obsidian", "obsidian_read_note",
                            {"vault": "t", "path": "a/b.md"})
        assert r2.success, r2.error
        await mgr.close()
        return r2

    out = asyncio.run(_run())
    assert "hello" in str(out.output)
