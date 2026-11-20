# harness/kernel/planner.py
# Planner-Executor 执行内核（策划案 §4.1.3 / rc1 C1）。
#
# ── 语义 ──
# 先产出**结构化计划**（工具步骤列表），再由 Executor 按步执行；
# 步骤失败时可**重新规划**（带失败上下文，次数有上限），
# 已完成的步骤声明了补偿动作时**回退**。
#
# ── 计划是结构化的，不是自然语言 ──
# 「计划」如果是模型自由发挥的一段话，Executor 就只能靠另一个模型去猜，
# 猜错无法归因。所以计划必须是可校验的 JSON：
#   {"steps": [{"id", "tool", "args", "reason"?}, ...]}
# 解析失败先重试一次（模型输出偶尔带围栏），再失败就按 failed 结束 ——
# 绝不把「计划解析失败」静默降级成 ReAct（那是另一种执行架构的事，
# 混在一起会让评测无法归因到底是哪个架构的失败）。
#
# ── 与 React 的关系 ──
# 工具调用仍然只走 ToolRegistry.execute_async()（§3.2 规则 5）：
# 策略 / 审批 / 幂等 / 沙箱 / 审计对 Planner 与 React 一视同仁。

from __future__ import annotations

import inspect
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from .base import KernelContext, KernelResult, KernelSpec
from .capability import CapabilitySet

logger = logging.getLogger("harness.kernel.planner")

#: 计划的提示词 —— 刻意短：给模型越少的话，输出形状越稳。
PLAN_SYSTEM = (
    '你是执行规划器。根据用户目标产出一个 JSON 计划，不要输出其它文字。\n'
    '形状：{"steps": [{"id": "s1", "tool": "工具名", "args": {}, "reason": "为什么"}]}\n'
    '规则：'
    '只使用已提供的工具；'
    '步骤按执行顺序排列；'
    '后续步骤的参数可以引用前面步骤的输出，写作 "{上一步id}"。'
)

#: 执行器在每一步看到的提示（模型节点才需要；工具节点不需要）
_STEP_SYSTEM = (
    '你负责执行当前步骤。只做这一步，不要做计划之外的其它事。'
)

_JSON_BLOCK = re.compile(r'```(?:json)?\s*(.*?)```', re.DOTALL)


class PlanError(ValueError):
    """模型没有产出可解析的计划。"""


@dataclass
class PlanStep:
    """计划里的一步。"""

    id: str
    tool: str
    args: dict = field(default_factory=dict)
    reason: str = ''
    #: 失败补偿：撤销这一步副作用的工具名 + 参数模板
    compensate: str = ''
    compensate_args: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'tool': self.tool,
            'args': self.args,
            'reason': self.reason,
            'compensate': self.compensate,
            'compensate_args': self.compensate_args,
        }


@dataclass
class Plan:
    """一份结构化计划。"""

    steps: list[PlanStep] = field(default_factory=list)
    raw: str = ''
    replan_of: str = ''          # 若是重新规划，引用上一份计划的 id
    replan_reason: str = ''

    def to_dict(self) -> dict:
        return {
            'steps': [s.to_dict() for s in self.steps],
            'replan_of': self.replan_of,
            'replan_reason': self.replan_reason,
        }


def parse_plan(text: str) -> Plan:
    """把模型输出解析成 Plan。只接受 JSON —— 这是与模型的硬契约。"""
    if not text:
        raise PlanError('计划为空')
    candidate = text.strip()
    # 模型偶尔把 JSON 包进代码围栏；剥掉围栏再试，仍然只接受 JSON。
    fenced = _JSON_BLOCK.search(candidate)
    if fenced:
        candidate = fenced.group(1).strip()
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as error:
        raise PlanError(f'计划不是合法 JSON: {error}') from error
    if not isinstance(data, dict) or not isinstance(data.get('steps'), list):
        raise PlanError('计划必须是 {"steps": [...]} 的形状')
    steps: list[PlanStep] = []
    for i, item in enumerate(data['steps']):
        if not isinstance(item, dict) or not str(item.get('tool') or '').strip():
            raise PlanError(f'第 {i} 步缺少 tool 字段')
        steps.append(PlanStep(
            id=str(item.get('id') or f's{i + 1}'),
            tool=str(item['tool']),
            args=dict(item.get('args') or {}),
            reason=str(item.get('reason') or ''),
            compensate=str(item.get('compensate') or ''),
            compensate_args=dict(item.get('compensate_args') or {}),
        ))
    return Plan(steps=steps, raw=text)


class PlannerKernel:
    """Planner-Executor 执行内核。"""

    name = 'planner'

    def __init__(self, *, version: str = '1.0',
                 max_replans: int = 1,
                 plan_temperature: float | None = 0.2):
        self.version = version
        self.max_replans = max_replans
        self.plan_temperature = plan_temperature

    # ── 协议实现 ──────────────────────────────────────────
    def describe(self) -> KernelSpec:
        return KernelSpec(
            name=self.name,
            version=self.version,
            description='Planner-Executor：结构化计划 → 按步执行 → 可重规划/回退',
            capabilities=CapabilitySet(),
            requires_approval=True,
            supports_parallel_tools=False,
            resumable=True,
        )

    async def run(self, ctx: KernelContext) -> KernelResult:
        model = ctx.model
        tools = ctx.tools
        telemetry = ctx.telemetry

        caps = CapabilitySet.negotiate(model, ctx.caps)
        ctx.caps = caps

        if model is None:
            return KernelResult(status='failed', stop_reason='no_model',
                                text='Planner 内核需要模型客户端')

        user_goal = self._goal_text(ctx)
        if telemetry is not None:
            telemetry.emit('run_started', {'run_id': ctx.turn_id,
                                           'session_id': ctx.session_id})

        replans_left = int(ctx.metadata.get('max_replans', self.max_replans))
        completed: list[tuple[PlanStep, str]] = []

        def results() -> dict:
            return {s.id: t for s, t in completed}
        try:
            plan = await self._ask_plan(model, ctx, user_goal, failures=None)
            if telemetry is not None:
                telemetry.emit('agent_event', {
                    'agent': 'planner', 'status': 'plan',
                    'content': json.dumps(
                        [s.tool for s in plan.steps], ensure_ascii=False)})
        except PlanError as error:
            return self._failed(ctx, telemetry, f'plan_parse_failed:{error}',
                                completed)

        # ── Executor：按步执行 ─────────────────────────────
        index = 0
        while index < len(plan.steps):
            step = plan.steps[index]
            rendered = _render_args(step.args, results())
            try:
                if tools is None:
                    raise RuntimeError('没有工具注册表')
                result = await tools.execute_async(step.tool, rendered)
                if not result.success:
                    raise RuntimeError(
                        f'工具 {step.tool} 失败: {result.error or result.output}')
                text = ''
                from ..tools.registry import tool_result_text
                text = tool_result_text(result.output)
                completed.append((step, text))
                if telemetry is not None:
                    telemetry.emit('agent_event', {
                        'agent': f'planner:{step.id}', 'status': 'done',
                        'content': text[:400]})
                index += 1
            except Exception as error:  # noqa: BLE001
                logger.warning('步骤 %s (%s) 失败: %s', step.id, step.tool,
                               error)
                if replans_left <= 0:
                    await self._compensate(completed, tools)
                    return self._failed(
                        ctx, telemetry,
                        f'step_failed:{step.id}:{error}', completed)
                replans_left -= 1
                try:
                    plan = await self._ask_plan(
                        model, ctx, user_goal,
                        failures=[(step, str(error))],
                        previous=plan)
                except PlanError as plan_error:
                    await self._compensate(completed, tools)
                    return self._failed(
                        ctx, telemetry,
                        f'replan_failed:{plan_error}', completed)
                index = 0
                # 重新规划后从头执行：重规划产出的计划覆盖剩余目标。
                # 已完成的步骤不重跑 —— 除非新计划显式包含同名步骤
                # （那是规划器明确的决定，不是框架擅自重放）。
                plan_step_ids = {s.id for s in plan.steps}
                completed = [pair for pair in completed
                             if pair[0].id in plan_step_ids]

        final = await self._summarize(model, ctx, plan, completed)
        if telemetry is not None:
            telemetry.emit('run_finished', {'run_id': ctx.turn_id,
                                            'session_id': ctx.session_id,
                                            'status': 'done', 'usage': {}})
        return KernelResult(
            status='done',
            output=list(ctx.input),
            stop_reason='',
            text=final,
            metadata={
                'plan': plan.to_dict(),
                'steps_done': [s.id for s, _ in completed],
                'step_results': {s.id: t for s, t in completed},
                'caps': caps.to_dict(),
            },
        )

    # ── 内部 ──────────────────────────────────────────────
    async def _ask_plan(self, model: Any, ctx: KernelContext, goal: str, *,
                  failures: list[tuple[PlanStep, str]] | None,
                  previous: Plan | None = None) -> Plan:
        """向模型要一份计划。解析失败重试一次（围栏剥离已在 parse 内）。"""
        tools = ctx.tools
        tool_lines = ''
        if tools is not None:
            names = [t.name for t in tools.tools()]
            tool_lines = ('可用工具（只允许用这些）: '
                          + ', '.join(sorted(names)))
        prompt = f'目标：{goal}\n{tool_lines}'
        if failures:
            failed_step, error = failures[0]
            prompt += (f'\n\n上一次执行在第 {failed_step.id} 步'
                       f'（工具 {failed_step.tool}）失败：{error}\n'
                       '请重新给出覆盖剩余目标的计划。')
        messages: list[dict] = [{'role': 'system', 'content': PLAN_SYSTEM},
                                {'role': 'user', 'content': prompt}]
        response = await _call_model(model, messages,
                                     temperature=self.plan_temperature)
        content = str(getattr(response, 'content', '') or '')
        plan = parse_plan(content)
        if previous is not None:
            plan.replan_of = f'plan_{id(previous) & 0xffffffff:x}'
            plan.replan_reason = failures[0][1] if failures else ''
        return plan

    def _goal_text(self, ctx: KernelContext) -> str:
        parts = []
        for item in ctx.input:
            if isinstance(item, dict):
                parts.append(str(item.get('content') or ''))
            else:
                parts.append(str(getattr(item, 'content', item) or ''))
        return '\n'.join(p for p in parts if p).strip()

    def _messages(self, ctx: KernelContext, system: str,
                  user: str) -> list[dict]:
        messages = [{'role': 'system', 'content': system}]
        if user:
            messages.append({'role': 'user', 'content': user})
        return messages

    async def _summarize(self, model: Any, ctx: KernelContext, plan: Plan,
                   completed: list[tuple[PlanStep, str]]) -> str:
        """收束：把每步的产出拼给模型要一段最终答复。

        模型失败不阻断 —— 收束只是呈现层，步骤结果本身就是事实。
        """
        transcript = '\n'.join(
            f'[{s.id}] {s.tool} → {t[:800]}' for s, t in completed)
        prompt = (f'目标：{self._goal_text(ctx)}\n\n执行记录：\n{transcript}\n\n'
                  '请给用户一段最终答复。')
        try:
            response = await _call_model(
                model, self._messages(ctx, _STEP_SYSTEM, prompt))
            return str(getattr(response, 'content', '') or '')
        except Exception as error:  # noqa: BLE001
            logger.warning('收束失败，直接返回步骤结果: %s', error)
            return transcript

    async def _compensate(self, completed: list[tuple[PlanStep, str]],
                          tools: Any) -> list[str]:
        """逆序执行已完成步骤声明的补偿动作。

        补偿失败**不抛** —— 补偿是尽力而为的回滚，失败记进返回值，
        让上层与审计看到「哪一步没能撤销」。
        """
        errors: list[str] = []
        for step, _ in reversed(completed):
            if not step.compensate or tools is None:
                continue
            try:
                result = await tools.execute_async(
                    step.compensate,
                    _render_args(step.compensate_args, {s.id: t for s, t in completed}))
                if not result.success:
                    errors.append(
                        f'{step.id}: 补偿工具 {step.compensate} 失败: '
                        f'{result.error or result.output}')
            except Exception as error:  # noqa: BLE001
                errors.append(f'{step.id}: {error}')
        return errors

    def _failed(self, ctx: KernelContext, telemetry: Any, reason: str,
                completed: list[tuple[PlanStep, str]]) -> KernelResult:
        if telemetry is not None:
            telemetry.emit('run_failed', {'run_id': ctx.turn_id,
                                          'session_id': ctx.session_id,
                                          'error': reason})
        return KernelResult(
            status='failed', stop_reason=reason,
            text=reason,
            metadata={'steps_done': [s.id for s, _ in completed],
                      'step_results': {s.id: t for s, t in completed}})


async def _call_model(model: Any, messages: list[dict], **kwargs: Any) -> Any:
    """调用模型；同步/异步 invoke 都吃（测试里的假模型两种都有）。"""
    result = model.invoke(messages, **kwargs)
    if inspect.isawaitable(result):
        result = await result
    return result


def _render_args(template: dict, results: dict[str, str]) -> dict:
    """把模板里的 ``{step_id}`` 替换成已完成步骤的输出。"""
    rendered: dict = {}
    for key, value in template.items():
        if isinstance(value, str):
            rendered[key] = value.format_map(_StepDict(results))
        else:
            rendered[key] = value
    return rendered


class _StepDict(dict):
    def __missing__(self, key: str) -> str:
        raise KeyError(f'{key}（可用: {sorted(self)}）')


__all__ = [
    'Plan',
    'PlanError',
    'PlanStep',
    'PlannerKernel',
    'parse_plan',
]
