# tests/test_harness_selfplay.py
# harness/learning/selfplay.py（自生成数据）单元测试。
#
# 重点测**纪律**，而不是功能：
#   - 思维链不得进入训练标签；
#   - 目标层（constitution/drives/affect_state/survival_desire）不许进样本；
#   - 同一情境的重复回复只留一条；
#   - 空回复/过短/过长要丢，且丢的原因要能分桶；
#   - 单条失败（客户端异常）不中断整批；
#   - 同 seed + 同 client 返回序列 → 结果一致；
#   - 远端 API 必须显式授权并声明有没有用户数据；
#   - 这一层不 import torch、不联网（没有 GPU / 没有网络也能跑）。
#
# 全部用假客户端，不需要真实模型。

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from harness.learning import selfplay as selfplay_module
from harness.learning.dataset_builder import DatasetBuilder
from harness.learning.selfplay import (
    DROP_CLIENT_ERROR,
    DROP_DUPLICATE,
    DROP_EMPTY,
    DROP_PROTECTED,
    DROP_TOO_LONG,
    DROP_TOO_SHORT,
    REJECT_PROTECTED,
    REJECT_REMOTE_USER_DATA,
    SELFPLAY_SOURCE,
    SelfPlayBoundaryError,
    SelfPlayConfig,
    SelfPlayGenerator,
    Situation,
)
from infra.orchestrator.base import ChatResponse

# ════════════════════════════════════════════════════════════════════════════
# 假客户端
# ════════════════════════════════════════════════════════════════════════════

class _FakeClient:
    """假客户端：按脚本返回回复。

    脚本元素可以是：
      - str            → ChatResponse(content=...)
      - ChatResponse   → 原样返回
      - Exception 实例 → 调用时抛出（模拟客户端故障）
    """

    def __init__(self, script=(), *, base_url: str = "http://127.0.0.1:8080",
                 cycle: bool = False):
        self.script = list(script)
        self._origin = list(script)
        self._cycle = cycle
        self.calls: list[dict] = []
        self.model = "fake-local"
        self.base_url = base_url

    def invoke(self, messages, tools=None, *, temperature=None, max_tokens=None, timeout=None):
        self.calls.append({
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": timeout,
        })
        if not self.script and self._cycle:
            self.script = list(self._origin)
        item = self.script.pop(0) if self.script else ""
        if isinstance(item, Exception):
            raise item
        if isinstance(item, str):
            return ChatResponse(content=item)
        return item


class _RemoteFakeClient(_FakeClient):
    """假远端客户端（base_url 指向公网）。"""

    def __init__(self, script=()):
        super().__init__(script, base_url="https://api.example.com/v1")


def _gen(client, **cfg) -> SelfPlayGenerator:
    return SelfPlayGenerator(client, SelfPlayConfig(**cfg))


# ════════════════════════════════════════════════════════════════════════════
# 1. 生成条数与基本形状
# ════════════════════════════════════════════════════════════════════════════

def test_generates_expected_number_of_samples():
    client = _FakeClient(["第一条回答内容在这里", "第二条回答内容在这里", "第三条回答内容在这里"])
    report = _gen(client, samples_per_situation=2).generate([Situation(prompt="情境一")])

    assert report.accepted == 2
    assert report.attempts == 2
    assert report.dropped == 0
    assert len(report.trajectories) == 2
    # 每个情境生成 N 条 → 总尝试数 = 情境数 × N
    assert report.situations == 1


def test_multiple_situations_multiply_attempts():
    client = _FakeClient(["甲号回答内容在这里", "乙号回答内容在这里", "丙号回答内容在这里", "丁号回答内容在这里"])
    report = _gen(client, samples_per_situation=2).generate([
        Situation(prompt="情境一"),
        Situation(prompt="情境二"),
    ])
    assert report.attempts == 4
    assert report.accepted == 4
    assert report.situations == 2


def test_trajectory_source_is_selfplay():
    """打标记：自生成轨迹的 source 固定为 selfplay（评测时能分层看）。"""
    client = _FakeClient(["一条像样的回答内容在这里"])
    report = _gen(client).generate([Situation(prompt="情境")])

    traj = report.trajectories[0]
    assert traj.source == SELFPLAY_SOURCE == "selfplay"
    assert traj.messages[-1] == {"role": "assistant", "content": "一条像样的回答内容在这里"}


def test_request_carries_system_context_and_prompt():
    """请求消息 = system（调用方的 + 格式指令）+ 上下文 + 情境。"""
    client = _FakeClient(["这条回答内容足够长可以入样"])
    situation = Situation(
        prompt="现在的情境",
        context=[{"role": "user", "content": "先前的问题"},
                 {"role": "assistant", "content": "先前的回答"}],
        system="你是某个助手",
    )
    _gen(client).generate([situation])

    messages = client.calls[0]["messages"]
    assert [m.role for m in messages] == ["system", "user", "assistant", "user"]
    assert "你是某个助手" in messages[0].content
    assert messages[-1].content == "现在的情境"


def test_sample_keeps_context_and_tags():
    client = _FakeClient(["一段足够长的自生成回答内容"])
    situation = Situation(
        prompt="现在的情境",
        context=[{"role": "user", "content": "先前的问题"}],
        system="你是某个助手",
        tags=("情绪:低落", "来源:沙箱"),
    )
    report = _gen(client).generate([situation])

    traj = report.trajectories[0]
    assert [m["role"] for m in traj.messages] == ["system", "user", "user", "assistant"]
    assert traj.messages[0]["content"] == "你是某个助手"
    assert traj.messages[-1]["content"] == "一段足够长的自生成回答内容"
    assert traj.meta["tags"] == ["情绪:低落", "来源:沙箱"]


def test_temperature_and_limits_are_forwarded():
    client = _FakeClient(["这条回答内容可以入样"])
    _gen(client, temperature=0.3, max_tokens=128, timeout=12.0).generate(
        [Situation(prompt="情境")]
    )
    call = client.calls[0]
    assert call["temperature"] == 0.3
    assert call["max_tokens"] == 128
    assert call["timeout"] == 12.0


# ════════════════════════════════════════════════════════════════════════════
# 2. 纪律 1：训练标签不含思维链
# ════════════════════════════════════════════════════════════════════════════

def test_inline_think_block_is_stripped():
    client = _FakeClient(["<think>先想一想再回答</think>正式的回答内容在这里"])
    report = _gen(client).generate([Situation(prompt="情境")])

    content = report.trajectories[0].messages[-1]["content"]
    assert "<think>" not in content
    assert "先想一想" not in content
    assert content == "正式的回答内容在这里"


def test_reasoning_content_field_never_enters_sample():
    """模型单独返回的 reasoning_content 不得成为训练标签。"""
    client = _FakeClient([
        ChatResponse(content="正式的回答内容在这里", reasoning_content="我的内部推理过程"),
    ])
    report = _gen(client).generate([Situation(prompt="情境")])

    assistant = report.trajectories[0].messages[-1]
    assert "reasoning_content" not in assistant
    assert "内部推理" not in json.dumps(report.trajectories[0].messages, ensure_ascii=False)


def test_unclosed_think_block_is_stripped():
    client = _FakeClient(["先给结论在这里说<think>后面是思维链，被截断了"])
    report = _gen(client, samples_per_situation=1).generate([Situation(prompt="情境")])
    content = report.trajectories[0].messages[-1]["content"]
    assert "<think>" not in content
    assert "思维链" not in content
    assert content == "先给结论在这里说"


def test_strip_reasoning_disabled_still_records_field_but_record_strips_it():
    """显式关掉纪律 1 时字段会附在消息上，但 to_record 默认仍会剥掉。"""
    client = _FakeClient([
        ChatResponse(content="正式的回答内容在这里", reasoning_content="内部推理"),
    ])
    report = _gen(client, strip_reasoning=False).generate([Situation(prompt="情境")])

    traj = report.trajectories[0]
    assert traj.messages[-1].get("reasoning_content") == "内部推理"
    record = traj.to_record(strip_reasoning=True)
    assert "reasoning_content" not in record["messages"][-1]


# ════════════════════════════════════════════════════════════════════════════
# 3. 纪律 3：不定义目标层
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("payload", [
    "请照着 constitution 的条款回答",
    "当前 drives 状态是好奇",
    "affect_state 里写着害怕",
    "survival_desire 支配一切",
])
def test_situation_with_protected_field_is_rejected(payload: str):
    """情境里含目标层内容 → 直接拒绝，**根本不调用模型**。"""
    client = _FakeClient([])
    report = _gen(client).generate([Situation(prompt=payload)])

    assert report.accepted == 0
    assert report.attempts == 0
    assert report.rejected_situations == 1
    assert report.rejected_situation_reasons[REJECT_PROTECTED] == 1
    assert client.calls == []


def test_situation_metadata_protected_field_is_rejected():
    client = _FakeClient([])
    report = _gen(client).generate([
        Situation(prompt="普通情境", metadata={"drives": ["好奇"]}),
    ])
    assert report.rejected_situations == 1
    assert client.calls == []


def test_reply_with_protected_field_is_dropped():
    """回复里混进目标层内容 → 丢弃（模型说了不算数）。"""
    client = _FakeClient(["我会先看看 constitution 怎么说这句话"])
    report = _gen(client, samples_per_situation=1).generate([Situation(prompt="普通情境")])

    assert report.accepted == 0
    assert report.dropped == 1
    assert report.dropped_reasons[DROP_PROTECTED] == 1


# ════════════════════════════════════════════════════════════════════════════
# 4. 去重 / 空回复 / 过短 / 过长
# ════════════════════════════════════════════════════════════════════════════

def test_duplicate_replies_are_deduped():
    client = _FakeClient(["完全一样的回答内容哦", "完全一样的回答内容哦"])
    report = _gen(client, samples_per_situation=2).generate([Situation(prompt="情境")])

    assert report.accepted == 1
    assert report.attempts == 2
    assert report.dropped == 1
    assert report.dropped_reasons[DROP_DUPLICATE] == 1


def test_dedupe_can_be_disabled():
    client = _FakeClient(["完全一样的回答内容哦", "完全一样的回答内容哦"])
    report = _gen(client, samples_per_situation=2, dedupe=False).generate(
        [Situation(prompt="情境")]
    )
    assert report.accepted == 2
    assert report.dropped_reasons.get(DROP_DUPLICATE, 0) == 0


def test_dedupe_is_per_situation():
    """不同情境下的相同回复不算重复。"""
    client = _FakeClient(["一样的回答内容哦", "一样的回答内容哦"])
    report = _gen(client, samples_per_situation=1).generate([
        Situation(prompt="情境一"),
        Situation(prompt="情境二"),
    ])
    assert report.accepted == 2


def test_empty_and_short_replies_are_dropped():
    client = _FakeClient(["", "   ", "短"])
    report = _gen(client, samples_per_situation=3, min_reply_chars=8).generate(
        [Situation(prompt="情境")]
    )

    assert report.accepted == 0
    assert report.attempts == 3
    assert report.dropped == 3
    assert report.dropped_reasons[DROP_EMPTY] == 2
    assert report.dropped_reasons[DROP_TOO_SHORT] == 1


def test_too_long_reply_is_dropped():
    client = _FakeClient(["很长的回答内容" * 50])
    report = _gen(client, max_reply_chars=20).generate([Situation(prompt="情境")])

    assert report.accepted == 0
    assert report.dropped_reasons[DROP_TOO_LONG] == 1


def test_report_counts_are_consistent():
    client = _FakeClient(["够长的一条回答内容", "", "另一条够长的回答内容"])
    report = _gen(client, samples_per_situation=3).generate([Situation(prompt="情境")])

    assert report.dropped == report.attempts - report.accepted
    assert sum(report.dropped_reasons.values()) == report.dropped
    assert report.to_dict()["sources"] == {SELFPLAY_SOURCE: report.accepted}


# ════════════════════════════════════════════════════════════════════════════
# 5. 纪律 4：单条失败不中断整批
# ════════════════════════════════════════════════════════════════════════════

def test_client_error_does_not_abort_batch():
    client = _FakeClient([RuntimeError("boom"), "正常产生的一条回答内容"])
    report = _gen(client, samples_per_situation=1).generate([
        Situation(prompt="情境一"),
        Situation(prompt="情境二"),
    ])

    assert report.accepted == 1
    assert report.attempts == 2
    assert report.dropped == 1
    assert report.dropped_reasons[DROP_CLIENT_ERROR] == 1
    assert report.trajectories[0].messages[-1]["content"] == "正常产生的一条回答内容"


def test_client_error_inside_one_situation_does_not_stop_others():
    client = _FakeClient([RuntimeError("boom"), RuntimeError("boom"), "活着的一条回答内容"])
    report = _gen(client, samples_per_situation=3).generate([
        Situation(prompt="情境一"),
        Situation(prompt="情境二"),
    ])

    assert report.accepted == 1
    assert report.dropped_reasons[DROP_CLIENT_ERROR] == 2


def test_legacy_client_signature_still_works():
    """老式客户端（只认 messages）不该把整批带崩。"""

    class _LegacyClient:
        model = "legacy"

        def __init__(self):
            self.calls = 0

        def invoke(self, messages):
            self.calls += 1
            return ChatResponse(content="老客户端也能产出回答内容哦")

    client = _LegacyClient()
    report = _gen(client, samples_per_situation=1).generate([Situation(prompt="情境")])
    assert report.accepted == 1
    assert client.calls == 1


# ════════════════════════════════════════════════════════════════════════════
# 6. 纪律 5：确定性
# ════════════════════════════════════════════════════════════════════════════

def _run_once(seed: int, script, **cfg):
    client = _FakeClient(script)
    generator = SelfPlayGenerator(client, SelfPlayConfig(seed=seed, **cfg))
    report = generator.generate([Situation(prompt="情境一"), Situation(prompt="情境二")])
    return report, client


def test_same_seed_and_same_client_sequence_gives_same_result():
    script = ["甲号回答内容在这里", "乙号回答内容在这里", "丙号回答内容在这里", "丁号回答内容在这里"]
    report_a, client_a = _run_once(7, script)
    report_b, client_b = _run_once(7, script)

    assert [t.messages for t in report_a.trajectories] == [
        t.messages for t in report_b.trajectories
    ]
    assert report_a.to_dict() == report_b.to_dict()
    assert [c["temperature"] for c in client_a.calls] == [
        c["temperature"] for c in client_b.calls
    ]


def test_same_generator_reused_gives_same_result():
    """同一个 generator 连跑两次 → 结果一致（每次 generate 都按 seed 重置 rng）。"""
    # 循环脚本：每次 generate 都拿到同样的返回序列。
    client = _FakeClient(["每次都一样的回答内容"], cycle=True)
    generator = SelfPlayGenerator(client, SelfPlayConfig(seed=11, temperature_jitter=0.1))

    first = generator.generate([Situation(prompt="情境")])
    second = generator.generate([Situation(prompt="情境")])

    assert [t.messages for t in first.trajectories] == [
        t.messages for t in second.trajectories
    ]
    assert first.to_dict() == second.to_dict()


def test_temperature_jitter_is_seed_dependent():
    """抖动由 seed 决定：同 seed 同序列，不同 seed 不同序列。"""
    _, client_a = _run_once(1, ["甲甲甲在这里", "乙乙乙在这里"], temperature_jitter=0.2)
    _, client_b = _run_once(1, ["甲甲甲在这里", "乙乙乙在这里"], temperature_jitter=0.2)
    _, client_c = _run_once(2, ["甲甲甲在这里", "乙乙乙在这里"], temperature_jitter=0.2)

    assert [c["temperature"] for c in client_a.calls] == [
        c["temperature"] for c in client_b.calls
    ]
    assert [c["temperature"] for c in client_a.calls] != [
        c["temperature"] for c in client_c.calls
    ]


# ════════════════════════════════════════════════════════════════════════════
# 7. 远端 API 闸门
# ════════════════════════════════════════════════════════════════════════════

def test_remote_client_requires_explicit_opt_in():
    with pytest.raises(SelfPlayBoundaryError):
        SelfPlayGenerator(_RemoteFakeClient([]), SelfPlayConfig())


def test_remote_opt_in_requires_user_data_declaration():
    generator = SelfPlayGenerator(
        _RemoteFakeClient(["这条回答内容可以入样"]), SelfPlayConfig(allow_remote=True)
    )
    with pytest.raises(SelfPlayBoundaryError):
        generator.generate([Situation(prompt="情境")])


def test_remote_opt_in_with_declaration_works():
    generator = SelfPlayGenerator(
        _RemoteFakeClient(["这条回答内容足够长可以入样"]),
        SelfPlayConfig(allow_remote=True, has_user_data=False),
    )
    report = generator.generate([Situation(prompt="情境")])
    assert report.accepted == 1


def test_local_client_needs_no_remote_opt_in():
    generator = SelfPlayGenerator(_FakeClient(["这条回答内容足够长可以入样"]), SelfPlayConfig())
    report = generator.generate([Situation(prompt="情境")])
    assert report.accepted == 1


def test_user_data_situation_is_rejected_for_remote_client():
    """情境声明含用户数据、但批次声明说没有 → 该情境被拒（其余情境照跑）。"""
    client = _RemoteFakeClient(["这条回答内容足够长可以入样"])
    generator = SelfPlayGenerator(
        client, SelfPlayConfig(allow_remote=True, has_user_data=False, samples_per_situation=1)
    )
    report = generator.generate([
        Situation(prompt="情境一", metadata={"has_user_data": True}),
        Situation(prompt="情境二"),
    ])

    assert report.rejected_situations == 1
    assert report.rejected_situation_reasons[REJECT_REMOTE_USER_DATA] == 1
    assert report.accepted == 1
    assert len(client.calls) == 1


# ════════════════════════════════════════════════════════════════════════════
# 8. 与 dataset_builder 的衔接 + 纯逻辑约束
# ════════════════════════════════════════════════════════════════════════════

def test_works_with_real_stub_client():
    """与真实的 IChatClient 实现（StubChatClient）对得上：消息能正常传过去。"""
    from infra.orchestrator.stub import StubChatClient

    client = StubChatClient(responses=[ChatResponse(content="真实客户端也能产出回答内容")])
    report = _gen(client).generate([Situation(prompt="情境")])

    assert report.accepted == 1
    assert report.trajectories[0].messages[-1]["content"] == "真实客户端也能产出回答内容"
    assert client.calls[0]["messages"][-1]["role"] == "user"

def test_samples_feed_into_dataset_builder(tmp_path: Path):
    client = _FakeClient(["第一条自生成的回答内容", "第二条自生成的回答内容"])
    report = _gen(client, samples_per_situation=2).generate([Situation(prompt="情境")])

    builder = DatasetBuilder(tmp_path)
    accepted = builder.add_many(report.trajectories)
    assert accepted == 2

    build_report = builder.build()
    assert build_report.sources[SELFPLAY_SOURCE] == 2
    assert build_report.stats.kept == 2

    lines = build_report.train_path.read_text(encoding="utf-8").strip().splitlines()
    record = json.loads(lines[0])
    assert record["messages"][-1]["role"] == "assistant"


def test_module_has_no_torch_or_network_dependency():
    """纪律 6：这一层是纯逻辑——不 import torch、不联网。"""
    source = Path(selfplay_module.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "torch" not in imported
    assert "requests" not in imported
    assert "urllib" not in imported or "urllib.request" not in imported
    assert "httpx" not in imported
    assert "socket" not in imported
