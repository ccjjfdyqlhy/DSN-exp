# tests/test_dsn_study_mcp_server.py
# FEATURE_GAP 阶段 6（暴露侧 MCP）验收 —— 学习技能工具经 stdio MCP
# 供外部 Agent 调用（harness/tools/mcp.py 是消费侧，本模块验收暴露侧）。
#
# 覆盖：
#   命名     skill.tool → skill__tool 编码 + MCP 命名规则校验
#   装配     最小上下文（无 Flask/线程副作用）→ 全部已注册工具进入暴露清单
#   契约     tools/list 载荷与 function calling 用同一 schema 生成器
#   派发     真实工具往返（建题→读题）/ 未知工具 / 异常折返为错误载荷
#   异步     协程工具走 call_tool_async 分支
#   端到端   子进程起真实 stdio 服务，MCP 客户端 initialize→list→call

import asyncio
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


# ── 装配（模块级，一次） ──

@pytest.fixture(scope="module")
def mcp_ctx(tmp_path_factory):
    """最小装配。db 指向临时目录 —— 直接改 Config 类属性（Config 是
    导入期快照，改环境变量在收集期之后已无效），避免污染仓库 .dsn 真实题库。"""
    tmp = tmp_path_factory.mktemp("mcp_study")
    from apps.dsn_study.config import Config
    restored = Config.QUESTION_BANK_DB_PATH
    Config.QUESTION_BANK_DB_PATH = str(tmp / "qb.db")
    context = None
    try:
        from apps.dsn_study.mcp_server import build_all
        registry, index, context = build_all()
        yield registry, index, context
    finally:
        Config.QUESTION_BANK_DB_PATH = restored
        tm = (context or {}).get("task_manager")
        if tm is not None:
            tm.shutdown()


# ── 命名 ──

def test_tool_name_encoding_rules():
    from apps.dsn_study.mcp_server import mcp_tool_name
    assert mcp_tool_name("question_bank", "create_question") == \
        "question_bank__create_question"
    # MCP 名只允许字母/数字/下划线/连字符且 ≤64
    with pytest.raises(ValueError):
        mcp_tool_name("a" * 60, "tool" * 10)          # 超长
    with pytest.raises(ValueError):
        mcp_tool_name("bad.skill", "tool")            # 点号不允许


# ── 装配与暴露清单 ──

def test_build_exposes_dispatchable_tools(mcp_ctx):
    """全部已注册工具都进入暴露清单，且名字符合 MCP 规则。"""
    registry, index, _ = mcp_ctx
    assert len(index) >= 90, f"暴露工具数异常: {len(index)}"
    pat = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
    for name, (skill, tool) in index.items():
        assert pat.match(name), name
        assert registry.get_tool_spec(skill, tool) is not None, \
            f"{name} 映射到不可派发的 {skill}.{tool}"


def test_list_tools_payload_uses_function_schema(mcp_ctx):
    """tools/list 与 function calling 同一 schema 生成器 —— 参数契约一致。"""
    registry, index, _ = mcp_ctx
    from apps.dsn_study.mcp_server import list_mcp_tools
    tools = list_mcp_tools(registry)
    by_name = {t["name"]: t for t in tools}
    assert set(by_name) == set(index), "tools/list 与 tool_index 不一致"

    t = by_name["question_bank__create_question"]
    assert t["description"], "工具描述缺失"
    props = t["inputSchema"]["properties"]
    assert "subject" in props and "content" in props, props
    assert t["inputSchema"]["type"] == "object"


# ── 派发 ──

def test_invoke_create_and_get_roundtrip(mcp_ctx):
    """MCP 语义的真实工具往返：建题 → 读题（数据落临时库）。"""
    registry, index, _ = mcp_ctx
    from apps.dsn_study.mcp_server import invoke_mcp_tool

    created = json.loads(asyncio.run(invoke_mcp_tool(
        registry, index, "question_bank__create_question", {
            "subject": "math", "content": "勾股定理适用于哪类三角形?",
            "answer": "A", "type_name": "选择题", "difficulty": 2,
            "options": ["直角三角形", "等边三角形", "任意三角形", "无法确定"],
        })))
    assert created["success"], created
    qid = created["result"]["question_id"]

    got = json.loads(asyncio.run(invoke_mcp_tool(
        registry, index, "question_bank__get_question",
        {"question_id": qid})))
    assert got["success"], got
    assert "勾股定理" in json.dumps(got["result"], ensure_ascii=False)


def test_invoke_unknown_tool_returns_error_payload(mcp_ctx):
    """未知工具 → 错误载荷（不断协议连接，调用方 LLM 可读）。"""
    registry, index, _ = mcp_ctx
    from apps.dsn_study.mcp_server import invoke_mcp_tool
    out = json.loads(asyncio.run(
        invoke_mcp_tool(registry, index, "no__such_tool", {})))
    assert out["success"] is False and "未知工具" in out["error"]


def test_invoke_exception_folds_into_payload(mcp_ctx):
    """工具抛异常（如非法参数）→ 折返 {"success": false, "error": …}。"""
    registry, index, _ = mcp_ctx
    from apps.dsn_study.mcp_server import invoke_mcp_tool
    out = json.loads(asyncio.run(invoke_mcp_tool(
        registry, index, "question_bank__get_question",
        {"question_id": 1, "bogus_kwarg": True})))   # 意外参数 → TypeError
    assert out["success"] is False, out
    assert "TypeError" in out["error"], out


def test_async_tool_uses_async_dispatch(mcp_ctx, monkeypatch):
    """协程工具走 call_tool_async 分支（MCP 会话工具需要 await 外部资源）。"""
    registry, index, _ = mcp_ctx
    from apps.dsn_study.mcp_server import invoke_mcp_tool

    called = {}

    async def _fake_async(skill, tool, params):
        called.update(skill=skill, tool=tool, params=params)
        return {"ok": True, "via": "async"}

    monkeypatch.setattr(registry, "is_async_tool", lambda s, t: True)
    monkeypatch.setattr(registry, "call_tool_async", _fake_async)
    out = json.loads(asyncio.run(
        invoke_mcp_tool(registry, index, "question_bank__search_questions",
                        {"keyword": "x"})))
    assert out["success"] and out["result"]["via"] == "async", out
    assert called["skill"] == "question_bank"


# ── 端到端：子进程 + 真实 stdio MCP 客户端 ──

def test_real_stdio_mcp_roundtrip(tmp_path):
    """真实子进程起 stdio 服务，官方 MCP 客户端完成 initialize/list/call。"""
    mcp = pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = os.environ.copy()
    env.update({
        "QUESTION_BANK_DB_PATH": str(tmp_path / "qb.db"),
        "TASK_MANAGER_ENABLED": "false",
        "MEMORY_ENABLED": "false",
        "MCP_ENABLED": "false",            # 不连 Obsidian 消费桥
        "MCP_EXPOSE_ENABLED": "true",
        "PYTHONPATH": str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", ""),
    })
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "apps.dsn_study.mcp_server"],
        cwd=str(REPO_ROOT), env=env)

    async def _run():
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                listed = await session.list_tools()
                names = [t.name for t in listed.tools]
                result = await session.call_tool(
                    "question_bank__create_question", {
                        "subject": "math", "content": "测试: 2+2=?",
                        "answer": "B", "type_name": "选择题", "difficulty": 1,
                        "options": ["3", "4", "5", "6"],
                    })
                return names, result

    names, result = asyncio.run(asyncio.wait_for(_run(), timeout=90))
    assert "question_bank__create_question" in names
    assert len(names) >= 90
    assert result.isError is False
    payload = json.loads(result.content[0].text)
    assert payload["success"] and payload["result"]["question_id"] > 0, payload
