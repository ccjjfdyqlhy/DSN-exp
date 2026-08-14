# tests/test_harness_v2_innovations.py
# harness v2 创新模块测试：subagent / modes / gatherer / imports / watcher / assembler。

from __future__ import annotations

import pytest

from harness import ContextGatherer, ToolDeps, ToolRegistry, install_standard_tools
from harness.agent import (
    AgentAssembler,
    AgentMode,
    AgentSpec,
    ModeState,
    SubAgentRunner,
    SubTask,
)
from harness.codegraph import FileWatcher, ImportResolver


# ── ModeState ──

def test_modes_switch_and_alias():
    m = ModeState()
    assert m.is_agent
    m.switch("s")
    assert m.is_swarm
    m.switch("agent")
    assert m.is_agent
    m.switch("o")
    assert m.is_oneshot


def test_modes_unknown_raises():
    m = ModeState()
    with pytest.raises(ValueError):
        m.switch("unknown")


# ── SubAgentRunner ──

def test_subagent_split_and_run():
    import asyncio

    from harness.models.base import ChatResponse

    class FakeClient:
        model = "fake"

        def invoke(self, messages, tools=None, **kw):
            return ChatResponse(content="ok")

    runner = SubAgentRunner(FakeClient(), None, max_steps=2)
    tasks = [SubTask(title="A", prompt="任务A"), SubTask(title="B", prompt="任务B")]
    result = asyncio.run(runner.run(tasks, max_concurrency=2))
    assert result.done_count == 2
    assert all(t.status == "done" for t in result.tasks)
    assert "ok" in result.summary()


def test_subagent_split_rule():
    runner = SubAgentRunner(None)
    tasks = runner.split("第一段。\n\n第二段。\n\n第三段。", n=3)
    assert len(tasks) == 3


# ── ContextGatherer ──

def test_gatherer_parse_directives(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    g = ContextGatherer(str(tmp_path))
    r = g.parse("看看 @req a.py 这个文件")
    assert r.directives_found
    assert "@req" not in r.clean_input
    assert "x = 1" in r.context_block


def test_gatherer_no_directive():
    g = ContextGatherer("/tmp")
    r = g.parse("你好")
    assert not r.directives_found and r.clean_input == "你好"


# ── ImportResolver ──

def test_import_resolver(tmp_path):
    mod = tmp_path / "mod.py"
    mod.write_text("def helper(x):\n    return x\n")
    (tmp_path / "main.py").write_text("from mod import helper\n")
    r = ImportResolver(str(tmp_path))
    sigs = r.resolve(str(tmp_path / "main.py"))
    assert any(s.name == "helper" for s in sigs)
    assert "依赖的接口" in r.prompt_block(str(tmp_path / "main.py"))


# ── FileWatcher ──

def test_file_watcher_detects_change(tmp_path):
    import os
    import time

    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    w = FileWatcher(str(tmp_path), interval=0.1)
    assert w.get_changed_files() == []  # 首次扫描不算变更
    time.sleep(0.05)
    f.write_text("x = 2\n")
    os.utime(f, None)  # 刷新 mtime
    changed = w.get_changed_files()
    assert any("a.py" in c for c in changed)


# ── AgentAssembler ──

def test_assembler_smoke():
    from harness.models.base import ChatResponse

    class FakeClient:
        model = "fake"

        def invoke(self, messages, tools=None, **kw):
            return ChatResponse(content="hi")

    spec = AgentSpec(
        name="demo",
        system_prompt="你是助手。",
        tools="standard",
        toolbox={"enabled": True},
        router={"flash_model": "f", "pro_model": "p"},
        budget={"token_cap": 10000},
        memory=True,
    )
    agent = AgentAssembler(FakeClient()).assemble(spec)
    assert len(agent.loop.tools) >= 10
    assert agent.loop.toolbox is not None
    assert agent.router is not None
    assert agent.budget is not None
    assert "你是助手" in agent.system_prompt()
