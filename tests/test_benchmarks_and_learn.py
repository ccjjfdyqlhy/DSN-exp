# tests/test_benchmarks_and_learn.py
# roadmap 段 8 的验收测试：
#   - `benchmarks/run_benchmarks.py` 的每项基准可跑、口径字段存在
#   - `aicf learn` 是 harness/learning + infra/finetune 的第二个消费者
#
# 验收标准（roadmap 原文）：README 上每个数字都能被一条命令复现 ——
# 这条测试钉住「命令存在且能跑出结构正确的数字」；数值本身随机器浮动，
# 不做数值断言（口径断言写在 benchmarks/README.md）。

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO = Path(__file__).resolve().parents[1]

BENCH = None


@pytest.fixture(scope='module')
def bench():
    global BENCH
    if BENCH is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'benchmarks_runner', REPO / 'benchmarks' / 'run_benchmarks.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        BENCH = mod
    return BENCH


@pytest.fixture(autouse=True)
def _in_tmp(tmp_path):
    old = Path.cwd()
    os.chdir(tmp_path)
    yield
    os.chdir(old)


# ── 基准可跑（缩小规模，数值不断言）──────────────────────────

def test_tool_call_latency_benchmark(bench):
    result = bench.bench_tool_call_latency(n=20)
    assert result['metric'] == 'tool_call_latency_us'
    assert result['n'] == 20
    assert result['p50_us'] > 0 and result['p95_us'] >= result['p50_us']
    assert '口径' in result


def test_journal_recovery_benchmark(bench):
    result = bench.bench_journal_recovery(events=20)
    assert result['metric'] == 'journal_recovery_ms'
    assert result['events'] == 20
    assert result['recovery_ms'] >= 0
    assert result['replayed_events'] >= 20


def test_memory_compaction_benchmark(bench):
    result = bench.bench_memory_compaction(entries=10)
    assert result['metric'] == 'memory_compaction_ratio'
    assert result['ratio'] > 1.0, '压缩比 ≤ 1 等于白做 —— 口径坏了'
    assert result['compacted_chars'] < result['raw_chars']


# ── aicf learn：learning/finetune 的第二消费者 ──────────────

def _run_cli(argv):
    from aicf.harness.cli.main import main as cli_main
    return cli_main(argv)


def test_learn_turns_dataset_traces_into_sft_dataset(tmp_path, capsys):
    """run → learn：trace 变成 train/val JSONL —— 两条链路在 CLI 接通。"""
    assert _run_cli(['run', '--dataset', 'offline',
                     '--trace-dir', 'traces/']) == 0
    assert _run_cli(['learn', '--traces', 'traces/', '--out', 'sft_out']) == 0
    train = Path('sft_out/train.jsonl')
    assert train.exists()
    records = [json.loads(line) for line in
               train.read_text(encoding='utf-8').splitlines() if line.strip()]
    assert records, '训练集是空的'
    for record in records:
        roles = [m['role'] for m in record['messages']]
        assert 'user' in roles and 'assistant' in roles
        assert record['source'] == 'cli-traces'


def test_learn_rejects_when_no_usable_traces(tmp_path, capsys):
    Path('traces').mkdir()
    (Path('traces') / 'empty.jsonl').write_text('', encoding='utf-8')
    assert _run_cli(['learn', '--traces', 'traces/', '--out', 'out']) == 1
    err = capsys.readouterr().err
    assert '没有可用轨迹' in err


def test_learn_reports_missing_trace_path(tmp_path, capsys):
    assert _run_cli(['learn', '--traces', 'nope/', '--out', 'out']) == 2
    assert 'trace 读取失败' in capsys.readouterr().err
