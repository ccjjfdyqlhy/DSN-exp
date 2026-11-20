# harness/kernel/workflow.py
# Workflow 执行内核（策划案 §4.1.3 / rc1 C1）。
#
# ── 语义 ──
# DAG：节点是工具或模型调用，边是依赖；无依赖关系的分支**并行**执行；
# 失败的分支按节点声明的补偿动作**逆序回滚**。
#
# ── 与 React 内核的关系 ──
# 同一个 ExecutionKernel 协议（策划案 §7.2 C1：同一 Agent 定义切换执行架构
# 只改 spec.kernel）。Workflow 不自己定义工具调用路径 —— 它仍然走
# ToolRegistry.execute_async()，因此策略 / 审批 / 幂等 / 沙箱 / 审计
# 五道闸门原样生效。策划案 §3.2 依赖规则 5：任何工具调用路径必须经过
# registry 的统一入口，Workflow 不例外。
#
# ── 并行与能力协商 ──
# 是否并行由 CapabilitySet.negotiate() 的结果决定（§4.1.4）：模型不支持
# parallel_tool_calls 时退化为顺序执行 —— 降级而非降智，也不假装并行。

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from ..runtime_client import NullRuntimeClient
from .base import KernelContext, KernelResult, KernelSpec
from .capability import CapabilitySet

logger = logging.getLogger("harness.kernel.workflow")

#: 节点类型
NODE_TOOL = 'tool'
NODE_MODEL = 'model'


@dataclass
class WorkflowNode:
    """一个工作流节点。

    name         节点名（DAG 的唯一标识，模板引用用它）
    kind         'tool' | 'model'
    tool         kind=tool 时的工具名（必须已在注册表里）
    args         kind=tool 时的参数模板；值里的 ``{node}`` 会被替换成
                 该节点的输出文本
    prompt       kind=model 时发给模型的提示；``{node}`` 同样可引用
    depends_on   依赖的节点名列表（全部完成才开始）
    retries      失败重试次数（默认 0 —— 重试是显式声明，不是默认行为）
    compensate   失败补偿：补偿用的**工具名**（不是节点名 —— 补偿走的是
                 「撤销这次副作用」的工具，例如 shell.mkdir 的补偿是 shell.rmdir）
    compensate_args  补偿工具的参数模板
    """

    name: str
    kind: str = NODE_TOOL
    tool: str = ''
    args: dict = field(default_factory=dict)
    prompt: str = ''
    depends_on: tuple[str, ...] = ()
    retries: int = 0
    compensate: str = ''
    compensate_args: dict = field(default_factory=dict)

    def render(self, template: Any, outputs: dict[str, str]) -> Any:
        """把模板里的 ``{node}`` 引用替换成已完成节点的输出。

        只替换字符串里的引用；数字 / 布尔 / None 原样保留 ——
        参数的形状不该因为模板化而被破坏。
        """
        if isinstance(template, str):
            return template.format_map(_SafeDict(outputs))
        if isinstance(template, dict):
            return {k: self.render(v, outputs) for k, v in template.items()}
        if isinstance(template, (list, tuple)):
            return [self.render(v, outputs) for v in template]
        return template


class _SafeDict(dict):
    """模板渲染时未完成节点的引用直接报 KeyError —— 静默替换成空串
    会让「引用了不存在的节点」这种声明错误永远不被发现。"""

    def __missing__(self, key: str) -> str:
        raise KeyError(key)


class WorkflowValidationError(ValueError):
    """工作流声明不合法（环 / 引用不存在的节点 / 空 DAG）。"""


def validate_workflow(nodes: list[WorkflowNode]) -> None:
    """静态校验：非空、名字唯一、依赖存在、无环。

    在 run() 之前做 —— 「跑到第三步才发现环」是最贵的失败方式。
    """
    if not nodes:
        raise WorkflowValidationError('工作流不能为空')
    names = [n.name for n in nodes]
    if len(names) != len(set(names)):
        dupes = sorted({n for n in names if names.count(n) > 1})
        raise WorkflowValidationError(f'节点名重复: {dupes}')
    name_set = set(names)
    for node in nodes:
        for dep in node.depends_on:
            if dep not in name_set:
                raise WorkflowValidationError(
                    f'节点 {node.name} 依赖了不存在的节点 {dep!r}')
    # Kahn 环检测
    indegree = {n.name: 0 for n in nodes}
    dependents: dict[str, list[str]] = {}
    for node in nodes:
        for dep in node.depends_on:
            indegree[node.name] += 1
            dependents.setdefault(dep, []).append(node.name)
    ready = [n for n, d in indegree.items() if d == 0]
    seen = 0
    while ready:
        current = ready.pop()
        seen += 1
        for nxt in dependents.get(current, ()):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
    if seen != len(nodes):
        stuck = sorted(n for n, d in indegree.items() if d > 0)
        raise WorkflowValidationError(f'工作流存在环: {stuck}')


class WorkflowKernel:
    """Workflow 执行内核：DAG + 并行分支 + 失败补偿。"""

    name = 'workflow'

    def __init__(self, *, nodes: list[WorkflowNode] | None = None,
                 workflow: list[WorkflowNode] | None = None,
                 version: str = '1.0',
                 max_concurrency: int = 4):
        nodes = workflow if workflow is not None else nodes
        if nodes is not None:
            validate_workflow(nodes)
        self.nodes = list(nodes or [])
        self.version = version
        # 并发上限是自我保护：无上限的 gather 会把 50 个分支同时压向
        # 模型端点（§4.2.5 资源隔离的内核侧呼应）。
        self.max_concurrency = max(1, int(max_concurrency))

    # ── 协议实现 ──────────────────────────────────────────
    def describe(self) -> KernelSpec:
        return KernelSpec(
            name=self.name,
            version=self.version,
            description='Workflow：DAG 节点（工具/模型）+ 并行分支 + 失败补偿',
            capabilities=CapabilitySet(parallel_tool_calls=True),
            requires_approval=True,
            supports_parallel_tools=True,
            resumable=True,
        )

    async def run(self, ctx: KernelContext) -> KernelResult:
        model = ctx.model
        tools = ctx.tools
        runtime = ctx.runtime or NullRuntimeClient()
        telemetry = ctx.telemetry
        started = time.monotonic()

        caps = CapabilitySet.negotiate(model, ctx.caps)
        ctx.caps = caps

        nodes = self.nodes
        if not nodes and ctx.metadata.get('workflow_nodes'):
            nodes = [WorkflowNode(**spec) for spec in ctx.metadata['workflow_nodes']]
        if not nodes:
            return KernelResult(status='failed', stop_reason='empty_workflow',
                                text='工作流没有节点')
        if ctx.metadata.get('validate', True):
            validate_workflow(nodes)

        outputs: dict[str, str] = {}
        completed: list[WorkflowNode] = []
        parallel = bool(caps.parallel_tool_calls) or \
            bool(ctx.metadata.get('force_parallel', False))

        if telemetry is not None:
            telemetry.emit('run_started', {'run_id': ctx.turn_id,
                                           'session_id': ctx.session_id})
        try:
            await self._run_dag(nodes, ctx, model, tools, runtime, telemetry,
                                outputs, completed, parallel)
        except _WorkflowFailure as failure:
            # 失败补偿：把已完成节点声明的补偿动作**逆序**执行。
            compensation_errors = await self._compensate(completed, ctx, tools)
            error_text = str(failure)
            if telemetry is not None:
                telemetry.emit('run_failed', {
                    'run_id': ctx.turn_id, 'session_id': ctx.session_id,
                    'error': error_text})
            return KernelResult(
                status='failed',
                stop_reason=f'node_failed:{failure.node}',
                text=error_text,
                metadata={
                    'node_results': outputs,
                    'compensation_errors': compensation_errors,
                    'caps': caps.to_dict(),
                })
        except Exception as error:
            logger.exception('Workflow 内核执行失败')
            await self._compensate(completed, ctx, tools)
            return KernelResult(status='failed', stop_reason=str(error),
                                text=str(error),
                                metadata={'node_results': outputs})

        final_text = self._final_text(nodes, outputs, ctx)
        if telemetry is not None:
            telemetry.emit('run_finished', {
                'run_id': ctx.turn_id, 'session_id': ctx.session_id,
                'status': 'done', 'usage': {}})
        return KernelResult(
            status='done',
            output=list(ctx.input),
            stop_reason='',
            text=final_text,
            metadata={
                'node_results': outputs,
                'steps': len(completed),
                'parallel': parallel,
                'caps': caps.to_dict(),
                'duration_ms': (time.monotonic() - started) * 1000,
            },
        )

    # ── DAG 执行 ──────────────────────────────────────────
    async def _run_dag(self, nodes: list[WorkflowNode], ctx: KernelContext,
                       model: Any, tools: Any, runtime: Any,
                       telemetry: Any, outputs: dict[str, str],
                       completed: list[WorkflowNode], parallel: bool) -> None:
        pending = {n.name: n for n in nodes}
        running: dict[str, asyncio.Task] = {}
        sem = asyncio.Semaphore(self.max_concurrency)

        async def guarded_run(node: WorkflowNode) -> None:
            async with sem:
                await self._run_node(node, ctx, model, tools, telemetry,
                                     outputs)

        while pending or running:
            # 就绪 = 依赖全部完成
            ready = [n for n in pending.values()
                     if all(d in outputs for d in n.depends_on)]
            if not ready and not running:
                stuck = sorted(pending)
                raise _WorkflowFailure(
                    stuck[0], f'依赖无法满足，节点 {stuck} 永远不会就绪')
            for node in ready:
                del pending[node.name]
                if parallel and len(ready) > 1:
                    task = asyncio.ensure_future(guarded_run(node))
                else:
                    task = asyncio.ensure_future(self._run_node(
                        node, ctx, model, tools, telemetry, outputs))
                running[node.name] = task
            if running:
                done, _ = await asyncio.wait(
                    running.values(),
                    return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    node = next(n for n, t in running.items() if t is task)
                    del running[node]
                    completed.append(
                        next(n for n in nodes if n.name == node))
                    # 任务里的异常在这里显式取出来 —— 吞掉 await 的异常
                    # 会让失败被记成成功。
                    task.result()

    async def _run_node(self, node: WorkflowNode, ctx: KernelContext,
                        model: Any, tools: Any, telemetry: Any,
                        outputs: dict[str, str]) -> None:
        """执行一个节点（含 retries）；失败抛 _WorkflowFailure。"""
        last_error = ''
        attempts = max(1, node.retries + 1)
        for attempt in range(attempts):
            try:
                if node.kind == NODE_TOOL:
                    result = await self._run_tool_node(node, ctx, tools,
                                                       outputs)
                else:
                    result = await self._run_model_node(node, ctx, model,
                                                        outputs)
                outputs[node.name] = result
                if telemetry is not None:
                    telemetry.emit('agent_event', {
                        'agent': f'workflow:{node.name}',
                        'status': 'done',
                        'content': result[:400],
                    })
                return
            except KeyError as error:
                # 模板引用了不存在的节点 —— 声明错误，重试无意义
                raise _WorkflowFailure(
                    node.name,
                    f'节点 {node.name} 的模板引用了不存在的节点: {error}'
                    ) from error
            except Exception as error:  # noqa: BLE001
                last_error = str(error)
                logger.warning('节点 %s 第 %d 次尝试失败: %s',
                               node.name, attempt + 1, last_error)
        raise _WorkflowFailure(node.name,
                               f'节点 {node.name} 在 {attempts} 次尝试后仍失败: '
                               f'{last_error}')

    async def _run_tool_node(self, node: WorkflowNode, ctx: KernelContext,
                             tools: Any, outputs: dict[str, str]) -> str:
        if tools is None:
            raise _WorkflowFailure(node.name, '工作流没有可用的工具注册表')
        args = node.render(node.args, outputs)
        if not isinstance(args, dict):
            raise _WorkflowFailure(node.name,
                                   f'节点 {node.name} 的 args 模板渲染后不是 dict')
        # 统一入口（§3.2 规则 5）：守卫在这里生效
        result = await tools.execute_async(node.tool, args)
        if not result.success:
            raise _WorkflowFailure(
                node.name,
                f'工具 {node.tool} 调用失败: {result.error or result.output}')
        from ..tools.registry import tool_result_text
        return tool_result_text(result.output)

    async def _run_model_node(self, node: WorkflowNode, ctx: KernelContext,
                              model: Any, outputs: dict[str, str]) -> str:
        if model is None:
            raise _WorkflowFailure(node.name, '工作流没有可用的模型客户端')
        prompt = node.render(node.prompt, outputs)
        messages = self._messages(ctx, str(prompt))
        response = await _call_model(model, messages)
        content = getattr(response, 'content', '') or ''
        return str(content)

    def _messages(self, ctx: KernelContext, user_text: str) -> list[dict]:
        messages: list[dict] = []
        if ctx.system_prompt:
            messages.append({'role': 'system', 'content': ctx.system_prompt})
        for item in ctx.input:
            if isinstance(item, dict):
                messages.append(dict(item))
            else:
                messages.append({'role': 'user',
                                 'content': str(getattr(item, 'content', item))})
        if user_text:
            messages.append({'role': 'user', 'content': user_text})
        return messages

    def _final_text(self, nodes: list[WorkflowNode], outputs: dict[str, str],
                    ctx: KernelContext) -> str:
        for node in reversed(nodes):
            if node.name in outputs:
                return outputs[node.name]
        return ''

    # ── 失败补偿 ──────────────────────────────────────────
    async def _compensate(self, completed: list[WorkflowNode],
                          ctx: KernelContext, tools: Any) -> list[str]:
        """逆序执行已完成节点的补偿动作。

        补偿失败**不抛** —— 补偿是尽力而为的回滚，把失败记进返回值，
        让上层与审计看到完整真相（哪一步没能撤销）。
        """
        errors: list[str] = []
        for node in reversed(completed):
            if not node.compensate:
                continue
            if tools is None:
                errors.append(f'{node.name}: 无工具注册表，补偿未执行')
                continue
            args = node.render(node.compensate_args, {})
            if not isinstance(args, dict):
                errors.append(f'{node.name}: 补偿参数模板渲染后不是 dict')
                continue
            try:
                result = await tools.execute_async(node.compensate, args)
                if not result.success:
                    errors.append(
                        f'{node.name}: 补偿工具 {node.compensate} 失败: '
                        f'{result.error or result.output}')
            except Exception as error:  # noqa: BLE001
                errors.append(f'{node.name}: 补偿异常: {error}')
        return errors


class _WorkflowFailure(Exception):
    """节点失败（带节点名，供 stop_reason 与补偿使用）。"""

    def __init__(self, node: str, message: str) -> None:
        super().__init__(message)
        self.node = node


async def _call_model(model: Any, messages: list[dict], **kwargs: Any) -> Any:
    """调用模型；同步/异步 invoke 都吃 —— 测试里的假模型两种都有。"""
    result = model.invoke(messages, **kwargs)
    if inspect.isawaitable(result):
        result = await result
    return result


def workflow_from_dict(specs: list[dict]) -> list[WorkflowNode]:
    """从 artifact/配置的 dict 形状构造节点列表。"""
    nodes = []
    for spec in specs:
        known = {k: spec[k] for k in
                 ('name', 'kind', 'tool', 'args', 'prompt', 'depends_on',
                  'retries', 'compensate', 'compensate_args')
                 if k in spec}
        known.setdefault('name', '')
        nodes.append(WorkflowNode(**known))
    validate_workflow(nodes)
    return nodes


def workflow_from_yaml(text: str) -> list[WorkflowNode]:
    """从 YAML 形状构造节点列表（agent.yaml 的 spec.workflow 直接可用）。"""
    import yaml
    data = yaml.safe_load(text)
    if not isinstance(data, dict) or 'steps' not in data:
        raise WorkflowValidationError(
            "工作流 YAML 必须是 {'steps': [...]} 的形状")
    return workflow_from_dict(data['steps'])


__all__ = [
    'NODE_MODEL',
    'NODE_TOOL',
    'WorkflowKernel',
    'WorkflowNode',
    'WorkflowValidationError',
    'validate_workflow',
    'workflow_from_dict',
    'workflow_from_yaml',
]
