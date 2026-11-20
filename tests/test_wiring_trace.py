# Wiring W1: a run must leave a real span trail, not only the trimmed eval
# payload. The telemetry fan-out feeds both the eval event stream and the
# infra TraceCollector; disk writes go through TraceExporter (redact on).

import json
from pathlib import Path

from aicf.harness.cli.main import main as cli_main


def test_run_writes_a_span_sidecar(tmp_path: Path):
    trace_path = tmp_path / 't.jsonl'
    code = cli_main(['run', 'span wiring check', '--trace', str(trace_path),
                     '--db', str(tmp_path / 'db.sqlite')])
    assert code == 0
    spans_path = trace_path.with_suffix('.spans.jsonl')
    assert spans_path.exists(), 'the span collector produced nothing'
    spans = [json.loads(line) for line in
             spans_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    assert len(spans) > 0
    assert all('type' in span or 'kind' in span or 'name' in span for span in spans)


def test_dataset_run_writes_spans_per_case(tmp_path: Path):
    trace_dir = tmp_path / 'traces'
    code = cli_main(['run', '--dataset', 'offline', '--trace-dir', str(trace_dir),
                     '--db', str(tmp_path / 'db.sqlite')])
    assert code == 0
    sidecar = trace_dir / 'offline_pipeline_replies.spans.jsonl'
    assert sidecar.exists()
    raw = sidecar.read_text(encoding='utf-8').strip()
    assert raw  # the case produced at least one span


def test_eval_contract_survives_the_exporter(tmp_path: Path):
    from aicf.infra.eval.trace_store import read_trace_jsonl

    trace_path = tmp_path / 't.jsonl'
    code = cli_main(['run', 'readback check', '--trace', str(trace_path),
                     '--db', str(tmp_path / 'db.sqlite')])
    assert code == 0
    traces = read_trace_jsonl(trace_path)
    assert len(traces) == 1
    assert traces[0].total_tokens > 0


def test_exporter_redacts_secret_shaped_values(tmp_path: Path):
    from aicf.harness.telemetry.exporter import TraceExporter

    path = tmp_path / 'redacted.jsonl'
    with TraceExporter(path) as exporter:
        exporter.write({'tool': 'web.fetch', 'args': {'api_key': 'sk-super-secret',
                                                     'url': 'http://example.com'}})
    line = json.loads(path.read_text(encoding='utf-8').strip())
    assert 'sk-super-secret' not in json.dumps(line)
    assert line['args']['url'] == 'http://example.com'
