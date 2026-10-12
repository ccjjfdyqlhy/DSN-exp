# tests/test_dsn_ui_api_mode.py
# 回归测试：dsn_ui 对外 API 的两种模式。
#
#   dsn         —— 完整 DSN-exp：动态提示词 + 话题记忆 + 情绪 + 人格
#   passthrough —— 完全交给请求方：不注入任何提示词、不跑情绪与记忆系统，
#                  请求里的 messages 原样送进模型
#
# 模式由应用配置（DSN_UI_API_MODE）决定，可用 DSN_UI_API_MODE_LOCKED 锁定，
# 也允许请求方通过 api_mode / X-DSN-Api-Mode 单次覆盖。

from __future__ import annotations

import pytest

from apps.dsn_ui.agent import DSNUIAgentCoordinator
from apps.dsn_ui.config import (
    API_MODE_DSN,
    API_MODE_PASSTHROUGH,
    UIConfig,
)


# ────────────────────────── 配置解析 ──────────────────────────

def test_config_default_is_dsn(monkeypatch):
    monkeypatch.setattr(UIConfig, "API_MODE", API_MODE_DSN)
    monkeypatch.setattr(UIConfig, "API_MODE_LOCKED", False)

    assert UIConfig.resolve_api_mode() == API_MODE_DSN
    assert UIConfig.resolve_api_mode(API_MODE_PASSTHROUGH) == API_MODE_PASSTHROUGH


def test_config_locked_ignores_request_override(monkeypatch):
    """锁定后请求方无权改模式（部署方强制纯透传/强制完整 DSN）。"""
    monkeypatch.setattr(UIConfig, "API_MODE", API_MODE_PASSTHROUGH)
    monkeypatch.setattr(UIConfig, "API_MODE_LOCKED", True)

    assert UIConfig.resolve_api_mode(API_MODE_DSN) == API_MODE_PASSTHROUGH
    assert UIConfig.resolve_api_mode(None) == API_MODE_PASSTHROUGH


def test_config_invalid_value_falls_back(monkeypatch):
    """非法模式不抛错，回退到 dsn，避免把 API 打挂。"""
    monkeypatch.setattr(UIConfig, "API_MODE", "nonsense")
    monkeypatch.setattr(UIConfig, "API_MODE_LOCKED", False)

    assert UIConfig.resolve_api_mode() == API_MODE_DSN
    assert UIConfig.resolve_api_mode("also-bogus") == API_MODE_DSN


# ────────────────────── passthrough 消息构造 ──────────────────────

def test_passthrough_keeps_caller_messages_verbatim():
    """请求方给什么就是什么：不追加 system、不改写角色。"""
    raw = [
        {"role": "system", "content": "你是一个翻译引擎"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "你好"},
        {"role": "user", "content": "world"},
    ]

    msgs = DSNUIAgentCoordinator._build_passthrough_messages(raw)

    assert [m.role for m in msgs] == ["system", "user", "assistant", "user"]
    assert [m.content for m in msgs] == ["你是一个翻译引擎", "hello", "你好", "world"]


def test_passthrough_preserves_multimodal_parts():
    """多模态结构必须保留（不能拍平成字符串）。"""
    from harness.orchestrator.base import count_image_parts

    raw = [{
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            {"type": "text", "text": "描述这张图"},
        ],
    }]

    msgs = DSNUIAgentCoordinator._build_passthrough_messages(raw)

    assert count_image_parts(msgs) == 1
    assert isinstance(msgs[0].content, list)


def test_passthrough_does_not_inject_system_prompt():
    """只有 user 消息时，输出里不应凭空多出 system 段。"""
    raw = [{"role": "user", "content": "hi"}]

    msgs = DSNUIAgentCoordinator._build_passthrough_messages(raw)

    assert len(msgs) == 1
    assert msgs[0].role == "user"


def test_passthrough_handles_tool_role():
    """tool 消息的 tool_call_id 必须保留，否则上游模板报错。"""
    raw = [{"role": "tool", "content": "42", "tool_call_id": "call_1"}]

    msgs = DSNUIAgentCoordinator._build_passthrough_messages(raw)

    assert msgs[0].role == "tool"
    assert msgs[0].tool_call_id == "call_1"


# ────────────────────── 端到端：不碰记忆/情绪 ──────────────────────

class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))


class _FakeOrchestrator:
    """只记录收到的 messages，不真的推理。"""

    def __init__(self):
        self.seen = None

    def get_model_ctx_size(self, name):
        return 8192

    async def stream(self, messages, **kwargs):
        self.seen = messages
        yield "ok"

    def invoke(self, messages, **kwargs):
        self.seen = messages

        class _R:
            content = "ok"
            tool_calls = []
            usage = {}
            model = "m"
            finish_reason = "stop"
            reasoning_content = None

        return _R()


@pytest.fixture()
def coordinator(monkeypatch):
    """构造一个最小可用的 coordinator，只替换外部依赖。"""
    import apps.dsn_ui.agent as agent_mod

    orch = _FakeOrchestrator()
    coord = agent_mod.DSNUIAgentCoordinator.__new__(agent_mod.DSNUIAgentCoordinator)
    coord.orchestrator = orch
    coord._max_steps = 1
    coord._tool_max_output_chars = 1000

    # 情绪与记忆：passthrough 下必须一次都不被调用
    coord.emotion_engine = type("E", (), {
        "evaluate_text_stimulus": _Recorder(),
        "perception_prompt": lambda self: "",
        "get_state": lambda self: {},
        "get_summary": lambda self: "",
    })()
    coord.topic_mgr = type("T", (), {
        "assemble_context_messages": _Recorder(),
        "get_assembly_stats": lambda self: {},
        "topics": {},
        "memos": [],
        "current_topic_id": None,
        "last_converged_topic": None,
    })()
    coord._post_turn = _Recorder()
    coord.assemble_system_prompt = lambda execution_mode=False: "DSN 动态提示词"
    coord._resolve_max_tokens = lambda max_tokens, ctx: 128
    coord._apply_context_strategy = lambda **kw: False
    coord.pv3 = None
    return coord


@pytest.mark.asyncio
async def test_passthrough_skips_prompt_emotion_and_memory(coordinator):
    raw = [{"role": "user", "content": "hi"}]

    events = []
    async for ev in coordinator.chat_stream(
        messages_raw=raw, model_name="m", api_mode=API_MODE_PASSTHROUGH
    ):
        events.append(ev)

    # 上下文 = 调用方原样消息（无 system 注入）
    sent = coordinator.orchestrator.seen
    assert [m.role for m in sent] == ["user"]
    assert sent[0].content == "hi"

    # 情绪系统未被触发
    assert coordinator.emotion_engine.evaluate_text_stimulus.calls == []
    # 话题记忆装配未被调用
    assert coordinator.topic_mgr.assemble_context_messages.calls == []
    # 不写回记忆/人格
    assert coordinator._post_turn.calls == []
    # 不发 DSN 上下文统计事件
    assert not any(e.get("type") == "context_stats" for e in events)


@pytest.mark.asyncio
async def test_dsn_mode_still_uses_prompt_emotion_and_memory(coordinator):
    """默认模式必须保持原有行为（不能因为新增 passthrough 而回归）。"""
    raw = [{"role": "user", "content": "hi"}]

    coordinator.topic_mgr.assemble_context_messages = lambda **kw: [
        type("M", (), {"role": "system", "content": "ctx"})(),
        type("M", (), {"role": "user", "content": "hi"})(),
    ]

    async for _ in coordinator.chat_stream(
        messages_raw=raw, model_name="m", api_mode=API_MODE_DSN
    ):
        pass

    assert coordinator.emotion_engine.evaluate_text_stimulus.calls != []
    assert coordinator._post_turn.calls != []
