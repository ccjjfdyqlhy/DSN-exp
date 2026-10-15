# tests/test_dsn_ui_tool_roundtrip_cache.py
# 回归测试：
#   1) 工具执行结果必须回传给模型（保留 assistant.tool_calls → role=tool 的往返）；
#   2) 相同请求重复发送时必须真正命中前缀缓存（cache_n > 0）。
#
# 现场问题：
#   * DSN 模式下上下文交给话题记忆装配，而它只产出「一条 system + 一条 user」——
#     role=tool 的结果被整段丢掉，模型永远看不到工具执行结果，
#     表现为反复调用同一个工具或回答"没有拿到结果"。
#   * system 提示词里含 PEV3 人格与情绪状态（每轮都变），前缀缓存从头就失效，
#     cache_n 恒为 0，前端显示"缓存命中 0%"。

from __future__ import annotations

import pytest

from apps.dsn_ui.agent import DSNUIAgentCoordinator


TOOLS = [{"name": "get_weather", "description": "查天气",
          "parameters": {"type": "object", "properties": {"city": {"type": "string"}}}}]


def _tool_conversation() -> list[dict]:
    """一次完整的工具往返：user → assistant(tool_calls) → tool(result)。"""
    return [
        {"role": "user", "content": "上海天气？"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"city":"Shanghai"}'},
            }],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "上海 22C 多云"},
    ]


# ────────────────── 工具往返必须完整保留 ──────────────────

def test_conversation_messages_preserve_tool_roundtrip():
    """assistant.tool_calls 与 role=tool 都要在上下文里，且顺序不变。"""
    msgs = DSNUIAgentCoordinator._build_conversation_messages(
        _tool_conversation(), "你是助手"
    )

    assert [m.role for m in msgs] == ["system", "user", "assistant", "tool"]
    # assistant 的 tool_calls 必须带回去，否则 tool 消息没有对应的调用
    assert msgs[2].tool_calls and msgs[2].tool_calls[0]["id"] == "call_1"
    # tool 结果与 tool_call_id 必须一致
    assert msgs[3].tool_call_id == "call_1"
    assert msgs[3].content == "上海 22C 多云"


def test_conversation_messages_replace_client_system():
    """客户端的 system 被 DSN 合成的那条替换（不重复注入）。"""
    raw = [{"role": "system", "content": "客户端提示词"}, {"role": "user", "content": "hi"}]

    msgs = DSNUIAgentCoordinator._build_conversation_messages(raw, "DSN 提示词")

    systems = [m for m in msgs if m.role == "system"]
    assert len(systems) == 1
    assert systems[0].content == "DSN 提示词"


def test_conversation_messages_preserve_multimodal():
    from infra.orchestrator.base import count_image_parts

    raw = [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        {"type": "text", "text": "看图"},
    ]}]

    msgs = DSNUIAgentCoordinator._build_conversation_messages(raw, "s")

    assert count_image_parts(msgs) == 1


def test_conversation_messages_preserve_assistant_reasoning():
    raw = [
        {"role": "user", "content": "问"},
        {"role": "assistant", "content": "答", "reasoning_content": "想了一下"},
    ]

    msgs = DSNUIAgentCoordinator._build_conversation_messages(raw, "s")

    # [system, user, assistant]
    assert msgs[2].reasoning_content == "想了一下"


# ────────────────── system 提示词前缀稳定性 ──────────────────

class _Coord:
    """最小 coordinator：只测提示词缓存本身。"""

    base_system_prompt = "base"
    uid = 1
    pv3 = None
    # 实例方法是「无状态」的，直接借用真实实现即可
    _tools_signature = staticmethod(DSNUIAgentCoordinator._tools_signature)
    assemble_system_prompt = DSNUIAgentCoordinator.assemble_system_prompt

    def __init__(self):
        self.calls = 0
        self._system_prompt_cache = {}
        self.emotion_engine = type("E", (), {"perception_prompt": lambda self: ""})()

    def _build_system_prompt(self, execution_mode=False, client_tools=None):
        self.calls += 1
        return f"prompt(exec={execution_mode},tools={len(client_tools or [])})"


def test_system_prompt_is_cached_per_mode_and_tools():
    """同一（模式, 工具集）只构建一次 —— 前缀缓存能命中的前提。"""
    c = _Coord()

    a = c.assemble_system_prompt(execution_mode=False, client_tools=TOOLS)
    b = c.assemble_system_prompt(execution_mode=False, client_tools=TOOLS)

    assert a == b
    assert c.calls == 1, "同一键重复构建会让前缀每轮都变，缓存永远不命中"

    # 换模式 / 换工具集必须重建
    c.assemble_system_prompt(execution_mode=True, client_tools=TOOLS)
    c.assemble_system_prompt(execution_mode=False, client_tools=None)
    assert c.calls == 3


def test_tools_signature_is_order_independent():
    """同样一组工具，顺序不同不应导致重建缓存。"""
    a = [{"name": "b"}, {"name": "a"}]
    b = [{"name": "a"}, {"name": "b"}]

    assert DSNUIAgentCoordinator._tools_signature(a) == DSNUIAgentCoordinator._tools_signature(b)
    assert DSNUIAgentCoordinator._tools_signature(None) == ""
    assert DSNUIAgentCoordinator._tools_signature([]) == ""


def test_prompt_mentions_tool_usage_when_tools_present():
    """带工具时提示词要说明"结果会以 tool 消息返回、别重复调用"。"""
    c = _Coord()
    # 用真实的 _build_system_prompt（不是 _Coord 里的计数替身）
    prompt = DSNUIAgentCoordinator._build_system_prompt(
        c, execution_mode=False, client_tools=TOOLS
    )

    assert "函数调用" in prompt
    assert "get_weather" in prompt
    assert "tool" in prompt


# ────────────────── 端到端：agent 不再丢 tool ──────────────────

class _RecordingOrchestrator:
    def __init__(self):
        self.seen = None
        self.seen_tools = None

    def get_model_ctx_size(self, name):
        return 8192

    async def stream(self, messages, tools=None, **kwargs):
        self.seen = messages
        self.seen_tools = tools
        yield "done"


@pytest.fixture()
def coordinator():
    import apps.dsn_ui.agent as agent_mod

    orch = _RecordingOrchestrator()
    c = agent_mod.DSNUIAgentCoordinator.__new__(agent_mod.DSNUIAgentCoordinator)
    c.orchestrator = orch
    c._max_steps = 1
    c._tool_max_output_chars = 1000
    c._system_prompt_cache = {}
    c.base_system_prompt = "DSN base"
    c.uid = 1
    c.pv3 = None
    c.emotion_engine = type("E", (), {
        "evaluate_text_stimulus": lambda self, t: None,
        "perception_prompt": lambda self: "",
        "get_state": lambda self: {},
        "get_summary": lambda self: "",
    })()
    c.topic_mgr = type("T", (), {
        "assemble_context_messages": lambda self, **kw: [
            agent_mod.ChatMessage.system("记忆装配"),
            agent_mod.ChatMessage.user("上海天气？"),
        ],
        "get_assembly_stats": lambda self: {},
        "topics": {}, "memos": [], "current_topic_id": None,
        "last_converged_topic": None,
    })()
    c._post_turn = lambda *a, **k: None
    c._resolve_max_tokens = lambda mt, ctx: 128
    c._apply_context_strategy = lambda **kw: False
    c.tool_coordinator = type("TC", (), {
        "tool_reg": type("TR", (), {"names": lambda self: set()})(),
        "toolbox": None,
    })()
    return c, orch


@pytest.mark.asyncio
async def test_tool_result_reaches_orchestrator(coordinator):
    """带 tools 时必须走"保留完整对话"分支，tool 结果出现在上下文里。"""
    c, orch = coordinator

    async for _ in c.chat_stream(
        messages_raw=_tool_conversation(),
        model_name="m",
        client_tools=TOOLS,
    ):
        pass

    roles = [m.role for m in orch.seen]
    assert "tool" in roles, f"工具结果没有传给模型，实际 roles={roles}"
    assert roles == ["system", "user", "assistant", "tool"]
    assert orch.seen_tools == TOOLS


@pytest.mark.asyncio
async def test_without_tools_still_uses_memory_assembly(coordinator):
    """没带工具时保持原行为（话题记忆装配），不引入回归。"""
    c, orch = coordinator

    async for _ in c.chat_stream(
        messages_raw=_tool_conversation(), model_name="m",
    ):
        pass

    roles = [m.role for m in orch.seen]
    assert roles == ["system", "user"], f"实际 {roles}"
    assert orch.seen[0].content == "记忆装配"
