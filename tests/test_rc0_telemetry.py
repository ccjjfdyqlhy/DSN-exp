# R5 遥测标准化的契约测试（策划案 §4.1.6 / §4.4.7 / §7.1 R5）。
#
# 这一层钉死三件事：
#   1. **向后兼容**：既有事件 kind 一个不改；trace_id / span_id / seq 三个
#      字段全部可选；旧生产者不带它们时消费方必须容忍。
#   2. **事件扇出成 trace**：一次 run 的 trace 覆盖 model_call / tool_call /
#      usage / latency / approval 五类 span，并产出一个 JSONL 文件。
#   3. **审计不可被业务删除**：审计与业务事件同流，但独立存储。
#
# 为什么单独一个文件：test_rc0_contracts.py 测的是**契约形状**，
# 这里测的是**行为**（扇出、脱敏、留存）。

from __future__ import annotations

import json

import pytest


# ── 工具：一段能覆盖五类 span 的事件流 ────────────────────
def sample_events() -> list[tuple[str, dict]]:
    """一次典型 run 的事件流（**故意不带** trace_id/span_id/seq）。

    这是 v1 生产者的形状：老代码路径不会盖这三个章，消费方必须照样能
    把它扇出成 trace —— 否则「加字段」这个动作就变成了破坏性变更。
    """
    return [
        ('run_started', {'run_id': 'run-1', 'session_id': 'sess-1'}),
        ('turn_start', {'turn': 1, 'text': 'hello'}),
        ('thinking_end', {'text': 'hmm', 'duration': 0.4}),
        ('text_end', {'text': 'hi', 'duration': 0.2}),
        ('usage', {'input_tokens': 120, 'output_tokens': 30,
                   'cached_input_tokens': 100, 'cache_hit_rate': 0.83,
                   'provider': 'openai', 'model': 'gpt-x', 'latency_ms': 600}),
        ('tool_start', {'turn': 1, 'call_id': 'c1', 'name': 'shell',
                        'display': 'shell', 'args': {'cmd': 'ls'}}),
        ('tool_end', {'turn': 1, 'call_id': 'c1', 'name': 'shell',
                      'output': 'a\nb', 'duration': 0.05, 'error': None}),
        ('approval_request', {'id': 'ap-1', 'tool': 'shell',
                               'effect': 'effectful', 'risk': 'high'}),
        ('approval_decision', {'id': 'ap-1', 'tool': 'shell',
                                'decision': 'approve', 'decided_by': 'human'}),
        ('run_finished', {'run_id': 'run-1', 'session_id': 'sess-1',
                          'status': 'done'}),
    ]


def feed(collector, events) -> None:
    for kind, payload in events:
        collector.emit(kind, payload)


# ── 1. 向后兼容 ─────────────────────────────────────────
def test_existing_event_kinds_are_untouched():
    """既有 kind 一个都不能少 —— 改词表就是改公共 API。"""
    from harness.agent.events import EVENT_KINDS
    for kind in ('turn_start', 'status', 'thinking_delta', 'thinking_end',
                 'text_delta', 'text_end', 'tool_start', 'tool_output',
                 'tool_end', 'usage', 'notice', 'error', 'interrupted',
                 'diff_added', 'queued', 'turn_end', 'compaction_start',
                 'compaction_delta', 'compaction_end', 'aside_start',
                 'aside_delta', 'aside_end', 'agent_event', 'agents_refresh',
                 'session_loaded', 'session_cleared', 'session_rewound',
                 'model_changed', 'tools_refreshed'):
        assert kind in EVENT_KINDS, kind


def test_trace_fields_are_exactly_three_optional_ones():
    from harness.agent.events import TRACE_FIELDS
    assert TRACE_FIELDS == ('trace_id', 'span_id', 'seq')


def test_consumer_tolerates_events_without_trace_fields():
    """旧生产者不带 trace_id/span_id/seq 时，消费方不能报错。"""
    from infra.observability.trace import TraceCollector
    collector = TraceCollector()
    feed(collector, sample_events())
    assert collector._errors == []
    assert collector.spans()


def test_stamp_adds_optional_fields_without_overwriting():
    """盖章只补缺失的：已经盖好的章不能被后来者覆盖。"""
    from harness.telemetry.span import stamp
    stamped = stamp({'trace_id': 'keep-me', 'x': 1}, trace_id='other', seq=7)
    assert stamped['trace_id'] == 'keep-me'
    assert stamped['seq'] == 7
    assert stamped['x'] == 1


def test_stamp_without_context_adds_nothing():
    """没有上下文时不能补空串 —— 空串会被下游当成「有 id 但 id 是空的」。"""
    from harness.telemetry.span import stamp
    stamped = stamp({'x': 1})
    assert 'trace_id' not in stamped
    assert 'span_id' not in stamped
    assert 'seq' not in stamped


def test_trace_scope_sets_and_restores_context():
    from harness.telemetry.base import current_span_id, current_trace_id
    from harness.telemetry.span import trace_scope
    with trace_scope('t-1', 's-1') as ctx:
        assert ctx.trace_id == 't-1'
        assert current_trace_id.get() == 't-1'
        assert current_span_id.get() == 's-1'
    assert current_trace_id.get() == ''
    assert current_span_id.get() == ''


def test_trace_scope_restores_on_exception():
    """异常路径也必须恢复上下文，否则会污染下一个任务。"""
    from harness.telemetry.base import current_trace_id
    from harness.telemetry.span import trace_scope
    with pytest.raises(RuntimeError):
        with trace_scope('t-1', 's-1'):
            raise RuntimeError('boom')
    assert current_trace_id.get() == ''


def test_span_scope_nests_parent_ids():
    from harness.telemetry.base import current_span_id
    from harness.telemetry.span import span_scope, start_span

    class Collector:
        def emit(self, kind, payload):
            pass

    with span_scope(start_span(Collector(), 'outer')) as outer:
        assert current_span_id.get() == outer.span_id
        with span_scope(start_span(Collector(), 'inner')) as inner:
            assert inner.parent_span_id == outer.span_id


# ── 2. 事件扇出成 span ──────────────────────────────────
def test_trace_covers_the_five_required_span_kinds():
    """R5 验收：model_call / tool_call / usage / latency / approval 五类。"""
    from infra.observability.trace import SPAN_KINDS, TraceCollector
    collector = TraceCollector()
    feed(collector, sample_events())
    kinds = collector.kinds()
    for kind in SPAN_KINDS:
        assert kind in kinds, f'缺少 {kind} span（实际 {sorted(kinds)}）'


def test_trace_spans_share_one_trace_id():
    from infra.observability.trace import TraceCollector
    collector = TraceCollector()
    feed(collector, sample_events())
    spans = collector.spans()
    assert spans
    assert {s.trace_id for s in spans} == {collector.trace_id}


def test_tool_call_span_carries_tool_and_duration():
    from infra.observability.trace import TraceCollector
    collector = TraceCollector()
    feed(collector, sample_events())
    tools = [s for s in collector.spans() if s.kind == 'tool_call']
    assert len(tools) == 1
    assert tools[0].attrs['tool'] == 'shell'
    assert tools[0].attrs['duration_ms'] == pytest.approx(50.0)


def test_approval_span_records_decision():
    from infra.observability.trace import TraceCollector
    collector = TraceCollector()
    feed(collector, sample_events())
    approvals = [s for s in collector.spans() if s.kind == 'approval']
    assert len(approvals) == 1
    assert approvals[0].attrs['decision'] == 'approve'
    assert approvals[0].attrs['approved'] is True
    assert approvals[0].status == 'ok'


def test_approval_denied_is_marked_denied():
    from infra.observability.trace import TraceCollector
    collector = TraceCollector()
    collector.emit('approval_request', {'id': 'ap-1', 'tool': 'shell'})
    collector.emit('approval_decision', {'id': 'ap-1', 'tool': 'shell',
                                         'decision': 'deny'})
    approvals = [s for s in collector.spans() if s.kind == 'approval']
    assert approvals and approvals[0].status == 'denied'


def test_approval_timeout_is_denied_not_approved():
    """审批超时 = 拒绝（fail-closed）。当成同意就是安全事故。"""
    from infra.observability.trace import TraceCollector
    collector = TraceCollector()
    collector.emit('approval_request', {'id': 'ap-1', 'tool': 'shell'})
    collector.emit('approval_timeout', {'id': 'ap-1', 'tool': 'shell'})
    approvals = [s for s in collector.spans() if s.kind == 'approval']
    assert approvals and approvals[0].status == 'denied'
    assert approvals[0].attrs['decision'] == 'timeout'


def test_usage_span_keeps_token_metrics():
    from infra.observability.trace import TraceCollector
    collector = TraceCollector()
    feed(collector, sample_events())
    usages = [s for s in collector.spans() if s.kind == 'usage']
    assert len(usages) == 1
    assert usages[0].attrs['input_tokens'] == 120
    assert usages[0].attrs['cache_hit_rate'] == pytest.approx(0.83)


def test_latency_span_carries_milliseconds():
    """耗时统一归一成毫秒：harness 的 duration 是秒，混用会让 trace 全错。"""
    from infra.observability.trace import TraceCollector
    collector = TraceCollector()
    feed(collector, sample_events())
    latencies = [s for s in collector.spans() if s.kind == 'latency']
    assert latencies
    assert all('duration_ms' in s.attrs for s in latencies)
    assert max(s.attrs['duration_ms'] for s in latencies) == pytest.approx(600.0)


def test_events_with_seq_are_deduplicated():
    """重复投递（journal 重放）按 seq 去重，不然会重复计费。"""
    from infra.observability.trace import TraceCollector
    collector = TraceCollector()
    collector.emit('usage', {'seq': 1, 'input_tokens': 10})
    collector.emit('usage', {'seq': 1, 'input_tokens': 10})
    assert len([s for s in collector.spans() if s.kind == 'usage']) == 1


def test_unknown_event_kind_is_ignored_not_fatal():
    """事件词表会继续长：不认识的事件不能把 trace 采集器搞崩。"""
    from infra.observability.trace import TraceCollector
    collector = TraceCollector()
    collector.emit('some_future_kind', {'whatever': 1})
    assert collector._errors == []


def test_span_handle_events_are_ingested():
    """harness.telemetry.base.SpanHandle 发出的 span_end 要能被收下。"""
    from infra.observability.trace import TraceCollector
    from harness.telemetry.span import start_span
    collector = TraceCollector()
    with start_span(collector, 'manual', kind='model_call'):
        pass
    spans = collector.spans()
    assert len(spans) == 1
    assert spans[0].name == 'manual'
    assert spans[0].end is not None


def test_build_trace_helper():
    from infra.observability.trace import build_trace
    collector = build_trace(sample_events())
    assert collector.spans()
    assert collector._errors == []


# ── 3. JSONL 导出 ───────────────────────────────────────
def test_run_produces_one_jsonl_trace_file(tmp_path):
    from infra.observability.trace import TraceCollector
    path = tmp_path / 'trace.jsonl'
    collector = TraceCollector(run_id='run-1')
    feed(collector, sample_events())
    written = collector.export(path)
    assert path.exists()
    assert written == len(collector.records())
    lines = path.read_text(encoding='utf-8').strip().split('\n')
    assert len(lines) == written
    records = [json.loads(line) for line in lines]
    assert all(r['type'] == 'span' for r in records)
    assert {r['trace_id'] for r in records} == {collector.trace_id}
    assert {r['kind'] for r in records} >= {'model_call', 'tool_call',
                                            'usage', 'latency', 'approval'}


def test_jsonl_roundtrip_and_bad_lines_are_skipped(tmp_path):
    from harness.telemetry.exporter import read_jsonl, write_jsonl
    path = tmp_path / 'x.jsonl'
    write_jsonl(path, [{'a': 1}, {'b': '值'}])
    with open(path, 'a', encoding='utf-8') as fh:
        fh.write('{坏行\n')
    records = read_jsonl(path)
    assert records == [{'a': 1}, {'b': '值'}]


def test_trace_exporter_writes_jsonl(tmp_path):
    from harness.telemetry.exporter import TraceExporter
    path = tmp_path / 'trace.jsonl'
    with TraceExporter(path) as exporter:
        exporter.write_event('usage', {'input_tokens': 5})
        exporter.write({'type': 'span', 'kind': 'usage'})
    lines = path.read_text(encoding='utf-8').strip().split('\n')
    assert len(lines) == 2
    assert json.loads(lines[0])['kind'] == 'usage'


# ── 4. 统一脱敏 ─────────────────────────────────────────
def test_redact_replaces_sensitive_values():
    from harness.telemetry.exporter import redact
    out = redact({'user': 'bob', 'password': 'hunter2',
                  'nested': {'api_key': 'k-1'}, 'list': [{'token': 't'}]})
    assert out['user'] == 'bob'
    assert out['password'] == '***'
    assert out['nested']['api_key'] == '***'
    assert out['list'][0]['token'] == '***'


def test_redact_does_not_mutate_input():
    from harness.telemetry.exporter import redact
    source = {'password': 'hunter2'}
    redact(source)
    assert source['password'] == 'hunter2'


def test_redact_hides_credential_shaped_values():
    from harness.telemetry.exporter import redact
    assert redact('sk-abcdef123456') == '***'
    assert redact('hello world') == 'hello world'


def test_redact_is_the_single_implementation():
    """审计与 trace 导出必须用**同一个** redact —— 分散实现必然漏改一处。"""
    from harness.telemetry.exporter import redact as exporter_redact
    from infra.observability.audit import redact as audit_redact
    assert audit_redact is exporter_redact


def test_trace_export_redacts_tool_args(tmp_path):
    """工具参数可能带密钥，落盘前必须脱敏。"""
    from infra.observability.trace import TraceCollector
    path = tmp_path / 'trace.jsonl'
    collector = TraceCollector()
    collector.emit('tool_start', {'call_id': 'c1', 'name': 'http',
                                  'args': {'url': 'x', 'api_key': 'sk-secret'}})
    collector.emit('tool_end', {'call_id': 'c1', 'name': 'http',
                                'output': 'ok', 'duration': 0.01})
    collector.export(path)
    text = path.read_text(encoding='utf-8')
    assert 'sk-secret' not in text
    assert '***' in text


def test_args_digest_keeps_only_hash_and_length():
    """args_digest 只存哈希与长度 —— 不放明文。"""
    from infra.observability.audit import args_digest
    digest = args_digest({'cmd': 'rm -rf /', 'password': 'hunter2'})
    text = json.dumps(digest)
    assert 'hunter2' not in text
    assert 'rm -rf' not in text
    assert set(digest) == {'sha256', 'length'}
    assert len(digest['sha256']) == 64
    assert digest['length'] > 0


def test_args_digest_is_stable_across_key_order():
    """键序不同的同一组参数必须算出同一个摘要，否则没法比对两次调用。"""
    from infra.observability.audit import args_digest
    assert (args_digest({'a': 1, 'b': 2})['sha256']
            == args_digest({'b': 2, 'a': 1})['sha256'])


def test_args_digest_differs_for_different_args():
    from infra.observability.audit import args_digest
    assert args_digest({'a': 1})['sha256'] != args_digest({'a': 2})['sha256']


# ── 5. 审计 ─────────────────────────────────────────────
def test_audit_event_vocabulary():
    from infra.observability.audit import AUDIT_KINDS
    assert AUDIT_KINDS == ('audit.tool_call', 'audit.denied',
                           'audit.secret_access', 'audit.delegation')


def test_audit_tool_call_has_the_agreed_fields():
    from infra.observability.audit import AuditLog
    log = AuditLog()
    record = log.tool_call(identity='agent:1', tool='shell', version='3',
                           args={'cmd': 'ls', 'password': 'x'},
                           effect='effectful', sandbox='isolated',
                           decision='approve', duration=0.2, outcome='ok')
    payload = record.payload
    for field in ('identity', 'tool', 'version', 'args_digest', 'effect',
                  'sandbox', 'decision', 'duration', 'outcome'):
        assert field in payload, field
    assert 'password' not in json.dumps(payload)
    assert payload['args_digest']['sha256']


def test_audit_denied_records_reason():
    from infra.observability.audit import DENY_REASONS, AuditLog
    log = AuditLog()
    for reason in DENY_REASONS:
        record = log.denied(reason, tool='shell')
        assert record.kind == 'audit.denied'
        assert record.payload['reason'] == reason


def test_audit_secret_access_and_delegation():
    from infra.observability.audit import AuditLog
    log = AuditLog()
    secret = log.secret_access('vault://prod/db', tool='http')
    assert secret.payload['credential_ref'] == 'vault://prod/db'
    assert secret.payload['tool'] == 'http'
    delegation = log.delegation('agent:root', 'agent:worker', ['fs.read'])
    assert delegation.payload['from'] == 'agent:root'
    assert delegation.payload['to'] == 'agent:worker'
    assert delegation.payload['scopes'] == ['fs.read']


def test_audit_flows_in_the_same_stream_as_business_events():
    """审计与业务事件**同流**：trace 里能看到审计发生过。"""
    from infra.observability.audit import AuditLog
    from infra.observability.trace import TraceCollector
    collector = TraceCollector()
    log = AuditLog(telemetry=collector)
    log.tool_call(identity='agent:1', tool='shell', args={'cmd': 'ls'},
                  decision='approve', outcome='ok')
    audits = [s for s in collector.spans() if s.kind == 'audit']
    assert len(audits) == 1
    assert audits[0].name == 'audit.tool_call'


def test_audit_is_stored_independently_of_business_events():
    """独立存储：清掉 trace 不影响审计。"""
    from infra.observability.audit import AuditLog
    from infra.observability.trace import TraceCollector
    collector = TraceCollector()
    log = AuditLog(telemetry=collector)
    log.denied('policy', tool='shell')
    assert len(log) == 1
    collector.close()
    assert len(log) == 1  # 业务侧收摊，审计还在


def test_audit_cannot_be_deleted_by_business_code():
    """审计可被业务删除 = 没有审计。"""
    from infra.observability.audit import AuditImmutableError, AuditLog
    log = AuditLog()
    log.denied('policy')
    with pytest.raises(AuditImmutableError):
        log.clear()


def test_audit_store_has_no_delete_api():
    """存储层干脆不提供删除入口 —— 想删也删不掉。"""
    from infra.observability.audit import AuditStore
    store = AuditStore()
    for forbidden in ('delete', 'remove', 'clear', 'truncate', 'pop'):
        assert not hasattr(store, forbidden), forbidden


def test_audit_purge_requires_positive_retention():
    """唯一的删除路径必须显式给出正留存时长。"""
    from infra.observability.audit import AuditStore
    store = AuditStore()
    with pytest.raises(ValueError):
        store.purge_expired(retention_seconds=0)


def test_audit_records_are_serialisable():
    from infra.observability.audit import AuditLog
    log = AuditLog()
    log.secret_access('vault://x', tool='http')
    data = log.records()[0].to_dict()
    assert json.loads(json.dumps(data))['kind'] == 'audit.secret_access'


def test_audit_export_writes_its_own_file(tmp_path):
    """独立存储的落盘形态：审计文件与业务 trace 文件分开。"""
    from infra.observability.audit import AuditLog
    path = tmp_path / 'audit.jsonl'
    log = AuditLog()
    log.denied('sandbox', tool='shell')
    log.export(path)
    records = [json.loads(line)
               for line in path.read_text(encoding='utf-8').strip().split('\n')]
    assert len(records) == 1
    assert records[0]['kind'] == 'audit.denied'


def test_audit_rejects_non_audit_kinds():
    from infra.observability.audit import AuditLog
    log = AuditLog()
    with pytest.raises(ValueError):
        log.record('tool_start', {})


# ── 6. 追溯性与收尾 ─────────────────────────────────────
def test_producer_seq_is_kept_in_span_attrs():
    """trace 要能对回事件流：生产方的 seq 记进 span attrs。"""
    from infra.observability.trace import TraceCollector
    collector = TraceCollector()
    collector.emit('usage', {'seq': 7, 'input_tokens': 1})
    usage = [s for s in collector.spans() if s.kind == 'usage'][0]
    assert usage.attrs['event_seq'] == 7


def test_trace_record_seqs_are_unique():
    """trace 文件自己的 seq 必须唯一 —— 消费方会拿它去重。"""
    from infra.observability.trace import TraceCollector
    collector = TraceCollector()
    feed(collector, sample_events())
    seqs = [r['seq'] for r in collector.records()]
    assert len(seqs) == len(set(seqs))


def test_export_events_writes_one_file(tmp_path):
    """一次 run → 一个 trace.jsonl（最短路径）。"""
    from infra.observability.trace import export_events
    path = tmp_path / 'trace.jsonl'
    written = export_events(sample_events(), path)
    assert written > 0
    assert path.exists()


def test_add_span_records_a_span_directly():
    from harness.telemetry.base import Span, new_trace_id
    from infra.observability.trace import TraceCollector
    collector = TraceCollector()
    collector.add_span(Span(trace_id=new_trace_id(), span_id='s1',
                            name='manual', kind='tool_call'))
    assert [s.name for s in collector.spans()] == ['manual']


def test_unfinished_run_span_is_marked_incomplete():
    """没收尾的 span 要标出来 —— 否则 trace 里看起来像「还在跑」。"""
    from infra.observability.trace import TraceCollector
    collector = TraceCollector()
    collector.emit('run_started', {'run_id': 'r'})
    collector.close()
    root = [s for s in collector.spans() if s.name == 'run'][0]
    assert root.attrs['incomplete'] is True
    assert root.end is not None


def test_audit_inherits_current_trace_context():
    """审计默认挂在当前 trace 上 —— 审计要能回答「属于哪次运行」。"""
    from infra.observability.audit import AuditLog
    from harness.telemetry.span import trace_scope
    log = AuditLog()
    with trace_scope('t-9', 's-9'):
        record = log.denied('policy')
    assert record.trace_id == 't-9'
    assert record.span_id == 's-9'


def test_span_semantics_events_are_accepted():
    """生产方直接发「已经是 span 语义」的事件时也要收下。"""
    from infra.observability.trace import TraceCollector
    collector = TraceCollector()
    collector.emit('model_call', {'duration': 0.3})
    collector.emit('tool_call', {'tool': 'shell', 'duration': 0.1})
    collector.emit('usage', {'input_tokens': 1})
    collector.emit('latency', {'duration_ms': 42})
    collector.emit('approval', {'decision': 'deny'})
    assert collector._errors == []
    kinds = collector.kinds()
    for kind in ('model_call', 'tool_call', 'usage', 'latency', 'approval'):
        assert kind in kinds, kind


def test_other_span_kinds_are_not_dropped():
    """context_build / memory 也是 §4.1.6 列出的 span —— 不能丢。"""
    from infra.observability.trace import TraceCollector
    collector = TraceCollector()
    collector.emit('context_build', {'tokens': 100})
    collector.emit('memory', {'items': 3})
    assert 'context_build' in collector.kinds()
    assert 'memory' in collector.kinds()


# ── 7. 依赖方向：共享原语只有一份定义 ───────────────────
def test_harness_telemetry_is_a_thin_shell_over_infra():
    """harness/telemetry 是 infra 的再导出薄壳。

    两边各写一份 Span / redact 就会**静默分叉** —— 一处改了另一处没改，
    运行时才炸。所以这里把「同一个对象」钉死。
    """
    import harness.telemetry as ht
    from infra.observability import span as iso
    # 注意：模块名 redact 与函数名 redact 同名，import 时必须从模块里取，
    # 否则 `import infra.observability.redact as x` 拿到的是函数（同名遮蔽）。
    from infra.observability.redact import (redact as infra_redact,
                                            redact_dict as infra_redact_dict,
                                            write_jsonl as infra_write_jsonl,
                                            read_jsonl as infra_read_jsonl)
    assert ht.Span is iso.Span
    assert ht.SpanHandle is iso.SpanHandle
    assert ht.SpanKind is iso.SpanKind
    assert ht.new_trace_id is iso.new_trace_id
    assert ht.new_span_id is iso.new_span_id
    assert ht.current_trace_id is iso.current_trace_id
    assert ht.current_span_id is iso.current_span_id
    assert ht.TraceContext is iso.TraceContext
    assert ht.SeqCounter is iso.SeqCounter
    assert ht.redact is infra_redact
    assert ht.redact_dict is infra_redact_dict
    assert ht.write_jsonl is infra_write_jsonl
    assert ht.read_jsonl is infra_read_jsonl


def test_audit_redact_is_the_same_object_as_the_infra_one():
    from infra.observability.audit import redact as audit_redact
    from infra.observability.redact import redact as infra_redact
    assert audit_redact is infra_redact


def test_telemetry_port_protocol_stays_in_the_kernel():
    """TelemetryPort 是内核对外的契约 —— 定义必须留在 harness 侧。"""
    import harness.telemetry.base as htb
    from harness.telemetry import TelemetryPort
    assert TelemetryPort is htb.TelemetryPort
    assert 'class TelemetryPort' in open(htb.__file__, encoding='utf-8').read()


def test_infra_does_not_import_harness():
    """infra 不得依赖 harness（依赖方向守卫的迷你版，见 test_rc0_dependency_direction.py）。"""
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    for path in sorted((root / 'infra').rglob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        for node in tree.body:          # 只看模块顶层
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level:
                names = [node.module or '']
            for name in names:
                assert not (name == 'harness' or name.startswith('harness.')), (
                    f'{path.relative_to(root)} 在模块级依赖了 {name}')
