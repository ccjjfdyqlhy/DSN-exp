# tests/test_rc0_kernel.py
# 执行内核 SPI 的契约测试。
#
# 这些用例保证的是「换一个执行架构不改业务代码」这条设计目标：
# 任何内核只要满足 ExecutionKernel 协议，就能被同样的代码驱动。

from __future__ import annotations

import asyncio

import pytest

from harness.kernel import (
    CapabilitySet,
    ExecutionKernel,
    KernelContext,
    KernelResult,
    KernelSpec,
    ReactKernel,
)
from harness.kernel.capability import CapabilitySet as CapabilitySet2
from harness.tools.base import Tool, ToolRegistry


class FakeClient:
    """只会回一句话的假模型。"""

    def __init__(self, reply: str = 'ok', vision: bool = False,
                 supports_parallel_tool_calls: bool = False):
        self.reply = reply
        self.vision = vision
        self.supports_parallel_tool_calls = supports_parallel_tool_calls
        self.calls: list[list] = []

    async def invoke(self, messages, tools=None, **kwargs):
        self.calls.append(list(messages))
        from infra.orchestrator.base import ChatResponse
        return ChatResponse(content=self.reply)

    def stream(self, messages, tools=None, **kwargs):
        raise NotImplementedError


class Collector:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def emit(self, kind, payload):
        self.events.append((kind, payload))

    def kinds(self):
        return [k for k, _ in self.events]


# ── 协议形状 ────────────────────────────────────────────
def test_react_kernel_satisfies_the_protocol():
    kernel = ReactKernel()
    assert isinstance(kernel, ExecutionKernel)


def test_describe_returns_a_kernel_spec():
    spec = ReactKernel().describe()
    assert isinstance(spec, KernelSpec)
    assert spec.name == 'react'
    assert spec.requires_approval is True


def test_capability_set_is_shared_between_base_and_module():
    assert CapabilitySet is CapabilitySet2


# ── 能力协商 ────────────────────────────────────────────
def test_negotiation_disables_explicitly_unsupported_features():
    """模型明确说不支持的能力要被关掉。"""

    class Model:
        vision = True
        supports_tool_calls = True
        supports_parallel_tool_calls = False
        max_output_tokens = 8192

    requested = CapabilitySet(tool_calls=True, parallel_tool_calls=True,
                              vision=True, max_output_tokens=32768)
    caps = CapabilitySet.negotiate(Model(), requested)
    assert caps.parallel_tool_calls is False
    assert caps.vision is True
    assert caps.max_output_tokens == 8192


def test_negotiation_keeps_request_when_model_declares_nothing():
    """模型没声明能力时不做收敛 —— 否则所有真实模型都会「不可用」。"""
    requested = CapabilitySet(tool_calls=True, parallel_tool_calls=True)
    caps = CapabilitySet.negotiate(object(), requested)
    assert caps.to_dict() == requested.to_dict()


def test_negotiation_accepts_a_capability_set_directly():
    model_caps = CapabilitySet(tool_calls=True, vision=False)
    caps = CapabilitySet.negotiate(model_caps, CapabilitySet(vision=True))
    assert caps.vision is False
    assert caps.tool_calls is True


def test_negotiation_reads_a_capabilities_dict():
    class Model:
        capabilities = {'vision': True, 'supports_tool_calls': False}

    # 请求里要什么 + 模型支持什么 = 实际能用什么。
    # 这里请求要 vision，模型也支持 vision → 保留；
    # 模型明确不支持 tool_calls → 关掉。
    requested = CapabilitySet(tool_calls=True, vision=True)
    caps = CapabilitySet.negotiate(Model(), requested)
    assert caps.vision is True
    assert caps.tool_calls is False


def test_negotiation_never_grants_what_was_not_requested():
    """模型支持 ≠ 应用要用。请求里没有的能力不能被「协商」出来。"""
    class Model:
        capabilities = {'vision': True}

    caps = CapabilitySet.negotiate(Model(), CapabilitySet(tool_calls=True))
    assert caps.vision is False


def test_intersect_keeps_the_more_conservative_side():
    a = CapabilitySet(max_output_tokens=1000, context_window=8000)
    b = CapabilitySet(max_output_tokens=4000, context_window=2000)
    merged = a.intersect(b)
    assert merged.max_output_tokens == 1000
    assert merged.context_window == 2000


# ── 运行 ────────────────────────────────────────────────
def test_react_kernel_runs_a_turn():
    client = FakeClient(reply='你好')
    kernel = ReactKernel(client=client)
    ctx = KernelContext(model=client, input=[])
    result = asyncio.run(kernel.run(ctx))
    assert isinstance(result, KernelResult)
    assert result.status == 'done'
    assert result.text == '你好'
    assert len(client.calls) == 1


def test_react_kernel_negotiates_into_the_context():
    class Model:
        vision = False
        supports_parallel_tool_calls = False

    client = FakeClient()
    client.vision = False
    client.supports_parallel_tool_calls = False
    kernel = ReactKernel(client=client)
    ctx = KernelContext(model=client,
                         caps=CapabilitySet(parallel_tool_calls=True))
    asyncio.run(kernel.run(ctx))
    assert ctx.caps.parallel_tool_calls is False


def test_react_kernel_reports_failure_instead_of_raising():
    class Boom:
        async def invoke(self, messages, tools=None, **kwargs):
            raise RuntimeError('模型炸了')

    kernel = ReactKernel(client=Boom())
    result = asyncio.run(kernel.run(KernelContext(model=Boom())))
    assert result.status == 'failed'
    assert '模型炸了' in result.stop_reason


def test_react_kernel_emits_run_finished():
    client = FakeClient()
    collector = Collector()
    kernel = ReactKernel(client=client)
    ctx = KernelContext(model=client, telemetry=collector, session_id='s1',
                         turn_id='t1')
    asyncio.run(kernel.run(ctx))
    assert 'run_finished' in collector.kinds()


def test_react_kernel_uses_the_context_tools():
    """内核用的是 ctx 里的工具表，而不是构造时绑死的那一份。"""
    registry = ToolRegistry()
    registry.register(Tool(name='noop', description='d', handler=lambda: 'x'))
    client = FakeClient()
    kernel = ReactKernel(client=client)
    ctx = KernelContext(model=client, tools=registry)
    asyncio.run(kernel.run(ctx))
    # 工具 schema 应该被下发给模型（这里模型是假��，只验证没报错）
    assert client.calls


def test_kernel_result_helpers():
    done = KernelResult(status='done', text='x')
    assert done.done is True
    assert done.awaiting_approval is False
    assert str(done) == 'x'
    waiting = KernelResult(status='awaiting_approval')
    assert waiting.awaiting_approval is True
