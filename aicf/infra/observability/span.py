# infra/observability/span.py
# span / trace 的**共享原语**：数据形状 + id 生成 + 上下文管理。
#
# 为什么住在 infra（而不是 harness）：仓库的依赖规则是 **harness → infra，
# 单向**。端口与共享数据类型住在 infra（IChatClient 在 infra/orchestrator、
# IStore 在 infra/store、Identity 在 infra/auth、PolicyDecision 在
# infra/policy），harness 往上依赖它们。span 的数据形状属于同一类：
# 生产方（harness 内核）和消费者（infra 的 trace / 审计 / 评估）都要用。
#
# 反过来 infra import aicf.harness 就是违规 —— 历史上 infra/observability/core.py
# 反向 import aicf.harness.pipeline.events 就是这么被清掉的（见 docs/architecture.md）。
# 现在有 tests/test_rc0_dependency_direction.py 钉着这条规则。
#
# 依赖方向：harness/telemetry/base.py 是本模块的**再导出薄壳**，
# 内核侧继续用 `from aicf.harness.telemetry import Span` 这样的短路径，
# 而「Span 到底是什么」只有一个答案。
#
# 原则（策划案 §3.3.4「一切皆事件」）：Kernel 只产出事件，**不做格式化**。
# trace、审计、成本、评估都是同一批事件的不同消费者。事件消费者要能容忍
# 重复投递，所以事件带 seq，消费者按 seq 去重。
#
# 缺陷备忘（踩过的坑写在这里，别再踩）：
#   - contextvars **不跨线程自动传播**（只有 asyncio.to_thread 这类显式
#     copy_context 的路径会带过去）：裸 Thread 里必须用 trace_scope 显式设置。
#   - reset 必须在 finally 里做，否则异常路径会把上下文泄漏给下一个任务。
#   - current_trace_id / current_span_id 的默认值是空串而不是 None：
#     空串是「没有」；None 会让下游 `if trace_id:` 与 `if trace_id is not None`
#     两种判断给出不同答案。
#   - Span 是 frozen dataclass，但 attrs 是可变 dict —— 改 attrs 用
#     `span.attrs[k] = v`，**不能** `span.attrs = {...}`（FrozenInstanceError）。

from __future__ import annotations

import contextvars
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator, Literal

#: span kind（与 trace 里出现的阶段对应）
SpanKind = Literal['run', 'model_call', 'tool_call', 'approval', 'context_build',
                   'memory', 'usage', 'audit', 'latency']


def new_trace_id() -> str:
    return uuid.uuid4().hex


def new_span_id() -> str:
    return uuid.uuid4().hex[:16]


@dataclass(frozen=True)
class Span:
    """一次可测量的操作。

    trace_id       一次 run 的 id
    span_id        本 span 的 id
    parent_span_id 父 span
    name           名字（如 'model_call' / 'tool:shell'）
    kind           span 类型
    start          起始时间（epoch 秒）
    end            结束时间；未结束为 None
    attrs          附加属性（已脱敏）
    status         ok | error | denied
    """

    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    name: str = ''
    kind: str = 'run'
    start: float = 0.0
    end: float | None = None
    attrs: dict = field(default_factory=dict)
    status: str = 'ok'

    def to_dict(self) -> dict:
        return {
            'trace_id': self.trace_id,
            'span_id': self.span_id,
            'parent_span_id': self.parent_span_id,
            'name': self.name,
            'kind': self.kind,
            'start': self.start,
            'end': self.end,
            'attrs': self.attrs,
            'status': self.status,
        }


#: 事件出口的**正式协议**（TelemetryPort）定义在 harness/telemetry/base.py ——
#: 那是内核对外的契约，必须留在内核侧。
#:
#: 本模块（infra 侧）**不 import** 它：Protocol 是结构化类型，任何有
#: ``emit(kind, payload)`` 方法的对象都满足，实现方既不需要继承也不需要
#: import 协议。所以 infra 侧的形参标注用 Any + 文档说明即可 ——
#: 少一条 infra → harness 的依赖，比多一个类型标注值钱。
EventSink = Any


class SpanHandle:
    """一个进行中的 span。

    用作 context manager：退出时自动结束并发出事件。
    事件通过 TelemetryPort.emit 发出，Kernel 不直接碰 trace 格式。
    """

    def __init__(self, telemetry: EventSink, span: Span) -> None:
        """telemetry 是事件出口（任何有 ``emit(kind, payload)`` 的对象）。

        正式协议见 harness/telemetry/base.py 的 TelemetryPort —— 那是内核
        对外的契约，本模块不 import 它（结构化类型，不需要）。
        """
        self._telemetry = telemetry
        self.span = span
        self._ended = False

    def set_attr(self, key: str, value: Any) -> None:
        # Span 是 frozen 的，但 attrs 是可变 dict —— 直接改 attrs 即可。
        self.span.attrs[key] = value

    def set_status(self, status: str) -> None:
        object.__setattr__(self.span, 'status', status)

    def end(self, *, status: str | None = None, **attrs: Any) -> None:
        if self._ended:
            return
        self._ended = True
        import time as _time
        object.__setattr__(self.span, 'end', _time.time())
        if status is not None:
            object.__setattr__(self.span, 'status', status)
        if attrs:
            self.span.attrs.update(attrs)
        self._telemetry.emit('span_end', self.span.to_dict())

    def __enter__(self) -> 'SpanHandle':
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            self.end(status='error', error=str(exc))
        else:
            self.end()
        return False


#: 当前 trace / span 的上下文（contextvars，跨线程需要显式传递）
current_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    'aicf_current_trace_id', default='')
current_span_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    'aicf_current_span_id', default='')


@dataclass(frozen=True)
class TraceContext:
    """当前所处的 trace / span 位置。

    parent_span_id 用于重建父子链：事件里只有 span_id 时，靠它向上找父。
    """

    trace_id: str
    span_id: str
    parent_span_id: str | None = None


class SeqCounter:
    """单调递增的事件序号。

    seq 是消费方去重的唯一依据（策划案 §4.2.3）：journal 重放会**重复投递**
    同一个事件，消费方按 seq 去重才不会重复计费。

    注意：seq 不是全局唯一的 —— 它只在一条流（一次 run / 一个 session）内
    单调。多条流各自计数。这也是为什么事件去重要用 (trace_id, seq) 而不是
    单看 seq。
    """

    def __init__(self, start: int = 0) -> None:
        self._value = int(start)

    @property
    def value(self) -> int:
        return self._value

    def next(self) -> int:
        self._value += 1
        return self._value

    def observe(self, seq: int) -> None:
        """见到外部 seq 时抬高计数，避免自增的 seq 跟外部 seq 撞号。"""
        if isinstance(seq, int) and not isinstance(seq, bool) and seq > self._value:
            self._value = seq


def new_trace() -> str:
    """生成一个 trace id（new_trace_id 的语义别名）。"""
    return new_trace_id()


def new_span() -> str:
    """生成一个 span id（new_span_id 的语义别名）。"""
    return new_span_id()


def ensure_trace_id(trace_id: str | None = None) -> str:
    """有就用，没有就造 —— 不覆盖生产方已经盖好的章。"""
    return trace_id or new_trace_id()


def ensure_span_id(span_id: str | None = None) -> str:
    return span_id or new_span_id()


def current_context() -> TraceContext | None:
    """当前上下文；没有任何上下文时返回 None（而不是空串 TraceContext）。"""
    tid = current_trace_id.get()
    sid = current_span_id.get()
    if not tid and not sid:
        return None
    return TraceContext(trace_id=tid or new_trace_id(), span_id=sid)


@contextmanager
def trace_scope(trace_id: str | None = None,
                span_id: str | None = None,
                parent_span_id: str | None = None) -> Iterator[TraceContext]:
    """进入一个 trace 上下文；退出时恢复原值。

    传 trace_id=None 表示「沿用当前 trace，没有就新建一个」。
    """
    ctx = TraceContext(
        trace_id=ensure_trace_id(trace_id or current_trace_id.get() or None),
        span_id=ensure_span_id(span_id),
        parent_span_id=parent_span_id,
    )
    t_token = current_trace_id.set(ctx.trace_id)
    s_token = current_span_id.set(ctx.span_id)
    try:
        yield ctx
    finally:
        current_span_id.reset(s_token)
        current_trace_id.reset(t_token)


@contextmanager
def span_scope(handle: SpanHandle | Span) -> Iterator[Span]:
    """进入一个 span 上下文（span 里的事件自动带上这个 span_id）。"""
    span = handle.span if isinstance(handle, SpanHandle) else handle
    t_token = current_trace_id.set(span.trace_id)
    s_token = current_span_id.set(span.span_id)
    try:
        yield span
    finally:
        current_span_id.reset(s_token)
        current_trace_id.reset(t_token)


def start_span(telemetry: EventSink,
               name: str,
               *,
               kind: str = 'run',
               parent_span_id: str | None = None,
               trace_id: str | None = None,
               **attrs: Any) -> SpanHandle:
    """开一个 span 并返回句柄。

    父 span 缺省取当前上下文里的 span_id —— 于是嵌套调用天然形成父子链，
    调用方不需要自己维护父子关系。

    事件出口只有一个：telemetry.emit('span_end', ...)。Kernel 不碰 trace
    格式（策划案 §4.1.6）。
    """
    parent = parent_span_id if parent_span_id is not None else (current_span_id.get() or None)
    span = Span(
        trace_id=ensure_trace_id(trace_id or current_trace_id.get() or None),
        span_id=new_span_id(),
        parent_span_id=parent,
        name=name,
        kind=kind,
        start=time.time(),
        attrs=dict(attrs),
    )
    return SpanHandle(telemetry, span)


def stamp(payload: dict[str, Any] | None = None,
          *,
          trace_id: str | None = None,
          span_id: str | None = None,
          seq: int | None = None) -> dict[str, Any]:
    """给事件补上三个**可选**字段：trace_id / span_id / seq。

    规则：
      - 缺失才补，已有值不覆盖（同一个事件可能被多个生产者盖章）；
      - trace_id / span_id 缺省取当前上下文，没有上下文就**不补** ——
        补一个空串会让下游误以为「有 trace 但 id 为空」；
      - seq 缺省不补 —— seq 的语义是「这条流里的第几条」，跨流没有意义，
        谁补谁负责。
    """
    out = dict(payload or {})
    tid = trace_id or current_trace_id.get() or None
    sid = span_id or current_span_id.get() or None
    if tid and not out.get('trace_id'):
        out['trace_id'] = tid
    if sid and not out.get('span_id'):
        out['span_id'] = sid
    if seq is not None and out.get('seq') is None:
        out['seq'] = seq
    return out


__all__ = [
    'EventSink',
    'SeqCounter',
    'Span',
    'SpanHandle',
    'SpanKind',
    'TraceContext',
    'current_context',
    'current_span_id',
    'current_trace_id',
    'ensure_span_id',
    'ensure_trace_id',
    'new_span',
    'new_span_id',
    'new_trace',
    'new_trace_id',
    'span_scope',
    'stamp',
    'start_span',
    'trace_scope',
]
