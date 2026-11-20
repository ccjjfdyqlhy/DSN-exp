# infra/observability/__init__.py
# 通用可观测性 — 计时/计数/事件日志 + token 用量与成本追踪。

from .core import MetricsCollector, EventLogger, Metric
from .usage import UsageTracker, UsageRecord, Price, fmt_tokens

__all__ = [
    "MetricsCollector",
    "EventLogger",
    "Metric",
    "UsageTracker",
    "UsageRecord",
    "Price",
    "fmt_tokens",
]

# ── R5：trace 扇出 + 统一审计（追加导出，不改动既有内容）──────
from .span import (
    EventSink,
    SeqCounter,
    Span,
    SpanHandle,
    SpanKind,
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
# 注意：这里**不** re-export `redact` 函数 —— 它与本包下的 `redact` 模块
# 同名。再导出一次会把 `infra.observability.redact` 从「模块」变成「函数」，
# 于是 `import aicf.infra.observability.redact as m` 拿到的是函数而不是模块
# （同名遮蔽，最难查的一类 bug）。要函数请写：
#     from aicf.infra.observability.redact import redact
from .redact import (
    REDACTED,
    REFERENCE_KEY_SUFFIXES,
    SECRET_VALUE_PREFIXES,
    SENSITIVE_KEYS,
    read_jsonl,
    redact_dict,
    write_jsonl,
)
from .trace import (
    SPAN_KINDS,
    TraceBuilder,
    TraceCollector,
    TraceFanout,
    build_trace,
    export_events,
    span_record,
)
from .audit import (
    AUDIT_KINDS,
    DENY_REASONS,
    ArgsDigest,
    AuditImmutableError,
    AuditLog,
    AuditRecord,
    AuditStore,
    args_digest,
)

__all__ += [
    "AUDIT_KINDS",
    "EventSink",
    "REDACTED",
    "REFERENCE_KEY_SUFFIXES",
    "SECRET_VALUE_PREFIXES",
    "SENSITIVE_KEYS",
    "SeqCounter",
    "Span",
    "SpanHandle",
    "SpanKind",
    "TraceContext",
    "current_context",
    "current_span_id",
    "current_trace_id",
    "ensure_span_id",
    "ensure_trace_id",
    "new_span",
    "new_span_id",
    "new_trace",
    "new_trace_id",
    "read_jsonl",
    "redact_dict",
    "span_scope",
    "stamp",
    "start_span",
    "trace_scope",
    "write_jsonl",
    "DENY_REASONS",
    "SPAN_KINDS",
    "ArgsDigest",
    "AuditImmutableError",
    "AuditLog",
    "AuditRecord",
    "AuditStore",
    "TraceBuilder",
    "TraceCollector",
    "TraceFanout",
    "args_digest",
    "build_trace",
    "export_events",
    "span_record",
]
