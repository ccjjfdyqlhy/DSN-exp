# infra/observability/trace.py
# 事件流 → trace 扇出（策划案 §4.1.6 / R5）。
#
# 为什么 Kernel 不直接写 trace：§3.3.4「一切皆事件」—— Kernel 只产出事件，
# trace / 审计 / 成本 / 评估是**同一批事件的不同消费者**。格式化的责任在消费
# 侧：换导出格式（JSONL / OTel）时 Kernel 一行都不用改。
#
# 事件 → span 的映射（**不新增任何事件 kind**，只消费既有词表）：
#
#   run_started / run_finished / run_failed      → run span（根）
#   turn_start / turn_end                        → turn span
#   thinking_end / text_end                      → model_call span
#   usage                                        → usage span
#   tool_start / tool_end / tool_blocked         → tool_call span
#   approval_request / approval_decision /
#   approval_timeout                             → approval span
#   任何带时长的事件                              → latency span
#   audit.*                                      → audit span
#   span_end（SpanHandle 结束时发出的）            → 直接收下这个 span
#
# 另外兼容「已经是 span 语义」的事件 kind：model_call / tool_call /
# usage / latency / approval / context_build / memory —— 生产方直接发
# 这种事件时，trace 照样收下，不会因为换了写法就少一半内容。
#
# 向后兼容（验收标准 1）：
#   - 既有事件 kind 一个不改，本模块只**读**它们；
#   - trace_id / span_id / seq 缺失时（v1 生产者）自己补齐，
#     消费方对缺失必须容忍而不是报错；
#   - 未知 kind 直接忽略，不抛异常 —— 事件词表会继续长。
#
# 去重：§4.2.3 要求消费方按 seq 去重（journal 重放会重复投递同一个事件）。
# 带 seq 的事件重复到达时只处理一次。
#
# 缺陷备忘：
#   - 「duration」单位不一致：harness 事件里的 duration 是**秒**
#     （time.monotonic 差值），usage.latency_ms 是**毫秒**。
#     混用会让 trace 的耗时全错，所以统一在 _duration_ms 里归一成毫秒。
#   - model_call span 的结束时机不确定：有 thinking 无 text（被中断）时，
#     要等 usage 事件或 run 结束才收尾，否则 span 永远开着。
#   - 晚到的 usage 事件（provider / model 信息）要回填到已经结束的
#     model span 上 —— 回填不了就只能看到「模型调了但不知道用的哪个模型」。

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

from .redact import redact_dict, write_jsonl
from .span import SeqCounter, Span, SpanHandle, new_span_id, new_trace_id, start_span

_LOGGER = logging.getLogger('aicf.infra.observability.trace')

__all__ = [
    'SPAN_KINDS',
    'TraceBuilder',
    'TraceCollector',
    'TraceFanout',
    'build_trace',
    'export_events',
    'span_record',
]

#: R5 要求覆盖的五类 span（+ run / audit 两类结构性 span）
SPAN_KINDS = ('model_call', 'tool_call', 'usage', 'latency', 'approval')

#: 审批决定里表示「放行」的值（大小写不敏感）
_APPROVED_WORDS = ('approve', 'approved', 'allow', 'allowed', 'yes', 'ok', 'grant', 'granted')


def _is_approved(decision: Any) -> bool:
    return str(decision or '').strip().lower() in _APPROVED_WORDS


def _duration_ms(payload: Mapping[str, Any]) -> float | None:
    """把各种时长字段归一成毫秒；没有则返回 None。

    harness 事件的 duration 是秒，latency_ms / duration_ms 是毫秒。
    """
    for key in ('duration_ms', 'latency_ms'):
        value = payload.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    value = payload.get('duration')
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) * 1000.0
    return None


def span_record(span: Span,
                *,
                seq: int | None = None,
                run_id: str = '') -> dict[str, Any]:
    """span → 一行 JSONL 记录。

    字段名与 infra.observability.span.Span.to_dict 对齐（多两个便利字段：
    type / seq / duration_ms），这样「span 对象」和「trace 文件里的行」
    能互相对照。
    """
    record: dict[str, Any] = {
        'type': 'span',
        'trace_id': span.trace_id,
        'span_id': span.span_id,
        'parent_span_id': span.parent_span_id,
        'name': span.name,
        'kind': span.kind,
        'start': span.start,
        'end': span.end,
        'status': span.status,
        'attrs': dict(span.attrs),
    }
    if seq is not None:
        record['seq'] = seq
    if run_id:
        record['run_id'] = run_id
    if span.end is not None and span.start:
        record['duration_ms'] = round((span.end - span.start) * 1000.0, 3)
    return record


class TraceCollector:
    """把事件流转成 trace（span 集合）。

    用法::

        collector = TraceCollector(run_id='run-1')
        for kind, payload in events:
            collector.emit(kind, payload)
        collector.export('trace.jsonl')

    它同时是一个 ``TelemetryPort``：可以直接塞进 Kernel 当事件出口。
    """

    def __init__(self,
                 *,
                 trace_id: str | None = None,
                 run_id: str | None = None,
                 session_id: str | None = None,
                 redact_values: bool = True) -> None:
        self.trace_id = trace_id or new_trace_id()
        self.run_id = run_id or ''
        self.session_id = session_id or ''
        self.redact_values = redact_values
        self._seq = SeqCounter()
        self._seen_seq: set[int] = set()
        self._spans: dict[str, Span] = {}
        self._records: list[dict[str, Any]] = []
        self._open: dict[str, Span] = {}
        #: 扇出过程中吞掉的异常（遥测出错不该让业务炸，但必须留痕）
        self._errors: list[tuple[str, Exception]] = []
        #: 最近一条事件的 seq（生产方的），写进 span attrs 用于对账
        self._event_seq: int | None = None

    # ── TelemetryPort ───────────────────────────────────
    def emit(self, kind: str, payload: dict[str, Any] | None = None) -> None:
        """吃一条事件，扇出成 span。**永不抛异常**（遥测不能拖垮业务）。"""
        try:
            self._emit(kind, payload)
        except Exception as exc:
            # 遥测不该让主流程炸，但**不能静默**：静默的失败会把
            # 「trace 里少了一段」变成无法排查的灵异事件。
            self._errors.append((kind, exc))
            _LOGGER.warning('trace 扇出失败 kind=%s: %s', kind, exc, exc_info=True)

    def _emit(self, kind: str, payload: dict[str, Any] | None) -> None:
        data = dict(payload or {})

        trace_id = data.get('trace_id')
        if isinstance(trace_id, str) and trace_id:
            self.trace_id = trace_id

        seq = data.get('seq')
        if isinstance(seq, int) and not isinstance(seq, bool):
            if seq in self._seen_seq:
                return  # 重复投递：按 seq 去重（§4.2.3）
            self._seen_seq.add(seq)
            self._seq.observe(seq)
            # 记住生产方的 seq：写进 span attrs，trace 才能对回事件流。
            # 注意 seq 有两个空间 —— 生产方的（事件流内去重用）与本收集器
            # 自己发的（trace 文件内排序用）。两者不混用，故此分开存。
            self._event_seq = seq

        if kind == 'span_end':
            self._ingest_span(data, closed=True)
            return
        if kind == 'span_start':
            self._ingest_span(data, closed=False)
            return
        if kind.startswith('audit.'):
            self._h_audit(kind, data)
            return
        if kind in _SPAN_EVENT_KINDS:
            handler = _SPAN_EVENT_HANDLERS.get(kind)
            if handler is None:
                self._h_generic_span(kind, data)
            else:
                handler(self, data)
            return

        handler = _HANDLERS.get(kind)
        if handler is None:
            return  # 未知 kind：词表会继续长，忽略而不是报错
        handler(self, data)

    # ── span 生命周期 ───────────────────────────────────
    def _new_span(self,
                  name: str,
                  kind: str,
                  parent: Span | None = None,
                  attrs: Mapping[str, Any] | None = None) -> Span:
        merged = dict(attrs or {})
        if self._event_seq is not None:
            merged.setdefault('event_seq', self._event_seq)
        return Span(
            trace_id=self.trace_id,
            span_id=new_span_id(),
            parent_span_id=parent.span_id if parent is not None else None,
            name=name,
            kind=kind,
            start=time.time(),
            attrs=merged,
        )

    def _parent(self) -> Span | None:
        """当前该挂在谁下面：turn > root > None。"""
        return self._open.get('turn') or self._open.get('root')

    def _record(self, span: Span) -> None:
        """把一个 span 收进 trace（只登记，不改它的 end/status）。"""
        if span.span_id in self._spans:
            return
        self._spans[span.span_id] = span
        self._records.append(
            span_record(span, seq=self._seq.next(), run_id=self.run_id))

    def _finish(self, span: Span, status: str = 'ok', **attrs: Any) -> Span:
        if span.end is not None:
            return span  # 已经收过了
        object.__setattr__(span, 'end', time.time())
        object.__setattr__(span, 'status', status)
        if attrs:
            span.attrs.update(attrs)
        self._record(span)
        return span

    def _close(self, key: str, status: str = 'ok', **attrs: Any) -> Span | None:
        span = self._open.pop(key, None)
        if span is None:
            return None
        return self._finish(span, status, **attrs)

    def _ingest_span(self, data: Mapping[str, Any], *, closed: bool) -> None:
        """收下 SpanHandle 结束时发出的 span（span_end 事件）。"""
        span_id = data.get('span_id')
        if not isinstance(span_id, str) or not span_id:
            return
        span = Span(
            trace_id=str(data.get('trace_id') or self.trace_id),
            span_id=span_id,
            parent_span_id=data.get('parent_span_id'),
            name=str(data.get('name') or ''),
            kind=str(data.get('kind') or 'run'),
            start=float(data.get('start') or 0.0),
            end=data.get('end'),
            attrs=dict(data.get('attrs') or {}),
            status=str(data.get('status') or 'ok'),
        )
        if self.redact_values:
            # Span 是 frozen 的，但 attrs 是可变 dict —— 原地改，不能赋值。
            span.attrs.clear()
            span.attrs.update(redact_dict(span.attrs))
        if closed:
            self._open.pop(span_id, None)
            self._record(span)
        else:
            self._open[span_id] = span

    # ── 事件处理 ────────────────────────────────────────
    def _h_run_started(self, p: Mapping[str, Any]) -> None:
        self.run_id = str(p.get('run_id') or self.run_id)
        self.session_id = str(p.get('session_id') or self.session_id)
        if 'root' in self._open:
            return
        attrs = {k: p[k] for k in ('run_id', 'session_id') if p.get(k)}
        self._open['root'] = self._new_span('run', 'run', None, attrs)

    def _h_run_finished(self, p: Mapping[str, Any]) -> None:
        self.run_id = str(p.get('run_id') or self.run_id)
        status = str(p.get('status') or 'ok').lower()
        final = 'error' if status in ('failed', 'error', 'interrupted') else 'ok'
        self._close('turn', final, run_status=status)
        self._close('root', final, run_status=status)

    def _h_run_failed(self, p: Mapping[str, Any]) -> None:
        error = str(p.get('error') or '')
        self._close('turn', 'error', error=error)
        self._close('root', 'error', error=error)

    def _h_turn_start(self, p: Mapping[str, Any]) -> None:
        parent = self._open.get('root')
        if 'turn' in self._open:
            self._close('turn', 'ok')
        attrs = {'turn': p.get('turn')} if p.get('turn') is not None else {}
        self._open['turn'] = self._new_span('turn', 'run', parent, attrs)

    def _h_turn_end(self, p: Mapping[str, Any]) -> None:
        status = str(p.get('status') or 'ok').lower()
        final = 'ok' if status in ('ok', 'done', 'success') else 'error'
        self._close('turn', final, status=status)

    # ── model_call ──────────────────────────────────────
    def _model_step(self, p: Mapping[str, Any], phase: str, *, close: bool) -> None:
        span = self._open.get('model')
        if span is None:
            span = self._new_span('model_call', 'model_call', self._parent())
            self._open['model'] = span
        phases = span.attrs.setdefault('phases', [])
        if isinstance(phases, list):
            phases.append(phase)
        duration = _duration_ms(p)
        if duration is not None:
            span.attrs[f'{phase}_duration_ms'] = duration
            span.attrs['duration_ms'] = float(span.attrs.get('duration_ms') or 0.0) + duration
        text = p.get('text')
        if isinstance(text, str):
            span.attrs['text_len'] = len(text)
        if close:
            self._close('model', 'ok')
        if duration is not None:
            self._emit_latency(p, source=phase, parent=span, duration_ms=duration)

    def _h_thinking_end(self, p: Mapping[str, Any]) -> None:
        self._model_step(p, 'thinking', close=False)

    def _h_text_end(self, p: Mapping[str, Any]) -> None:
        self._model_step(p, 'text', close=True)

    # ── usage ───────────────────────────────────────────
    def _h_usage(self, p: Mapping[str, Any]) -> None:
        model_span = self._open.get('model')
        if model_span is not None:
            self._close('model', 'ok')
        keys = ('input_tokens', 'cached_input_tokens', 'uncached_input_tokens',
                'output_tokens', 'cache_hit_rate', 'prefix_generation',
                'prefix_hash', 'provider', 'model')
        attrs = {k: p[k] for k in keys if p.get(k) is not None}
        parent = model_span or self._parent()
        span = self._new_span('usage', 'usage', parent, attrs)
        self._finish(span, 'ok')
        duration = _duration_ms(p)
        if duration is not None:
            self._emit_latency(p, source='usage', parent=span, duration_ms=duration)
        self._enrich_model(attrs)

    def _enrich_model(self, attrs: Mapping[str, Any]) -> None:
        """把迟到的 provider/model 信息回填到最近结束的 model span。

        没有这一步，trace 里只剩「模型调了」，不知道调的哪个模型 ——
        而那恰恰是排查成本问题时最需要的信息。
        """
        if not attrs:
            return
        for span in reversed(list(self._spans.values())):
            if span.kind != 'model_call':
                continue
            for key, value in attrs.items():
                span.attrs.setdefault(key, value)
            return

    # ── tool_call ───────────────────────────────────────
    def _tool_attrs(self, p: Mapping[str, Any]) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        name = p.get('name') or p.get('display')
        if name:
            attrs['tool'] = name
        call_id = p.get('call_id')
        if call_id:
            attrs['call_id'] = str(call_id)
        args = p.get('args')
        if args is not None:
            attrs['args'] = args if not self.redact_values else redact_dict(args)
        return attrs

    def _h_tool_start(self, p: Mapping[str, Any]) -> None:
        call_id = str(p.get('call_id') or p.get('id') or new_span_id())
        key = f'tool:{call_id}'
        attrs = self._tool_attrs(p)
        attrs.setdefault('call_id', call_id)
        name = attrs.get('tool') or 'tool'
        self._open[key] = self._new_span(f'tool:{name}', 'tool_call', self._parent(), attrs)

    def _h_tool_end(self, p: Mapping[str, Any]) -> None:
        call_id = str(p.get('call_id') or '')
        key = f'tool:{call_id}'
        span = self._open.pop(key, None)
        if span is None:
            # 只有 tool_end 没有 tool_start（老生产者 / 事件被丢了一条）：
            # 照样补一个 span，别让这次调用在 trace 里凭空消失。
            attrs = self._tool_attrs(p)
            span = self._new_span(
                f"tool:{attrs.get('tool') or 'tool'}", 'tool_call', self._parent(), attrs)
        duration = _duration_ms(p)
        if duration is not None:
            span.attrs['duration_ms'] = duration
        output = p.get('output')
        if isinstance(output, str):
            span.attrs['output_len'] = len(output)
        error = p.get('error')
        if error:
            span.attrs['error'] = str(error)[:200]
        diff = p.get('diff')
        if isinstance(diff, dict) and diff:
            span.attrs['diff_keys'] = sorted(str(k) for k in diff)
        self._finish(span, 'error' if error else 'ok')
        if duration is not None:
            self._emit_latency(p, source='tool_call', parent=span, duration_ms=duration)

    def _h_tool_blocked(self, p: Mapping[str, Any]) -> None:
        attrs = self._tool_attrs(p)
        for key in ('reason', 'effect', 'risk'):
            if p.get(key) is not None:
                attrs[key] = p[key]
        name = attrs.get('tool') or 'tool'
        span = self._new_span(f'tool:{name}', 'tool_call', self._parent(), attrs)
        self._finish(span, 'denied', reason=p.get('reason'))

    # ── approval ────────────────────────────────────────
    def _approval_span(self, p: Mapping[str, Any]) -> tuple[str, Span]:
        approval_id = str(p.get('id') or p.get('approval_id') or new_span_id())
        key = f'approval:{approval_id}'
        span = self._open.get(key)
        if span is None:
            attrs: dict[str, Any] = {'approval_id': approval_id}
            if p.get('tool'):
                attrs['tool'] = p.get('tool')
            for key_name in ('effect', 'risk', 'expires_at', 'args_preview'):
                if p.get(key_name) is not None:
                    value = p[key_name]
                    attrs[key_name] = (redact_dict(value) if self.redact_values
                                       else value) if isinstance(value, dict) else value
            span = self._new_span('approval', 'approval', self._parent(), attrs)
            self._open[key] = span
        return key, span

    def _h_approval_request(self, p: Mapping[str, Any]) -> None:
        self._approval_span(p)

    def _h_approval_decision(self, p: Mapping[str, Any]) -> None:
        key, span = self._approval_span(p)
        decision = str(p.get('decision') or '').lower()
        span.attrs['decision'] = decision
        for key_name in ('decided_by', 'reason', 'scope'):
            if p.get(key_name) is not None:
                span.attrs[key_name] = p[key_name]
        approved = _is_approved(decision)
        span.attrs['approved'] = approved
        self._open.pop(key, None)
        self._finish(span, 'ok' if approved else 'denied')

    def _h_approval_timeout(self, p: Mapping[str, Any]) -> None:
        key, span = self._approval_span(p)
        span.attrs['decision'] = 'timeout'
        span.attrs['approved'] = False
        span.attrs['reason'] = 'timeout'
        self._open.pop(key, None)
        self._finish(span, 'denied')

    # ── latency ─────────────────────────────────────────
    def _emit_latency(self,
                      p: Mapping[str, Any],
                      *,
                      source: str,
                      parent: Span | None,
                      duration_ms: float) -> None:
        """带时长的操作额外产出一个 latency span。

        为什么单独一个 span 而不是把耗时塞进业务 span 的 attrs：
        耗时是**横切**的度量 —— 模型耗时和工具耗时要能放在一起比。
        混在 attrs 里就只能靠脚本挖 JSON。
        """
        end = time.time()
        start = end - (duration_ms / 1000.0)
        span = Span(
            trace_id=self.trace_id,
            span_id=new_span_id(),
            parent_span_id=parent.span_id if parent is not None else None,
            name='latency',
            kind='latency',
            start=start,
            end=end,
            attrs={
                'duration_ms': duration_ms,
                'source': source,
                'operation': source,
            },
            status='ok',
        )
        self._record(span)

    # ── 直接以 span 语义发来的事件 ──────────────────────
    #
    # 为什么要兼容这一路：§4.1.6 说 trace 里应有 model_call / tool_call /
    # usage / latency / approval 等 span。有些生产者（Kernel 之外的新模块）
    # 会直接发这种「已经是 span 语义」的事件，而不是 run_started / tool_start
    # 这种生命周期事件。两种形状都收下，trace 才不会因为生产方换了写法就
    # 少一半内容。

    def _payload_attrs(self, p: Mapping[str, Any]) -> dict[str, Any]:
        attrs = dict(p)
        return redact_dict(attrs) if self.redact_values else attrs

    def _h_model_call(self, p: Mapping[str, Any]) -> None:
        span = self._new_span('model_call', 'model_call', self._parent(),
                               self._payload_attrs(p))
        duration = _duration_ms(p)
        if duration is not None:
            span.attrs['duration_ms'] = duration
        self._finish(span, 'ok')
        if duration is not None:
            self._emit_latency(p, source='model_call', parent=span,
                               duration_ms=duration)

    def _h_tool_call(self, p: Mapping[str, Any]) -> None:
        attrs = self._payload_attrs(p)
        name = attrs.get('tool') or attrs.get('name') or 'tool'
        span = self._new_span(f'tool:{name}', 'tool_call', self._parent(), attrs)
        duration = _duration_ms(p)
        if duration is not None:
            span.attrs['duration_ms'] = duration
        self._finish(span, 'error' if attrs.get('error') else 'ok')
        if duration is not None:
            self._emit_latency(p, source='tool_call', parent=span,
                               duration_ms=duration)

    def _h_approval(self, p: Mapping[str, Any]) -> None:
        attrs = self._payload_attrs(p)
        decision = str(attrs.get('decision') or '').lower()
        approved = _is_approved(decision) if decision else True
        span = self._new_span('approval', 'approval', self._parent(), attrs)
        self._finish(span, 'ok' if approved else 'denied')

    def _h_latency(self, p: Mapping[str, Any]) -> None:
        attrs = self._payload_attrs(p)
        duration = _duration_ms(p)
        if duration is not None:
            attrs['duration_ms'] = duration
        span = self._new_span('latency', 'latency', self._parent(), attrs)
        self._finish(span, 'ok')

    def _h_generic_span(self, kind: str, p: Mapping[str, Any]) -> None:
        """context_build / memory 等其它 kind 的 span：照收，不丢。"""
        attrs = self._payload_attrs(p)
        span = self._new_span(kind, kind, self._parent(), attrs)
        self._finish(span, 'ok')

    # ── audit ───────────────────────────────────────────
    def _h_audit(self, kind: str, p: Mapping[str, Any]) -> None:
        attrs = dict(p)
        if self.redact_values:
            attrs = redact_dict(attrs)
        span = self._new_span(kind, 'audit', self._parent(), attrs)
        self._finish(span, 'ok')

    # ── 对外 ────────────────────────────────────────────
    def span(self, name: str, *, kind: str = 'run',
             parent_span_id: str | None = None,
             **attrs: Any) -> SpanHandle:
        """手动开一个 span（句柄结束时会 emit('span_end')，本收集器会收下）。"""
        return start_span(self, name, kind=kind, parent_span_id=parent_span_id,
                          trace_id=self.trace_id, **attrs)

    def add_span(self, span: Span) -> None:
        """直接收下一个 span 对象（不走事件）。"""
        if self.redact_values:
            span.attrs.clear()
            span.attrs.update(redact_dict(span.attrs))
        self._record(span)

    def spans(self) -> list[Span]:
        return sorted(self._spans.values(), key=lambda s: s.start)

    def records(self) -> list[dict[str, Any]]:
        return list(self._records)

    def kinds(self) -> set[str]:
        return {span.kind for span in self._spans.values()}

    def close(self, status: str = 'ok') -> None:
        """收掉所有还开着的 span（run 结束时调用）。

        没关的 span 是**信息丢失**：它既没有 end 也没有 status，trace 里
        看起来像「还在跑」。宁可标成 incomplete。
        """
        for key in list(self._open):
            span = self._open.pop(key)
            self._finish(span, status, incomplete=True)

    def export(self, path: str | Path) -> int:
        """把 trace 写成 JSONL，返回行数。"""
        self.close()
        return write_jsonl(path, self._records)


#: 别名 —— 「扇出」是策划案的原话，两个名字都有人用
TraceFanout = TraceCollector
TraceBuilder = TraceCollector

#: 直接以 span 语义发来的事件 kind → 处理方法
_SPAN_EVENT_HANDLERS = {
    'model_call': TraceCollector._h_model_call,
    'tool_call': TraceCollector._h_tool_call,
    'approval': TraceCollector._h_approval,
    'latency': TraceCollector._h_latency,
}

#: 其它「已经是 span」的事件 kind（context_build / memory …）
_SPAN_EVENT_KINDS = frozenset(
    set(_SPAN_EVENT_HANDLERS) | {'context_build', 'memory'})

#: 事件 kind → 处理方法
_HANDLERS = {
    'run_started': TraceCollector._h_run_started,
    'run_finished': TraceCollector._h_run_finished,
    'run_failed': TraceCollector._h_run_failed,
    'turn_start': TraceCollector._h_turn_start,
    'turn_end': TraceCollector._h_turn_end,
    'thinking_end': TraceCollector._h_thinking_end,
    'text_end': TraceCollector._h_text_end,
    'usage': TraceCollector._h_usage,
    'tool_start': TraceCollector._h_tool_start,
    'tool_end': TraceCollector._h_tool_end,
    'tool_blocked': TraceCollector._h_tool_blocked,
    'approval_request': TraceCollector._h_approval_request,
    'approval_decision': TraceCollector._h_approval_decision,
    'approval_timeout': TraceCollector._h_approval_timeout,
}


def build_trace(events: Iterable[tuple[str, Mapping[str, Any]]],
                *,
                trace_id: str | None = None,
                **kwargs: Any) -> TraceCollector:
    """把一串事件直接变成一个 trace（便捷函数）。"""
    collector = TraceCollector(trace_id=trace_id, **kwargs)
    for kind, payload in events:
        collector.emit(kind, dict(payload or {}))
    collector.close()
    return collector


def export_events(events: Iterable[tuple[str, Mapping[str, Any]]],
                  path: str | Path,
                  *,
                  trace_id: str | None = None,
                  **kwargs: Any) -> int:
    """一次 run 产出一个 trace.jsonl 文件。

    这是 R5 验收标准 3 的最短路径：喂一串事件，拿到一个文件。
    返回写出的行数。
    """
    collector = build_trace(events, trace_id=trace_id, **kwargs)
    return collector.export(path)
