# tests/test_coding_agent.py
# CodingAgent 应用测试 — 证明 harness 能承载 coding agent。

from __future__ import annotations

from apps.coding_agent import CodingAgent
from infra.models.base import ChatResponse, ToolCall
from infra.models.stub import StubChatClient


def test_coding_agent_installs_tools():
    agent = CodingAgent(StubChatClient())
    names = agent.agent.tools.names()
    assert "code.read_file" in names
    assert "code.run_bash" in names
    assert "code.grep" in names


def test_coding_agent_reads_file_with_tool(tmp_path):
    f = tmp_path / "hello.txt"
    f.write_text("hello harness\n", encoding="utf-8")
    stub = StubChatClient(responses=[
        ChatResponse(content="", tool_calls=[
            ToolCall(id="1", name="code.read_file", arguments={"path": str(f)})]),
        ChatResponse(content="文件内容是 hello harness", model="stub"),
    ])
    agent = CodingAgent(stub)
    reply = agent.chat("读一下这个文件")
    assert reply == "文件内容是 hello harness"
    # 三区上下文已更新
    assert agent.ctx.history[0].content == "读一下这个文件"


def test_coding_agent_persistence(tmp_path):
    stub = StubChatClient(responses=[ChatResponse(content="ok", model="stub")])
    agent = CodingAgent(stub)
    agent.enable_persistence(db_path=str(tmp_path / "chat.db"))
    reply = agent.chat("你好")
    assert reply == "ok"
    assert agent.session_store is not None
    # 修复后的语义：每轮对话结束即持久化本轮 user/assistant 消息。
    # （旧行为是 message_count 恒为 0——chat() 从不写库，持久化是空操作。）
    assert agent.session_store.list_sessions()[0]["message_count"] == 2

    # 第二轮继续累积
    stub._responses.append(ChatResponse(content="ok2", model="stub"))
    agent.chat("再来一句")
    assert agent.session_store.list_sessions()[0]["message_count"] == 4
    history = agent.session_store.load_messages()
    assert [m.content for m in history] == ["你好", "ok", "再来一句", "ok2"]
