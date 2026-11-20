# tests/test_rc0_cli.py
# R8：aicf 命令行。
#
# 验收标准：run → eval → gate 一条命令链跑通；`aicf --help` 可用。
# CLI 的测试要**离线**跑通 —— 不依赖任何 API key。

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aicf.harness.cli.main import main


def _run(argv, capsys):
    code = main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_help_exits_cleanly(capsys):
    code, out, _err = _run(['--help'], capsys)
    assert code == 0
    assert 'run' in out and 'eval' in out and 'gate' in out


def test_version_prints_the_package_version(capsys):
    import aicf.harness
    code, out, _err = _run(['--version'], capsys)
    assert code == 0
    assert aicf.harness.__version__ in out


def test_tool_list_shows_the_catalog(capsys):
    """工具目录要能看到副作用等级与沙箱档位 —— 这是控制面与评测的输入。"""
    code, out, _err = _run(['tool', 'list'], capsys)
    assert code == 0
    assert 'file.read' in out
    assert 'effect' in out and 'sandbox' in out


def test_tool_list_json(capsys):
    code, out, _err = _run(['tool', 'list', '--json'], capsys)
    assert code == 0
    rows = json.loads(out)
    assert isinstance(rows, list) and rows
    names = {row['name'] for row in rows}
    assert 'file.read' in names
    read = next(row for row in rows if row['name'] == 'file.read')
    assert read['effect'] == 'pure'


def test_tool_exec_runs_a_read_only_tool(tmp_path, capsys):
    target = tmp_path / 'hello.txt'
    target.write_text('hello', encoding='utf-8')
    code, out, _err = _run(
        ['tool', 'exec', 'file.read', '--args',
         json.dumps({'path': str(target)}), '--json'], capsys)
    assert code == 0
    payload = json.loads(out)
    assert payload['success'] is True
    assert 'hello' in payload['output'].get('content', '')


def test_tool_exec_blocks_an_effectful_tool_without_yes(capsys):
    """effectful 工具没有 --yes 必须被审批挡住 —— 这就是安全默认。"""
    code, _out, err = _run(
        ['tool', 'exec', 'proc.run', '--args',
         json.dumps({'command': 'echo hi'}), '--policy', 'strict'], capsys)
    assert code == 1
    assert 'proc.run' in err


def test_tool_exec_allows_with_yes(capsys):
    code, out, _err = _run(
        ['tool', 'exec', 'proc.run', '--args',
         json.dumps({'command': 'echo hi'}), '--policy', 'strict', '--yes'],
        capsys)
    assert code == 0
    assert 'hi' in out


def test_tool_exec_respects_an_explicit_deny(capsys):
    code, out, err = _run(
        ['tool', 'exec', 'file.read', '--args', json.dumps({'path': '/etc/hosts'}),
         '--deny', 'file.read', '--json'], capsys)
    assert code == 1
    # --json 时结构化结果走 stdout；错误文本在 payload 的 error 里。
    payload = json.loads(out)
    assert payload['success'] is False
    assert 'file.read' in payload['error']
    assert 'policy' in payload['error']


def test_tool_exec_rejects_bad_json(capsys):
    code, _out, err = _run(
        ['tool', 'exec', 'file.read', '--args', 'not json'], capsys)
    assert code == 2
    assert 'JSON' in err


def test_tool_exec_unknown_tool(capsys):
    code, _out, err = _run(['tool', 'exec', 'no.such.tool'], capsys)
    assert code == 2
    assert 'no.such.tool' in err


def test_run_produces_a_trace(tmp_path, capsys):
    trace = tmp_path / 'trace.jsonl'
    code, out, _err = _run(
        ['run', '你好', '--trace', str(trace), '--case-id', 'demo'], capsys)
    assert code == 0
    assert trace.exists()
    payload = json.loads(trace.read_text(encoding='utf-8').splitlines()[0])
    assert payload['case_id'] == 'demo'
    assert payload['input'] == '你好'
    assert payload['output']
    assert 'trace' in out


def test_run_to_eval_to_gate_chain(tmp_path, capsys):
    """一条命令链跑通：run → eval → gate。"""
    trace = tmp_path / 'trace.jsonl'
    run_json = tmp_path / 'run.json'
    gate_json = tmp_path / 'gate.json'
    dataset = (Path(__file__).resolve().parent.parent / 'aicf' / 'harness' / 'datasets'
               / 'basic.yaml')
    assert dataset.exists(), 'aicf/harness/datasets/basic.yaml 必须存在'

    code, _out, _err = _run(
        ['run', '你好', '--trace', str(trace), '--case-id', 'demo'], capsys)
    assert code == 0

    code, out, _err = _run(
        ['eval', '--dataset', str(dataset), '--traces', str(trace),
         '--out', str(run_json)], capsys)
    assert code in (0, 1)          # 只有 1 个 case 有 trace，整体不通过是正常的
    assert run_json.exists()
    payload = json.loads(run_json.read_text(encoding='utf-8'))
    assert payload['results']
    assert '用例' in out

    code, out, _err = _run(
        ['gate', '--run', str(run_json), '--out', str(gate_json)], capsys)
    assert code in (0, 1)
    assert gate_json.exists()
    report = json.loads(gate_json.read_text(encoding='utf-8'))
    assert report
    assert '闸门判定' in out


def test_eval_without_traces_scores_zero(tmp_path, capsys):
    dataset = (Path(__file__).resolve().parent.parent / 'aicf' / 'harness' / 'datasets'
               / 'basic.yaml')
    code, out, _err = _run(['eval', '--dataset', str(dataset)], capsys)
    assert code == 1
    assert 'missing_trace' in out


def test_eval_rejects_a_missing_dataset(capsys):
    code, _out, err = _run(['eval', '--dataset', '/nope/nope.yaml'], capsys)
    assert code == 2
    assert '数据集' in err


def test_session_list_on_an_empty_database(tmp_path, capsys):
    code, out, _err = _run(
        ['session', 'list', '--db', str(tmp_path / 'a.db')], capsys)
    assert code == 0
    assert '没有会话' in out


def test_no_subcommand_prints_help(capsys):
    code, out, _err = _run([], capsys)
    assert code == 0
    assert 'usage' in out
