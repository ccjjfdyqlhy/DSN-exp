# harness/kernel —— 执行内核 SPI。
#
# 四种执行架构共享同一套能力（模型、上下文、记忆、工具、审批、遥测）：
#   react     ReAct 循环（rc0）
#   workflow  DAG（rc1）
#   planner   Planner-Executor（rc1）
#   multi     复用 harness/agent/collab.py + swarm.py（协议统一）
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
from .planner import Plan, PlanError, PlannerKernel, PlanStep, parse_plan
from .react import ReactKernel
from .workflow import (
    WorkflowKernel,
    WorkflowNode,
    WorkflowValidationError,
    validate_workflow,
    workflow_from_dict,
)

#: 内核名 → 内核类（spec.kernel 的解析表；artifact 控制面用）
KERNEL_REGISTRY: dict[str, type] = {
    'react': ReactKernel,
    'workflow': WorkflowKernel,
    'planner': PlannerKernel,
}


def kernel_by_name(name: str):
    """按名字取内核类；未知名字返回 None —— 调用方决定怎么报错。"""
    return KERNEL_REGISTRY.get(str(name or '').strip().lower())


__all__ = [
    'KERNEL_REGISTRY',
    'CapabilitySet',
    'ExecutionKernel',
    'KernelContext',
    'KernelResult',
    'KernelSpec',
    'KernelStatus',
    'Plan',
    'PlanError',
    'PlanStep',
    'PlannerKernel',
    'ReactKernel',
    'WorkflowKernel',
    'WorkflowNode',
    'WorkflowValidationError',
    'kernel_by_name',
    'parse_plan',
    'validate_workflow',
    'workflow_from_dict',
]
