# tests/test_harness_coding.py
# 从 dekacode 提取的通用 coding-agent 能力测试

from __future__ import annotations

import asyncio
import tempfile
import textwrap

from harness.agent import (
    Blackboard,
    PrefetchPlaceholders,
    SpeculativePrefetch,
    SwarmMember,
    SwarmRuntime,
    ThreeZoneContext,
)
from harness.codegraph import GraphBuilder, find_callers, search_symbols
from harness.models.base import ChatResponse
from harness.models.router import ModelRouter
from harness.models.stub import StubChatClient
from harness.observability import UsageTracker
from harness.pipeline.filters import OutputFilter
from harness.store import SessionStore
from harness.tools import ToolRegistry, tool_from_function, tools_from_module


# ── function → tool ──

def test_tool_from_function_builds_schema():
    def add(a: int, b: int = 0):
        """两数相加。"""
        return a + b

    tool = tool_from_function(add, namespace="math")
    assert tool.name == "math.add"
    assert "两数相加" in tool.description
    assert tool.parameters["properties"]["a"]["type"] == "integer"
    assert tool.parameters["required"] == ["a"]
    assert tool.parameters["properties"]["b"]["default"] == 0
    assert tool.run(a=1, b=2).output == 3


def _sample_module():
    import types
    mod = types.ModuleType("sample_tools")

    def hello(name: str = "world") -> str:
        """打招呼。"""
        return f"hello {name}"

    mod.hello = hello
    return mod


def test_tools_from_module():
    tools = tools_from_module(_sample_module(), namespace="s")
    names = {t.name for t in tools}
    assert "s.hello" in names


# ── skill loader ──

def test_skill_loader_installs_package():
    from harness.skills import SkillLoader
    loader = SkillLoader()
    reg = ToolRegistry()
    installed = loader.install_module(_sample_module(), reg, namespace="pkg")
    assert "pkg.hello" in installed
    assert reg.has("pkg.hello")


# ── router ──

def test_model_router_select_and_switch():
    router = ModelRouter()
    router.register_tier("flash", "deepseek-v4-flash")
    router.register_tier("pro", "deepseek-v4-pro")
    assert router.select("search") == "flash"
    router.switch("pro")
    assert router.select("") == "pro"
    router.reset_auto()
    router.switch("my-custom")
    assert router.select("") == "my-custom"


# ── usage tracker ──

def test_usage_tracker_cost_and_budget():
    tracker = UsageTracker(budget=0.1)
    tracker.record(ChatResponse(usage={
        "prompt_tokens": 1000,
        "completion_tokens": 100,
        "prompt_tokens_details": {"cached_tokens": 800},
    }), tier="flash", peak_hours=False)
    rec = tracker.records[0]
    assert rec.input_tokens == 1000
    assert rec.cache_hit_input == 800
    assert rec.cache_miss_input == 200
    assert tracker.total_cost > 0
    assert not tracker.over_budget()


# ── RTK filters ──

def test_output_filter_cleans_ansi_and_truncates():
    raw = "\x1b[31mred\x1b[0m\n\n\nline\n"
    cleaned = OutputFilter.collapse(raw)
    assert "\x1b[" not in cleaned
    assert "\n\n\n" not in cleaned
    long = "x" * 100
    assert len(OutputFilter.truncate(long, max_chars=20)) <= 40


# ── three-zone context ──

def test_three_zone_context_sanitize_and_zones():
    ctx = ThreeZoneContext(system_prompt="sys")
    ctx.attach_prefix("prefix-a")
    ctx.add_user("hello")
    msgs = ctx.build_request()
    assert msgs[0].content == "sys"
    assert any(m.content == "prefix-a" for m in msgs)
    ctx.add_tool_result("id1", "tool", "res")
    ctx.commit_draft()
    assert len(ctx.history) == 2
    ctx.rollback_draft()
    assert ctx.total_messages() >= 3


def test_speculative_prefetch():
    symbols = {"foo": {"file_path": "/tmp/x.py", "line": 1, "signature": "def foo()"}}
    pf = SpeculativePrefetch(
        symbol_lookup=lambda n: symbols.get(n),
        source_loader=lambda f, l: "def foo():\n    pass\n")
    names = pf.analyze("NameError: name 'foo' is not defined")
    assert "foo" in names
    block = pf.prefetch(names)
    assert "def foo():" in block


def test_prefetch_placeholders():
    resolver = lambda n: "src_of_" + n  # noqa: E731
    ph = PrefetchPlaceholders(resolver)
    out = ph.resolve("见 [FETCH:bar]")
    assert "src_of_bar" in out


# ── session store ──

def test_session_store_roundtrip():
    store = SessionStore(db_path=":memory:")
    sid = store.create_session()
    from harness.models.base import ChatMessage
    store.save_messages([ChatMessage.user("hi"), ChatMessage.assistant("yo")])
    msgs = store.load_messages(sid)
    assert len(msgs) == 2 and msgs[0].content == "hi"
    store.save_usage(1, input_tokens=10, output_tokens=5)
    assert store.load_usage()[0]["input_tokens"] == 10
    assert store.list_sessions()[0]["message_count"] == 2


# ── code graph ──

def test_code_graph_build_and_search(tmp_path):
    (tmp_path / "mod.py").write_text(textwrap.dedent("""
        class Foo:
            def bar(self):
                return self._helper()
            def _helper(self):
                return 1
        def top():
            f = Foo()
            return f.bar()
    """))
    graph = GraphBuilder(str(tmp_path)).build()
    assert graph.total_symbols() >= 3
    assert graph.get("Foo") is not None
    assert graph.get("Foo.bar") is not None
    assert search_symbols(graph, "top")
    assert "def top" in graph.get("top").signature


# ── swarm ──

def test_blackboard_consensus():
    async def _run():
        board = Blackboard()
        await board.post("a", "consensus", "答案是 42")
        board.current_round = 2
        return board.final_answer(), board.consensus_survived()
    answer, survived = asyncio.run(_run())
    assert answer == "答案是 42"
    assert survived


def test_swarm_runtime_with_stub():
    async def _run():
        board = Blackboard()
        tools = ToolRegistry()
        stub = StubChatClient(responses=[
            ChatResponse(content="成员给出结论", model="stub")])
        m = SwarmMember("alpha", stub, tools, board, system_prompt="p")
        rt = SwarmRuntime([m], max_rounds=1)
        res = await rt.run("问题")
        return res
    res = asyncio.run(_run())
    assert res.member_outputs["alpha"] == "成员给出结论"
