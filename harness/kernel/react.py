# harness/kernel/react.py
# ReAct 执行内核 —— 循环：模型 → 工具 → 上下文 → 模型。
#
# 这个内核是 harness/agent/loop.py 的**收敛形态**，但不是重写：
# 它把 AgentLoop 包起来，因此现有行为（工具适配、步数上限、收束轮、
# 流式事件）完全不变，同时多出内核协议需要的东西：
#   - 能力协商（执行前收敛请求）
#   - 审批挂起语义（awaiting_approval）
#   - 统一的 KernelResult
#
# 为什么要包一层而不是把 loop.py 改名：
# loop.py 是被大量代码 import 的公共路径（SDK、engine、apps），
# 原地改名等于一次大范围破坏性变更。包一层让新旧路径共存，
# 老路径继续工作，新路径多一层抽象 —— 这是「不破坏现有用户」的做法。

from __future__ import annotations

import logging
from typing import Any, Optional

from ..agent.loop import AgentLoop
from ..runtime_client import NullRuntimeClient
from .base import KernelContext, KernelResult, KernelSpec
from .capability import CapabilitySet

logger = logging.getLogger("harness.kernel")


class ReactKernel:
    """ReAct 内核。"""

    name = 'react'

    def __init__(self, *, client: Any = None, tools: Any = None,
                 adapter: Any = None, max_steps: int = 8,
                 max_output_chars: int = 6000,
                 max_seconds: Optional[float] = None,
                 on_progress: Any = None, on_tool_error: Any = None,
                 toolbox: Any = None, on_usage: Any = None,
                 deps: Any = None, version: str = '1.0'):
        self.client = client
        self.tools = tools
        self.adapter = adapter
        self.max_steps = max_steps
        self.max_output_chars = max_output_chars
        self.max_seconds = max_seconds
        self.on_progress = on_progress
        self.on_tool_error = on_tool_error
        self.toolbox = toolbox
        self.on_usage = on_usage
        self.deps = deps
        self.version = version

    # ── 协议实现 ──────────────────────────────────────────
    def describe(self) -> KernelSpec:
        return KernelSpec(
            name=self.name,
            version=self.version,
            description='ReAct：模型 → 工具 → 上下文 → 模型',
            capabilities=CapabilitySet(),
            requires_approval=True,
            supports_parallel_tools=False,
            resumable=True,
        )

    async def run(self, ctx: KernelContext) -> KernelResult:
        """执行一次。"""
        model = ctx.model or self.client
        tools = ctx.tools if ctx.tools is not None else self.tools
        runtime = ctx.runtime or NullRuntimeClient()

        # 能力协商：执行前收敛一次，结果放进 ctx.caps 供下游决策
        caps = CapabilitySet.negotiate(model, ctx.caps)
        ctx.caps = caps

        loop = AgentLoop(
            client=model,
            tools=tools,
            adapter=self.adapter,
            max_steps=ctx.max_steps or self.max_steps,
            max_output_chars=self.max_output_chars,
            max_seconds=self.max_seconds,
            on_progress=self.on_progress,
            on_tool_error=self.on_tool_error,
            toolbox=self.toolbox,
            on_usage=self.on_usage,
            deps=ctx.metadata.get('deps', self.deps),
        )

        # 运行时的事件出口：内核产生的每一步都落 journal
        if ctx.telemetry is not None:
            self._wire_telemetry(loop, ctx)

        try:
            result = await loop.run_async(list(ctx.input),
                                          system_prompt=ctx.system_prompt)
        except Exception as error:  # noqa: BLE001
            logger.exception('ReAct 内核执行失败')
            return KernelResult(status='failed', stop_reason=str(error),
                                 text=str(error))

        status = 'done'
        stop_reason = ''
        if result.hit_max_steps:
            status = 'done'
            stop_reason = 'max_steps'
        text = result.text or ''
        if ctx.telemetry is not None:
            ctx.telemetry.emit('run_finished', {
                'run_id': ctx.turn_id,
                'session_id': ctx.session_id,
                'status': status,
                'usage': {},
            })
        return KernelResult(
            status=status,
            output=list(ctx.input),
            usage=None,
            stop_reason=stop_reason,
            text=text,
            executions=list(result.tool_executions),
            metadata={'steps': result.steps, 'caps': caps.to_dict()},
        )

    # ── 内部 ──────────────────────────────────────────────
    def _wire_telemetry(self, loop: AgentLoop, ctx: KernelContext) -> None:
        """把内核事件接到遥测口。

        注意：loop 自己的 on_progress / on_usage 回调是**已有的**扩展点，
        我们包一层而不是替换，避免把应用层已经挂的回调弄丢。
        """
        original_usage = loop.on_usage
        telemetry = ctx.telemetry

        def on_usage(payload: dict) -> None:
            telemetry.emit('usage', dict(payload or {}))
            if original_usage is not None:
                original_usage(payload)

        loop.on_usage = on_usage

        original_error = loop.on_tool_error
        tool_names = getattr(ctx, 'tool_names', None)

        def on_tool_error(name: str, error: str) -> None:
            telemetry.emit('tool_blocked', {'tool': name, 'reason': 'error',
                                           'effect': '', 'risk': ''})
            if original_error is not None:
                original_error(name, error)

        loop.on_tool_error = on_tool_error


__all__ = ['ReactKernel']
