# harness/telemetry/span.py
# span / trace 的 id 生成与上下文管理的**再导出薄壳**。
#
# 实现住在 infra/observability/span.py（共享原语住 infra，harness 往上依赖）。
# 这里保留薄壳是为了让内核侧能用 `from .span import trace_scope` 这样的
# 短路径，同时保证「上下文怎么管」只有一个答案 —— 两边各写一份必然分叉。
#
# 为什么用 contextvars 而不是 threading.local：
#   - 同一线程里可能并发跑多个 turn（asyncio），thread-local 会串味；
#   - asyncio.to_thread 会复制 contextvars，工具在线程里仍能拿到 trace_id；
#   - 嵌套（span 里再开 span）天然形成父子链。
#
# 缺陷备忘（踩过的坑写在这里，别再踩）：
#   - contextvars **不跨线程自动传播**（只有 asyncio.to_thread 这类显式
#     copy_context 的路径会带过去）：裸 Thread 里必须用 trace_scope 显式设置。
#   - reset 必须在 finally 里做，否则异常路径会把上下文泄漏给下一个任务。

from __future__ import annotations

from aicf.infra.observability.span import (
    EventSink,
    SeqCounter,
    TraceContext,
    current_context,
    current_span_id,
    current_trace_id,
    ensure_span_id,
    ensure_trace_id,
    new_span,
    new_span_id,
    new_trace,
    new_trace_id,
    span_scope,
    stamp,
    start_span,
    trace_scope,
)

__all__ = [
    'EventSink',
    'SeqCounter',
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
