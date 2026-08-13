# tests/test_harness_tools.py
from __future__ import annotations

import pytest

from harness import Tool, ToolResult, ToolRegistry


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
    assert schema[0]["name"] == "math.add"
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
