# harness/kernel/base.py
# 执行内核 SPI —— 「一次对话怎么跑」的可替换抽象。
#
# 动机（策划案 §4.1.1）：现在「怎么跑」硬编码在 harness/agent/loop.py 里。
# Multi-Agent 是 loop 里的一个特殊分支，Workflow 根本没法复用同样的模型、
# 上下文、工具、审批、遥测设施。把执行架构抽成协议之后，
# 「换一个执行架构」就只是换一个类 —— 业务代码不动。
#
# 依赖约束：内核只依赖 **IChatClient + ToolRegistry + ToolCallAdapter**
# 以及若干端口协议（approval / telemetry / runtime / memory）。
# 它不知道状态存在 sqlite 还是 postgres，也不知道工具有没有沙箱。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from .capability import CapabilitySet

#: 内核运行结果的状态
#:
#: done               正常结束（有最终答复）
#: interrupted        被中断
#: awaiting_approval  挂起等待人工审批（可恢复）
#: failed             失败
KernelStatus = Literal['done', 'interrupted', 'awaiting_approval', 'failed']


@dataclass
class KernelContext:
    """一次内核执行的输入。

    这里只放**端口**，不放实现：memory 是 MemoryStorePort、approval 是
    ApprovalBroker、telemetry 是 TelemetryPort、runtime 是 RuntimeClient。
    真正的实现由装配层注入（infra/）。
    """

    session_id: str = ''
    turn_id: str = ''
    input: list[Any] = field(default_factory=list)
    tools: Any = None                       # ToolRegistry
    context: Any = None                     # 上下文装配策略（可替换）
    memory: Any = None                      # MemoryStorePort
    approval: Any = None                    # ApprovalBroker
    telemetry: Any = None                   # TelemetryPort
    runtime: Any = None                     # RuntimeClient
    model: Any = None                       # IChatClient
    caps: CapabilitySet = field(default_factory=CapabilitySet)
    system_prompt: str = ''
    max_steps: int = 8
    metadata: dict = field(default_factory=dict)


@dataclass
class KernelResult:
    """一次内核执行的结果。"""

    status: KernelStatus = 'done'
    output: list[Any] = field(default_factory=list)
    usage: Any = None
    stop_reason: str = ''
    text: str = ''
    executions: list[Any] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def done(self) -> bool:
        return self.status == 'done'

    @property
    def awaiting_approval(self) -> bool:
        return self.status == 'awaiting_approval'

    def __str__(self) -> str:
        return self.text


@dataclass(frozen=True)
class KernelSpec:
    """内核的自我描述 —— 供能力协商与控制面使用。"""

    name: str
    version: str = '1.0'
    description: str = ''
    capabilities: CapabilitySet = field(default_factory=CapabilitySet)
    requires_approval: bool = False
    supports_parallel_tools: bool = False
    resumable: bool = False


@runtime_checkable
class ExecutionKernel(Protocol):
    """执行内核协议。

    实现：ReactKernel（rc0）、WorkflowKernel / PlannerKernel（rc1）。
    """

    name: str

    async def run(self, ctx: KernelContext) -> KernelResult: ...

    def describe(self) -> KernelSpec: ...


__all__ = [
    'CapabilitySet',
    'ExecutionKernel',
    'KernelContext',
    'KernelResult',
    'KernelSpec',
    'KernelStatus',
]
