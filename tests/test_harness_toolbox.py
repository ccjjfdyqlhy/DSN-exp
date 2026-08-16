# tests/test_harness_toolbox.py
# 引擎层两阶段工具激活策略（harness/tools/toolbox.py）单元测试。

from __future__ import annotations

import json

import pytest

from harness import Tool, ToolRegistry
from harness.tools.toolbox import RegistryIndexSource, ToolboxManager


def _registry(n: int = 5) -> ToolRegistry:
    reg = ToolRegistry()
    for i in range(n):
        reg.register_tool(
            f"skill.demo{i}", f"工具{i}描述",
            lambda i=i: i,
            {"type": "object", "properties": {"x": {"type": "integer"}}},
        )
    return reg


def test_toolbox_initial_schema_only_index():
    """阶段1：未激活时只发 toolbox 索引工具，不带任何具体工具 schema。"""
    m = ToolboxManager(RegistryIndexSource(_registry(5)))
    schema = m.build_schema(None)
    assert len(schema) == 1
    assert schema[0]["name"] == "toolbox"
    assert "skill.demo0" in schema[0]["description"]
    # ids 参数枚举完整
    enum = schema[0]["parameters"]["properties"]["ids"]["items"]["enum"]
    assert len(enum) == 5


def test_toolbox_activated_schema_appends_details():
    """阶段2：激活后附带已激活工具的完整 schema + 补充激活工具箱。"""
    m = ToolboxManager(RegistryIndexSource(_registry(3)))
    schema = m.build_schema(["skill.demo0"])
    names = [s["name"] for s in schema]
    # 发给模型的函数名是 wire 名（点号编码），内部激活状态仍是 skill.demo0
    assert names == ["toolbox", "skill__demo0"]
    assert schema[1]["parameters"]["properties"]["x"]["type"] == "integer"
    # 已激活时索引描述不再内联
    assert "skill.demo0" not in schema[0]["description"]


def test_toolbox_disabled_exports_full_schema():
    m = ToolboxManager(RegistryIndexSource(_registry(3)), enabled=False)
    schema = m.build_schema(None)
    assert len(schema) == 3
    # toolbox 关闭时全量导出，函数名仍使用 wire 格式
    assert all(s["name"].startswith("skill__") for s in schema)


def test_toolbox_nested_schema_style():
    """nested=True 时输出 OpenAI 嵌套格式（DSN 技能 schema 风格）。"""
    m = ToolboxManager(RegistryIndexSource(_registry(2)), nested=True)
    schema = m.build_schema(None)
    assert schema[0]["type"] == "function"
    assert schema[0]["function"]["name"] == "toolbox"


def test_toolbox_handle_calls_separates_and_activates():
    """handle_calls 分离 toolbox 调用、去重激活、产出确认结果。"""
    m = ToolboxManager(RegistryIndexSource(_registry(4)))
    calls = [
        {"id": "c1", "function": {"name": "toolbox",
                                  "arguments": json.dumps({"ids": ["skill.demo0", "skill.demo1"]})}},
        {"id": "c2", "function": {"name": "skill.demo0",
                                  "arguments": json.dumps({"x": 1})}},
        {"id": "c3", "function": {"name": "toolbox",
                                  "arguments": json.dumps({"ids": ["skill.demo1", "skill.demo2"]})}},
    ]
    real, results = m.handle_calls(calls)
    # 只有真实工具调用被保留执行
    assert [c["id"] for c in real] == ["c2"]
    # 两个 toolbox 调用各产生一条确认结果
    assert len(results) == 2
    assert results[0]["name"] == "toolbox"
    assert results[0]["success"] is True
    # 去重激活：demo1 只激活一次
    assert m.activated == ["skill.demo0", "skill.demo1", "skill.demo2"]
    # 引擎风格结果字段（call_id/name/output），供 build_round 直接消费
    assert results[0]["call_id"] == "c1"
    assert results[0]["output"]["activated"] == ["skill.demo0", "skill.demo1"]
    assert results[1]["output"]["activated"] == ["skill.demo2"]


def test_toolbox_legacy_converter():
    m = ToolboxManager(RegistryIndexSource(_registry(2)))
    calls = [{"id": "c1", "function": {"name": "toolbox",
                                       "arguments": json.dumps({"ids": ["skill.demo0"]})}}]
    _, results = m.handle_calls(calls)
    legacy = m.results_to_legacy(results)
    assert legacy[0]["function"] == "toolbox"
    assert legacy[0]["tool_call_id"] == "c1"
    assert legacy[0]["data"]["activated"] == ["skill.demo0"]


def test_toolbox_object_calls_supported():
    """兼容 harness ToolCall 对象形态（id/name/arguments 属性）。"""
    from harness.models.base import ToolCall

    m = ToolboxManager(RegistryIndexSource(_registry(2)))
    calls = [ToolCall(id="t1", name="toolbox", arguments={"ids": ["skill.demo0"]})]
    real, results = m.handle_calls(calls)
    assert real == []
    assert results[0]["call_id"] == "t1"
    assert m.activated == ["skill.demo0"]


def test_toolbox_agentloop_integration_smoke():
    """AgentLoop 注入 toolbox 后：首轮只发索引，激活轮次附全 schema。"""
    import asyncio

    from harness.agent import AgentLoop
    from harness.models.base import ChatMessage, ChatResponse, ToolCall

    reg = _registry(2)
    seen_schemas: list[list[dict]] = []

    class FakeClient:
        model = "fake"

        def invoke(self, messages, tools=None, **kw):
            seen_schemas.append(tools or [])
            if len(seen_schemas) == 1:
                # 第一轮：模型只激活工具
                return ChatResponse(content="", tool_calls=[
                    ToolCall(id="a1", name="toolbox",
                             arguments={"ids": ["skill.demo0"]})
                ])
            # 第二轮：真实调用 + 结束（模型返回 wire 名，loop 会还原）
            return ChatResponse(content="完成", tool_calls=[
                ToolCall(id="a2", name="skill__demo0", arguments={"x": 1})
            ])

    m = ToolboxManager(RegistryIndexSource(reg))
    loop = AgentLoop(FakeClient(), reg, toolbox=m, max_steps=4)
    result = asyncio.run(loop.run_async([ChatMessage.user("hi")]))
    # 首轮 schema 只有 toolbox 索引
    assert len(seen_schemas[0]) == 1
    assert seen_schemas[0][0]["name"] == "toolbox"
    # 第二轮 schema 含 toolbox + 已激活工具（wire 名）
    assert [s["name"] for s in seen_schemas[1]] == ["toolbox", "skill__demo0"]
    assert result.reply == "完成"
    assert result.steps >= 2
