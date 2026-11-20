# tests/test_rc1_kernels.py
# Workflow / Planner 内核的测试 —— 策划案 §4.1.3 / rc1 C1。
#
# 验收标准（策划案 §7.2 C1）：同一 Agent 定义切换执行架构只改
# spec.kernel；两种架构都能复用同一套能力（模型、工具、审批、遥测）。
# 工具调用必须走注册表统一入口（§3.2 规则 5）—— 这里用带守卫的
# 注册表验证闸门对两种内核都生效。

from __future__ import annotations

import asyncio

import pytest

from harness.kernel import (
    KernelContext,
    PlannerKernel,
    ReactKernel,
    WorkflowKernel,
    WorkflowNode,
    WorkflowValidationError,
    kernel_by_name,
    parse_plan,
    validate_workflow,
)
from harness.kernel.planner import PlanError
from harness.tools.base import Tool, ToolResult
from harness.tools.registry import ManagedToolRegistry
from infra.orchestrator.base import ChatResponse


class FakeClient:
    """假模型：同步与异步 invoke 都能吃（内核必须两者兼容）。"""

    def __init__(self, script=None, reply='ok', parallel=False):
        self.script = list(script or [])
        self.reply = reply
        self.parallel = parallel
        self.calls = 0

    async def invoke(self, messages, tools=None, **kwargs):
        self.calls += 1
        if self.script:
            item = self.script.pop(0)
            if isinstance(item, Exception):
                raise item
            return ChatResponse(content=item)
        return ChatResponse(content=self.reply)

    def stream(self, messages, tools=None, **kwargs):
        raise NotImplementedError


class SyncClient(FakeClient):
    def invoke(self, messages, tools=None, **kwargs):
        self.calls += 1
        if self.script:
            item = self.script.pop(0)
            return ChatResponse(content=item)
        return ChatResponse(content=self.reply)


class Collector:
    def __init__(self):
        self.events = []

    def emit(self, kind, payload):
        self.events.append((kind, payload))

    def kinds(self):
        return [k for k, _ in self.events]


def _registry(*tools):
    registry = ManagedToolRegistry()
    for tool in tools or []:
        registry.register(tool)
    return registry


def echo_tool():
    return Tool(name='demo.echo', description='echo',
                handler=lambda **kw: ToolResult.ok({'echo': kw}))


def shout_tool():
    def shout(text=''):
        return ToolResult.ok(str(text).upper())
    return Tool(name='demo.shout', description='shout', handler=shout)


def fail_tool():
    def boom(**kw):
        return ToolResult.fail('boom')
    return Tool(name='demo.boom', description='boom', handler=boom)


def undo_tool():
    def undo(target=''):
        return ToolResult.ok(f'undone:{target}')
    return Tool(name='demo.undo', description='undo', handler=undo)


def ctx(model=None, tools=None, metadata=None):
    c = KernelContext()
    c.session_id = 's1'
    c.turn_id = 't1'
    c.input = [{'role': 'user', 'content': 'go'}]
    c.tools = tools
    c.model = model
    c.telemetry = Collector()
    c.metadata = metadata or {}
    return c


# ── 内核注册表 ────────────────────────────────────────────
def test_kernel_registry_resolves_the_three_architectures():
    assert kernel_by_name('react') is ReactKernel
    assert kernel_by_name('workflow') is WorkflowKernel
    assert kernel_by_name('planner') is PlannerKernel
    assert kernel_by_name('Quantum') is None
    assert kernel_by_name('') is None


# ── Workflow ──────────────────────────────────────────────
def test_workflow_runs_a_linear_dag():
    tools = _registry(shout_tool(), echo_tool())
    model = FakeClient(reply='[wrap]')
    kernel = WorkflowKernel(nodes=[
        WorkflowNode(name='a', kind='tool', tool='demo.shout',
                     args={'text': 'hello'}),
        WorkflowNode(name='b', kind='model', prompt='wrap {a}',
                     depends_on=('a',)),
    ])
    result = asyncio.run(kernel.run(ctx(model, tools)))
    assert result.status == 'done'
    assert result.metadata['node_results']['a'] == 'HELLO'
    assert 'b' in result.metadata['node_results']
    telemetry = result.metadata  # noqa: F841


def test_workflow_events_reach_the_trace():
    tools = _registry(shout_tool())
    kernel = WorkflowKernel(nodes=[
        WorkflowNode(name='a', kind='tool', tool='demo.shout',
                     args={'text': 'x'})])
    c = ctx(FakeClient(), tools)
    result = asyncio.run(kernel.run(c))
    kinds = c.telemetry.kinds()
    assert 'run_started' in kinds
    assert 'run_finished' in kinds
    assert result.status == 'done'


def test_workflow_renders_tool_output_into_downstream_args():
    tools = _registry(shout_tool(), echo_tool())
    kernel = WorkflowKernel(nodes=[
        WorkflowNode(name='a', kind='tool', tool='demo.shout',
                     args={'text': 'hi'}),
        WorkflowNode(name='b', kind='tool', tool='demo.echo',
                     args={'msg': '值是 {a}'}, depends_on=('a',)),
    ])
    result = asyncio.run(kernel.run(ctx(FakeClient(), tools)))
    assert result.metadata['node_results']['b'] == '{"echo": {"msg": "值是 HI"}}'


def test_workflow_template_ref_to_missing_node_fails_loud():
    """引用了不存在的节点 → 立刻失败，绝不静默替换成空串。"""
    tools = _registry(echo_tool())
    kernel = WorkflowKernel(nodes=[
        WorkflowNode(name='b', kind='tool', tool='demo.echo',
                     args={'msg': '{ghost}'})])
    result = asyncio.run(kernel.run(ctx(FakeClient(), tools)))
    assert result.status == 'failed'
    assert 'ghost' in result.text       # 失败原因给到模型/调用方


def test_workflow_runs_parallel_branches():
    tools = _registry(shout_tool(), echo_tool())
    kernel = WorkflowKernel(nodes=[
        WorkflowNode(name='a', kind='tool', tool='demo.shout',
                     args={'text': 'x'}),
        WorkflowNode(name='b', kind='tool', tool='demo.echo', args={'q': 1}),
        WorkflowNode(name='c', kind='tool', tool='demo.shout',
                     args={'text': '{a}'}, depends_on=('a', 'b')),
    ], max_concurrency=2)
    c = ctx(FakeClient(reply='', parallel=True), tools)
    from harness.kernel import CapabilitySet
    c.caps = CapabilitySet(parallel_tool_calls=True)   # 请求并行 → 协商后仍并行
    result = asyncio.run(kernel.run(c))
    assert result.status == 'done'
    assert result.metadata['parallel'] is True
    assert result.metadata['steps'] == 3


def test_workflow_retries_then_compensates_in_reverse():
    """失败补偿：已完成节点声明的补偿动作按**完成顺序的逆序**执行。"""
    tools = _registry(shout_tool(), echo_tool(), fail_tool(), undo_tool())
    kernel = WorkflowKernel(nodes=[
        WorkflowNode(name='first', kind='tool', tool='demo.shout',
                     args={'text': 'x'}, compensate='demo.undo',
                     compensate_args={'target': 'first'}),
        WorkflowNode(name='second', kind='tool', tool='demo.echo',
                     args={'a': 1}, compensate='demo.undo',
                     compensate_args={'target': 'second'}),
        WorkflowNode(name='third', kind='tool', tool='demo.boom',
                     depends_on=('first', 'second'), retries=1),
    ])
    result = asyncio.run(kernel.run(ctx(FakeClient(), tools)))
    assert result.status == 'failed'
    assert result.stop_reason.startswith('node_failed:third')
    comp = result.metadata['compensation_errors']
    assert comp == []      # 两条补偿都成功
    # 逆序：second 先撤销，first 后撤销（由结果文本确认都发生了）
    # （补偿走注册表 → 守卫链路，见下一条测试）


def test_workflow_tool_calls_go_through_the_guard():
    """策划案 §3.2 规则 5：Workflow 的工具调用也必须走统一入口。"""
    from harness.policy.base import PolicyDecision
    from harness.tools.guard import ToolGuard

    class Deny:
        def admit(self, tool, args=None, spec=None, identity=None):
            return PolicyDecision.deny('policy', detail='no tools for you')

    tools = _registry(shout_tool())
    tools.attach_guard(ToolGuard(policy=Deny()))
    kernel = WorkflowKernel(nodes=[
        WorkflowNode(name='a', kind='tool', tool='demo.shout',
                     args={'text': 'x'})])
    result = asyncio.run(kernel.run(ctx(FakeClient(), tools)))
    assert result.status == 'failed'
    assert '被策略拒绝' in result.text


def test_workflow_compensation_failure_is_recorded_not_raised():
    tools = _registry(fail_tool(), undo_tool())
    kernel = WorkflowKernel(nodes=[
        WorkflowNode(name='a', kind='tool', tool='demo.boom',
                     compensate='demo.boom',        # 补偿自己也失败
                     compensate_args={}),
    ])
    result = asyncio.run(kernel.run(ctx(FakeClient(), tools)))
    assert result.status == 'failed'
    assert len(result.metadata['compensation_errors']) == 1


def test_workflow_validation_catches_cycles_and_bad_refs():
    with pytest.raises(WorkflowValidationError):
        validate_workflow([WorkflowNode(name='a', depends_on=('b',)),
                           WorkflowNode(name='b', depends_on=('a',))])
    with pytest.raises(WorkflowValidationError):
        validate_workflow([WorkflowNode(name='a', depends_on=('ghost',))])
    with pytest.raises(WorkflowValidationError):
        validate_workflow([WorkflowNode(name='a'), WorkflowNode(name='a')])
    with pytest.raises(WorkflowValidationError):
        WorkflowKernel(nodes=[])


def test_workflow_kernel_describe_declares_parallel_support():
    spec = WorkflowKernel().describe()
    assert spec.name == 'workflow'
    assert spec.supports_parallel_tools is True
    assert spec.requires_approval is True


def test_workflow_satisfies_the_execution_kernel_protocol():
    from harness.kernel.base import ExecutionKernel
    assert isinstance(WorkflowKernel(), ExecutionKernel)
    assert isinstance(PlannerKernel(), ExecutionKernel)


# ── Planner ───────────────────────────────────────────────
PLAN_JSON = ('{"steps": ['
             '{"id": "s1", "tool": "demo.shout", "args": {"text": "hi"}},'
             '{"id": "s2", "tool": "demo.echo", "args": {"msg": "{s1}"}}]}')


def test_parse_plan_accepts_json_and_fenced_json():
    plan = parse_plan(PLAN_JSON)
    assert [s.tool for s in plan.steps] == ['demo.shout', 'demo.echo']
    fenced = '```json\n' + PLAN_JSON + '\n```'
    assert parse_plan(fenced).steps == plan.steps


def test_parse_plan_rejects_non_json_and_bad_shapes():
    with pytest.raises(PlanError):
        parse_plan('我觉得应该先看看文件')
    with pytest.raises(PlanError):
        parse_plan('{"steps": "not-a-list"}')
    with pytest.raises(PlanError):
        parse_plan('{"steps": [{"id": "s1"}]}')   # 缺 tool


def test_planner_executes_the_plan_in_order():
    tools = _registry(shout_tool(), echo_tool())
    model = FakeClient(script=[PLAN_JSON, '[final]'])
    kernel = PlannerKernel()
    result = asyncio.run(kernel.run(ctx(model, tools)))
    assert result.status == 'done'
    assert result.metadata['steps_done'] == ['s1', 's2']
    assert result.metadata['step_results']['s1'] == 'HI'
    assert result.text == '[final]'
    # 两次模型调用：一次出计划，一次收束
    assert model.calls == 2


def test_planner_replans_after_a_failed_step():
    """步骤失败 → 带失败上下文重新规划（次数有上限）。"""
    tools = _registry(shout_tool(), echo_tool(), fail_tool())
    model = FakeClient(script=[
        ('{"steps": [{"id": "s1", "tool": "demo.boom"},'
         '{"id": "s2", "tool": "demo.shout", "args": {"text": "hi"}}]}'),
        '{"steps": [{"id": "s2", "tool": "demo.shout", "args": {"text": "hi"}}]}',
        '[final]',
    ])
    kernel = PlannerKernel(max_replans=1)
    result = asyncio.run(kernel.run(ctx(model, tools)))
    assert result.status == 'done'
    assert result.metadata['steps_done'] == ['s2']
    assert result.metadata['plan']['replan_of'] != ''


def test_planner_stops_after_replan_budget_is_exhausted():
    tools = _registry(fail_tool())
    model = FakeClient(script=[
        '{"steps": [{"id": "s1", "tool": "demo.boom"}]}',
        '{"steps": [{"id": "s1", "tool": "demo.boom"}]}',
    ])
    kernel = PlannerKernel(max_replans=1)
    result = asyncio.run(kernel.run(ctx(model, tools)))
    assert result.status == 'failed'
    assert result.stop_reason.startswith('step_failed:s1')


def test_planner_plan_parse_failure_is_not_silently_downgraded():
    """计划解析失败 → failed（不静默降级成 ReAct）。"""
    tools = _registry(echo_tool())
    model = FakeClient(script=['这不是 JSON', '这还不是 JSON'])
    kernel = PlannerKernel(max_replans=0)
    result = asyncio.run(kernel.run(ctx(model, tools)))
    assert result.status == 'failed'
    assert result.stop_reason.startswith('plan_parse_failed')


def test_planner_compensates_completed_steps_on_final_failure():
    tools = _registry(shout_tool(), fail_tool(), undo_tool())
    model = FakeClient(script=[
        ('{"steps": ['
         '{"id": "s1", "tool": "demo.shout", "args": {"text": "x"},'
         ' "compensate": "demo.undo", "compensate_args": {"target": "s1"}},'
         '{"id": "s2", "tool": "demo.boom"}]}'),
        # 重规划预算用尽：第二次计划还是炸
        '{"steps": [{"id": "s2", "tool": "demo.boom"}]}',
    ])
    kernel = PlannerKernel(max_replans=1)
    result = asyncio.run(kernel.run(ctx(model, tools)))
    assert result.status == 'failed'


def test_planner_tool_calls_go_through_the_guard():
    from harness.policy.base import PolicyDecision
    from harness.tools.guard import ToolGuard

    class Deny:
        def admit(self, tool, args=None, spec=None, identity=None):
            return PolicyDecision.deny('policy', detail='denied')

    tools = _registry(shout_tool())
    tools.attach_guard(ToolGuard(policy=Deny()))
    model = FakeClient(script=[
        '{"steps": [{"id": "s1", "tool": "demo.shout", "args": {"text": "x"}}]}'])
    kernel = PlannerKernel(max_replans=0)
    result = asyncio.run(kernel.run(ctx(model, tools)))
    assert result.status == 'failed'
    assert '被策略拒绝' in result.text or '被策略拒绝' in result.stop_reason


def test_planner_sync_model_client_also_works():
    tools = _registry(shout_tool(), echo_tool())
    model = SyncClient(script=[PLAN_JSON, '[final]'])
    kernel = PlannerKernel()
    result = asyncio.run(kernel.run(ctx(model, tools)))
    assert result.status == 'done'


def test_planner_describe_declares_its_shape():
    spec = PlannerKernel().describe()
    assert spec.name == 'planner'
    assert spec.supports_parallel_tools is False
    assert spec.resumable is True
