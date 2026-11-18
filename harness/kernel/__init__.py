# harness/kernel —— 执行内核 SPI。
#
# 四种执行架构共享同一套能力（模型、上下文、记忆、工具、审批、遥测）：
#   react     ReAct 循环（rc0）
#   workflow  DAG（rc1）
#   planner   Planner-Executor（rc1）
#   multi     复用 harness/agent/collab.py + swarm.py（rc0 只做协议统一）
#
# 依赖规则：内核只依赖端口协议，不依赖任何 infra 实现。

from .base import (
    CapabilitySet,
    ExecutionKernel,
    KernelContext,
    KernelResult,
    KernelSpec,
    KernelStatus,
)
from .capability import CapabilitySet as _CapabilitySet
from .react import ReactKernel

__all__ = [
    'ExecutionKernel',
    'KernelContext',
    'KernelResult',
    'KernelSpec',
    'KernelStatus',
    'CapabilitySet',
    'ReactKernel',
]
