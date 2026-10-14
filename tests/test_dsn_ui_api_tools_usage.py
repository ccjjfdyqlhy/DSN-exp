# tests/test_dsn_ui_api_tools_usage.py
# 回归测试：通过 API 调用时
#   1) 请求方在 body.tools 里声明的工具必须下发给模型（标准 OpenAI 函数调用），
#      且 tool_calls 以 finish_reason="tool_calls" 回传给调用方；
#   2) 客户端必须能拿到缓存命中与读取百分比（标准 usage + DSN 扩展）。
#
# 现场问题：
#   * /v1/chat/completions 从不读取 body.tools —— 工具被静默丢弃，模型看不到；
#   * timings 只以自定义事件下发，标准客户端读不到 usage，更没有 cached_tokens。

from __future__ import annotations

import pytest

from apps.dsn_ui.server import (
    _dsn_usage_extras,
    _normalize_request_tools,
    _normalize_tool_call_deltas,
    _openai_usage_from_timings,
)


# ────────────────────── tools 归一化 ──────────────────────

def test_normalize_openai_style_tools():
    """标准 OpenAI 形状 [{type:function, function:{...}}] → 裸 function。"""
    raw = [
        {"type": "function", "function": {"name": "get_weather", "description": "查天气",
                                          "parameters": {"type": "object", "properties": {}}}},
    ]

    out = _normalize_request_tools(raw)

    assert out is not None and len(out) == 1
    assert out[0]["name"] == "get_weather"
    assert "function" not in out[0]


def test_normalize_bare_function_tools():
    """也接受裸 function 写法。"""
    out = _normalize_request_tools([{"name": "f", "description": "d"}])

    assert out == [{"name": "f", "description": "d"}]


def test_normalize_drops_invalid_and_returns_none_when_empty():
    """非法条目被丢弃；没有可用工具时返回 None（保持"未传"语义）。"""
    assert _normalize_request_tools(None) is None
    assert _normalize_request_tools([]) is None
    assert _normalize_request_tools([{"type": "function", "function": {}}]) is None
    assert _normalize_request_tools(["nope", 42]) is None

    mixed = _normalize_request_tools([{"name": "ok"}, {"nope": 1}])
    assert [t["name"] for t in mixed] == ["ok"]


# ────────────────── 工具调用增量形状（关键兼容点）──────────────────

def test_tool_call_deltas_are_normalized_to_openai_shape():
    """扁平 {name,arguments} → 标准 {type,function:{name,arguments}}。

    消费方（OpenAI SDK / LangChain / 本仓库前端）只读 delta.function.*，
    扁平结构会被静默忽略，表现为"模型调不了工具"。
    """
    raw = [
        {"index": 0, "id": "call_1", "name": "get_weather", "arguments": '{"city":'},
        {"index": 0, "id": "", "name": "", "arguments": '"SH"}'},
    ]

    out = _normalize_tool_call_deltas(raw)

    assert out[0] == {
        "index": 0,
        "id": "call_1",
        "type": "function",
        "function": {"name": "get_weather", "arguments": '{"city":'},
    }
    # 后续分片按 OpenAI 惯例省略 id/type/name，只带 arguments
    assert out[1]["index"] == 0
    assert "id" not in out[1]
    assert out[1]["function"] == {"arguments": '"SH"}'}


def test_tool_call_deltas_handles_garbage():
    assert _normalize_tool_call_deltas(None) == []
    assert _normalize_tool_call_deltas(["x", 1]) == []
    assert _normalize_tool_call_deltas([{"arguments": "{}"}]) == [
        {"index": 0, "function": {"arguments": "{}"}}
    ]


# ────────────────────── usage / 缓存命中 ──────────────────────

# llama.cpp 语义：prompt_n 是本轮**实际评估**的 token，cache_n 是**复用**的
# 前缀 token。完整 prompt = prompt_n + cache_n。
TIMINGS = {"prompt_n": 250, "prompt_ms": 500.0, "predicted_n": 50, "predicted_ms": 1000.0, "cache_n": 750}


def test_openai_usage_maps_timings():
    """llama-server timings → 标准 OpenAI usage 字段。"""
    usage = _openai_usage_from_timings(TIMINGS)

    # 完整 prompt = 实际评估 + 缓存复用
    assert usage["prompt_tokens"] == 1000
    assert usage["completion_tokens"] == 50
    assert usage["total_tokens"] == 1050
    # 缓存命中是标准字段 prompt_tokens_details.cached_tokens
    assert usage["prompt_tokens_details"]["cached_tokens"] == 750
    assert usage["prompt_tokens_details"]["cache_hit_rate"] == 0.75


def test_cache_hit_rate_never_exceeds_one():
    """回归：cache_n 可能远大于 prompt_n（实测 79 vs 4）。

    若误用 cache_n / prompt_n 会算出 1975% 这种荒谬命中率。
    """
    usage = _openai_usage_from_timings(
        {"prompt_n": 4, "cache_n": 79, "predicted_n": 10, "predicted_ms": 100}
    )

    assert usage["prompt_tokens"] == 83
    assert usage["prompt_tokens_details"]["cached_tokens"] == 79
    assert usage["prompt_tokens_details"]["cache_hit_rate"] == round(79 / 83, 4)
    assert 0.0 <= usage["prompt_tokens_details"]["cache_hit_rate"] <= 1.0


def test_openai_usage_without_prompt_tokens():
    """没有 prompt token 时不应出现除零或伪造的 details。"""
    usage = _openai_usage_from_timings({"predicted_n": 5})

    assert usage["prompt_tokens"] == 0
    assert usage["completion_tokens"] == 5
    assert "prompt_tokens_details" not in usage


def test_dsn_usage_extras_reports_hit_and_read_rates():
    """扩展块给出缓存命中率与"实际读取"占比。"""
    extra = _dsn_usage_extras(TIMINGS)

    assert extra["cache_hit_rate"] == 0.75
    # 未命中的 25% 才是真正被读取/预填充的部分
    assert extra["prompt_read_rate"] == 0.25
    assert extra["prompt_evaluated_tokens"] == 250
    assert extra["prompt_tokens"] == 1000
    assert extra["prompt_tokens_per_second"] == 500.0
    assert extra["predicted_tokens_per_second"] == 50.0


def test_dsn_usage_extras_zero_safe():
    extra = _dsn_usage_extras({})

    assert extra["cache_hit_rate"] == 0.0
    assert extra["prompt_read_rate"] == 0.0
    assert extra["prompt_tokens_per_second"] == 0.0


# ────────────────────── agent 侧工具下发 ──────────────────────

class _FakeOrchestrator:
    """记录收到的 tools，并可选地产生一次 tool_call。"""

    def __init__(self, *, emit_tool_call: bool):
        self.seen_tools = "unset"
        self.emit_tool_call = emit_tool_call

    def get_model_ctx_size(self, name):
        return 8192

    async def stream(self, messages, tools=None, **kwargs):
        self.seen_tools = tools
        if self.emit_tool_call:
            yield {"tool_calls": [{
                "index": 0, "id": "call_1", "name": "get_weather", "arguments": '{"city":"SH"}',
            }]}
        else:
            yield "hello"

    def invoke(self, messages, tools=None, **kwargs):
        self.seen_tools = tools

        class _R:
            content = "hello"
            tool_calls = []
            usage = {}
            model = "m"
            finish_reason = "stop"
            reasoning_content = None

        return _R()


@pytest.fixture()
def coordinator():
    import apps.dsn_ui.agent as agent_mod

    def _make(emit_tool_call: bool):
        orch = _FakeOrchestrator(emit_tool_call=emit_tool_call)
        c = agent_mod.DSNUIAgentCoordinator.__new__(agent_mod.DSNUIAgentCoordinator)
        c.orchestrator = orch
        c._max_steps = 1
        c._tool_max_output_chars = 1000
        c.emotion_engine = type("E", (), {
            "evaluate_text_stimulus": lambda self, t: None,
            "perception_prompt": lambda self: "",
            "get_state": lambda self: {},
            "get_summary": lambda self: "",
        })()
        c.topic_mgr = type("T", (), {
            "assemble_context_messages": lambda self, **kw: [],
            "get_assembly_stats": lambda self: {},
            "topics": {}, "memos": [], "current_topic_id": None,
            "last_converged_topic": None,
        })()
        c._post_turn = lambda *a, **k: None
        c.assemble_system_prompt = lambda execution_mode=False, client_tools=None: "p"
        c._resolve_max_tokens = lambda mt, ctx: 128
        c._apply_context_strategy = lambda **kw: False
        c.pv3 = None
        # execution_mode 分支会构造 AgentLoop，这里给一个最小替身
        c.tool_coordinator = type("TC", (), {
            "tool_reg": type("TR", (), {"names": lambda self: set()})(),
            "toolbox": None,
        })()
        return c, orch

    return _make


TOOLS = [{"name": "get_weather", "description": "查天气",
          "parameters": {"type": "object", "properties": {}}}]


@pytest.mark.asyncio
async def test_client_tools_are_declared_to_model(coordinator):
    """body.tools 必须真的传到 orchestrator（历史实现完全丢弃）。"""
    c, orch = coordinator(emit_tool_call=False)

    async for _ in c.chat_stream(
        messages_raw=[{"role": "user", "content": "hi"}],
        model_name="m", client_tools=TOOLS,
    ):
        pass

    assert orch.seen_tools == TOOLS, "请求方声明的工具没有下发给模型"


@pytest.mark.asyncio
async def test_no_tools_means_no_schema(coordinator):
    """没传 tools 时不应凭空下发空 schema。"""
    c, orch = coordinator(emit_tool_call=False)

    async for _ in c.chat_stream(
        messages_raw=[{"role": "user", "content": "hi"}], model_name="m",
    ):
        pass

    assert orch.seen_tools is None


@pytest.mark.asyncio
async def test_tool_call_finish_reason(coordinator):
    """模型返回工具调用时必须以 finish_reason=tool_calls 收尾。"""
    c, orch = coordinator(emit_tool_call=True)

    events = []
    async for ev in c.chat_stream(
        messages_raw=[{"role": "user", "content": "hi"}],
        model_name="m", client_tools=TOOLS,
    ):
        events.append(ev)

    assert any(e.get("type") == "tool_calls" for e in events), "tool_calls 未透传"
    done = [e for e in events if e.get("type") == "done"]
    assert done and done[0]["finish_reason"] == "tool_calls", f"实际 {done!r}"


@pytest.mark.asyncio
async def test_plain_reply_finish_reason_stop(coordinator):
    """普通回复仍是 stop。"""
    c, orch = coordinator(emit_tool_call=False)

    events = []
    async for ev in c.chat_stream(
        messages_raw=[{"role": "user", "content": "hi"}],
        model_name="m", client_tools=TOOLS,
    ):
        events.append(ev)

    done = [e for e in events if e.get("type") == "done"]
    assert done and done[0]["finish_reason"] == "stop"


@pytest.mark.asyncio
async def test_execution_mode_ignores_client_tools(coordinator, monkeypatch):
    """execution_mode 下由 DSN 工具箱接管，请求方的 tools 不下发（避免
    服务端去执行客户端函数）。"""
    import apps.dsn_ui.agent as agent_mod

    class _NoopLoop:
        def __init__(self, **kwargs):
            pass

        async def run_stream(self, messages):
            yield agent_mod.StreamEvent(kind="done", hit_max=False, round=1)

    monkeypatch.setattr(agent_mod, "AgentLoop", _NoopLoop)

    c, orch = coordinator(emit_tool_call=False)

    async for _ in c.chat_stream(
        messages_raw=[{"role": "user", "content": "hi"}],
        model_name="m", execution_mode=True, client_tools=TOOLS,
    ):
        pass

    # execution_mode 分支走 AgentLoop，不经过 orchestrator.stream
    assert orch.seen_tools == "unset"
