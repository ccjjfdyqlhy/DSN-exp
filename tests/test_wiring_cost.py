# Wiring W0: the run path must carry real usage and cost into traces and the
# run record, so the cost gate judges a number instead of an empty field.
#
# The stub model reports a deterministic chars//4 usage estimate, so every
# assertion here passes offline with no API key.

import json
from pathlib import Path

from aicf.harness.cli.main import main as cli_main


def _cli(argv):
    return cli_main(argv)


def test_run_trace_carries_usage(tmp_path: Path):
    trace_path = tmp_path / 't.jsonl'
    code = _cli(['run', 'cost wiring check', '--trace', str(trace_path),
                 '--db', str(tmp_path / 'db.sqlite')])
    assert code == 0
    trace = json.loads(trace_path.read_text(encoding='utf-8').strip())
    usage = trace['usage']
    assert usage['total_tokens'] > 0
    assert usage['total_tokens'] == usage['input_tokens'] + usage['output_tokens']


def test_dataset_run_carries_usage_per_case(tmp_path: Path):
    trace_dir = tmp_path / 'traces'
    code = _cli(['run', '--dataset', 'offline', '--trace-dir', str(trace_dir),
                 '--db', str(tmp_path / 'db.sqlite')])
    assert code == 0
    raw = (trace_dir / 'offline_pipeline_replies.jsonl').read_text(encoding='utf-8').strip()
    trace = json.loads(raw)
    assert trace['usage']['total_tokens'] > 0
    assert trace['cost'] == 0.0  # stub = local pricing = free, and that is the honest number


def test_eval_run_record_has_real_cost_tokens(tmp_path: Path):
    trace_dir = tmp_path / 'traces'
    _cli(['run', '--dataset', 'offline', '--trace-dir', str(trace_dir),
          '--db', str(tmp_path / 'db.sqlite')])
    run_path = tmp_path / 'run.json'
    code = _cli(['eval', '--dataset', 'offline', '--traces', str(trace_dir),
                 '--out', str(run_path)])
    assert code == 0
    run = json.loads(run_path.read_text(encoding='utf-8'))
    assert float(run['aggregate'].get('total_cost_tokens', 0.0)) > 0


def test_evalcmd_falls_back_to_events_for_old_traces():
    from aicf.harness.cli.evalcmd import _to_trace

    payload = {
        'trace_id': 'old',
        'input': 'in',
        'output': 'out',
        'usage': {},  # old runs left this empty
        'events': [
            {'kind': 'usage', 'payload': {'input_tokens': 30, 'output_tokens': 12}},
            {'kind': 'tool_intent', 'payload': {'tool': 'file.read'}},
        ],
    }
    trace = _to_trace(payload)
    assert trace.total_tokens == 42


def test_gate_judges_cost_against_budget(tmp_path: Path):
    trace_dir = tmp_path / 'traces'
    _cli(['run', '--dataset', 'offline', '--trace-dir', str(trace_dir),
          '--db', str(tmp_path / 'db.sqlite')])
    run_path = tmp_path / 'run.json'
    _cli(['eval', '--dataset', 'offline', '--traces', str(trace_dir),
          '--out', str(run_path)])
    gate_path = tmp_path / 'gate.json'
    code = _cli(['gate', '--run', str(run_path), '--out', str(gate_path),
                 '--cost-budget', '5.0'])
    assert code == 0
    report = json.loads(gate_path.read_text(encoding='utf-8'))
    cost = next(o for o in report['outcomes'] if o['name'] == 'cost')
    assert cost['verdict'] == 'pass'  # budget given, so the gate judged instead of skipping
    assert 'total_cost' in cost['details']
