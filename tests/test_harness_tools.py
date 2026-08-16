# tests/test_harness_tools.py
from __future__ import annotations

import re

import pytest

from harness import Tool, ToolResult, ToolRegistry
from harness.tools import from_wire_name, to_wire_name

# 部分 OpenAI 兼容服务端强校验 function 名
PROVIDER_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def test_wire_name_roundtrip():
    known = {"file.read", "project.summary", "toolbox", "text.extract_json"}
    for internal in known:
        wire = to_wire_name(internal)
        assert PROVIDER_NAME_RE.match(wire), f"{wire} 不符合 provider 命名规则"
        assert from_wire_name(wire, known) == internal


def test_wire_name_sanitizes_illegal_chars():
    assert PROVIDER_NAME_RE.match(to_wire_name("weird name!@#"))


def test_wire_name_keeps_unknown_names_untouched():
    # 未知名字不应被强行还原（避免误伤本身带双下划线的工具名）
    assert from_wire_name("a__b", {"a__b"}) == "a__b"


def test_all_schema_names_are_provider_legal():
    reg = ToolRegistry()
    for name in ("file.read", "code.syntax_check", "git.status", "plain"):
        reg.register_tool(name, "d", lambda: None)
    for s in reg.build_schema():
        assert PROVIDER_NAME_RE.match(s["name"]), f"{s['name']} 会被 provider 拒绝"


def test_tool_run_ok_wraps_raw_result():
    t = Tool(name="double", description="x2", handler=lambda x: x * 2,
             parameters={"type": "object", "properties": {"x": {"type": "integer"}}})
    r = t.run(x=21)
    assert isinstance(r, ToolResult)
    assert r.success and r.output == 42


def test_tool_run_failure():
    def boom(**kw):
        raise ValueError("nope")

    t = Tool(name="boom", description="", handler=boom)
    r = t.run()
    assert not r.success and "nope" in r.error


def test_tool_async_handler():
    async def afn(**kw):
        return "ok"

    import asyncio
    t = Tool(name="a", description="", handler=afn)
    r = asyncio.run(t.run_async())
    assert r.success and r.output == "ok"


def test_registry_register_and_schema():
    reg = ToolRegistry()
    reg.register_tool("math.add", "add", lambda a, b: a + b,
                      {"type": "object", "properties": {"a": {}, "b": {}}})
    assert reg.has("math.add")
    schema = reg.build_schema()
    # schema 输出 wire 名（点 → 双下划线），兼容强校验 provider；内部注册名不变
    assert schema[0]["name"] == "math__add"
    assert reg.require("math.add") is not None


def test_registry_require_missing():
    reg = ToolRegistry()
    with pytest.raises(KeyError):
        reg.require("nope")


def test_registry_duplicate_raises():
    reg = ToolRegistry()
    reg.register_tool("t", "", lambda: None)
    with pytest.raises(KeyError):
        reg.register(Tool(name="t", description="", handler=lambda: None))
