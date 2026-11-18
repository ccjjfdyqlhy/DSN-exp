# harness/telemetry —— 遥测协议与 span 工具。

from .base import (
    Span,
    SpanHandle,
    SpanKind,
    TelemetryPort,
    current_span_id,
    current_trace_id,
    new_span_id,
    new_trace_id,
)

__all__ = [
    'Span',
    'SpanHandle',
    'SpanKind',
    'TelemetryPort',
    'current_trace_id',
    'current_span_id',
    'new_trace_id',
    'new_span_id',
]

# ── R5：span 上下文 + JSONL 导出 + 统一脱敏 ─────────────────
# 追加导出（不覆盖既有内容）：契约层仍然是 base 的那套，
# 这里只是把「运行期工具」也挂上来，方便 `from harness.telemetry import *`。
from .span import (  # noqa: E402
    SeqCounter,
    TraceContext,
    current_context,
    ensure_span_id,
    ensure_trace_id,
    new_span,
    new_trace,
    span_scope,
    stamp,
    start_span,
    trace_scope,
)
from .exporter import (  # noqa: E402
    REDACTED,
    REFERENCE_KEY_SUFFIXES,
    SECRET_VALUE_PREFIXES,
    SENSITIVE_KEYS,
    SENSITIVE_KEY_PARTS,
    TRACE_FILENAME,
    TraceExporter,
    export_trace,
    read_jsonl,
    redact,
    redact_dict,
    write_jsonl,
)

__all__ += [
    'REDACTED',
    'REFERENCE_KEY_SUFFIXES',
    'SECRET_VALUE_PREFIXES',
    'SENSITIVE_KEYS',
    'SENSITIVE_KEY_PARTS',
    'TRACE_FILENAME',
    'SeqCounter',
    'TraceContext',
    'TraceExporter',
    'current_context',
    'ensure_span_id',
    'ensure_trace_id',
    'export_trace',
    'new_span',
    'new_trace',
    'read_jsonl',
    'redact',
    'redact_dict',
    'span_scope',
    'stamp',
    'start_span',
    'trace_scope',
    'write_jsonl',
]
