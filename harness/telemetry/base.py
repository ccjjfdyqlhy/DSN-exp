# harness/telemetry/base.py
# 遥测（trace / span）的**内核侧契约** + 共享原语的再导出。
#
# 依赖方向：harness → infra，单向。span 的数据形状与 id 生成住在
# infra/observability/span.py（端口与共享数据类型住 infra，与
# infra/orchestrator/base.py 的 IChatClient、infra/store 的 IStore 同模式）；
# 这里只做再导出，让内核侧继续用短路径，同时「Span 到底是什么」只有一个答案。
#
# 唯一**定义**在本文件的，是 TelemetryPort —— 内核对外发事件的端口。
# 它必须留在内核侧：内核承诺「我只 emit 事件，不做格式化」，
# 这份承诺的正式文本属于内核。
#
# 原则（策划案 §3.3.4「一切皆事件」）：Kernel 只产出事件，**不做格式化**。
# trace、审计、成本、评估都是同一批事件的不同消费者。事件消费者要能容忍
# 重复投递，所以事件带 seq，消费者按 seq 去重。
#
# 向后兼容：既有事件 kind 一个不改，只新增三个可选字段
# （trace_id / span_id / seq）。见 harness/agent/events.py。

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from infra.observability.span import (
    Span,
    SpanHandle,
    SpanKind,
    current_span_id,
    current_trace_id,
    new_span_id,
    new_trace_id,
)


@runtime_checkable
class TelemetryPort(Protocol):
    """事件出口。

    实现：infra/observability/trace.py（扇出成 span）、harness/agent/events.py
    的 EventSink（既有路径）。Kernel 只调 emit。

    这是**结构化类型**：实现方不需要继承或 import 这个 Protocol，
    任何有 ``emit(kind, payload)`` 的对象都算。
    """

    def emit(self, kind: str, payload: dict[str, Any]) -> None: ...


__all__ = [
    'Span',
    'SpanHandle',
    'SpanKind',
    'TelemetryPort',
    'new_trace_id',
    'new_span_id',
    'current_trace_id',
    'current_span_id',
]
