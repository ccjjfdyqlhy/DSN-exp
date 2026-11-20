# tests/test_rc1_cli_artifact.py
# `aicf artifact` 子命令的测试 —— 策划案 §5.4 的 CLI 面 / rc1 C2。
#
# 验收标准（策划案 §7.2 C2）：artifact 版本不可变；发布必须携带
# Gate 报告；可一键回滚。

from __future__ import annotations

import json
from pathlib import Path

from harness.cli.main import main

#: 仓库根（agents/ 示例文件的锚点）
ROOT = Path(__file__).resolve().parents[1]


def _gate(db_path, report_id='gate-1', verdict='pass'):
    from infra.eval.trace_store import TraceStore
    TraceStore(db_path).save_gate_report(
        {'id': report_id, 'run_version_id': 'rv_x', 'verdict': verdict,
         'created_at': 1.0})


def test_cli_help_lists_the_artifact_command(capsys):
    main(['--help'])
    out = capsys.readouterr().out
    assert 'artifact' in out


def test_cli_validate_reports_the_hash(tmp_path, capsys):
    root = ROOT
    code = main(['artifact', 'validate', str(root / 'agents' / 'research.yaml'),
                 '--json'])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['name'] == 'research-assistant'
    assert payload['valid'] is True
    assert len(payload['content_hash']) == 64


def test_cli_publish_requires_the_gate_flag(tmp_path):
    root = ROOT
    code = main(['artifact', 'publish', str(root / 'agents' / 'research.yaml'),
                 '--db', str(tmp_path / 'a.db')])
    assert code == 2      # 没有 --gate → 直接拒绝


def test_cli_publish_blocks_on_missing_or_failing_gate(tmp_path):
    root = ROOT
    db = str(tmp_path / 'a.db')
    # 报告不存在
    code = main(['artifact', 'publish', str(root / 'agents' / 'research.yaml'),
                 '--gate', 'ghost', '--db', db])
    assert code == 1
    # 报告存在但没过
    _gate(db, 'gate-bad', verdict='fail')
    code = main(['artifact', 'publish', str(root / 'agents' / 'research.yaml'),
                 '--gate', 'gate-bad', '--db', db])
    assert code == 1
    # 失败的发布不落任何资产
    from infra.control import ArtifactStore
    from infra.store.sqlite import SqliteStore
    assert ArtifactStore(SqliteStore(db)).list_artifacts() == []


def test_cli_publish_with_passing_gate_and_history(tmp_path, capsys):
    root = ROOT
    db = str(tmp_path / 'a.db')
    _gate(db, 'gate-1')
    code = main(['artifact', 'publish', str(root / 'agents' / 'research.yaml'),
                 '--gate', 'gate-1', '--db', db, '--actor', 'tester',
                 '--json'])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['state'] == 'released'
    assert payload['gate_report'] == 'gate-1'

    capsys.readouterr()
    code = main(['artifact', 'history', 'research-assistant', '--db', db,
                 '--json'])
    assert code == 0
    events = json.loads(capsys.readouterr().out)
    assert [(e['action'], e['to_state']) for e in events] == [
        ('review', 'reviewing'), ('approve', 'approved'),
        ('release', 'released')]


def test_cli_rollback(tmp_path, capsys):
    root = ROOT
    db = str(tmp_path / 'a.db')
    _gate(db)
    main(['artifact', 'publish', str(root / 'agents' / 'research.yaml'),
          '--gate', 'gate-1', '--db', db])
    capsys.readouterr()
    code = main(['artifact', 'rollback', 'research-assistant', '0.4.2',
                 '--reason', '回归了', '--db', db, '--json'])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['to_state'] == 'rolled_back'
    # 回滚后的版本回到评审线
    capsys.readouterr()
    main(['artifact', 'list', '--db', db, '--json'])
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]['state'] == 'rolled_back'
    assert 'review' in rows[0]['allowed_actions']


def test_gate_report_persists_and_gates_publish(tmp_path, capsys):
    """闭环（策划案 §4.5.2）：gate 命令的报告落 eval_gate_report 表，
    artifact publish 用它校验 verdict —— fail 报告阻断发布，
    pass 报告放行。"""
    db = str(tmp_path / 'a.db')
    trace = tmp_path / 'trace.jsonl'
    run_json = tmp_path / 'run.json'
    gate_json = tmp_path / 'gate.json'
    dataset = ROOT / 'harness' / 'datasets' / 'basic.yaml'

    # 只有 1 个 case 有 trace → 质量闸门 fail（预期）
    main(['run', 'demo', '--trace', str(trace), '--case-id', 'demo',
          '--db', db])
    main(['eval', '--dataset', str(dataset), '--traces', str(trace),
          '--out', str(run_json)])
    main(['gate', '--run', str(run_json), '--out', str(gate_json),
          '--db', db])
    report = json.loads(gate_json.read_text(encoding='utf-8'))
    assert report['verdict'] == 'fail'

    # 报告已落库（publish 才能查到它）
    from infra.eval.trace_store import TraceStore
    stored = TraceStore(db).get_gate_report(report['id'])
    assert stored is not None and stored['verdict'] == 'fail'

    # fail 报告阻断发布
    code = main(['artifact', 'publish', str(ROOT / 'agents' / 'research.yaml'),
                 '--gate', report['id'], '--db', db])
    assert code == 1
    # pass 报告放行
    TraceStore(db).save_gate_report({'id': 'gate-ok', 'run_version_id': 'rv',
                                     'verdict': 'pass', 'created_at': 1.0})
    code = main(['artifact', 'publish', str(ROOT / 'agents' / 'research.yaml'),
                 '--gate', 'gate-ok', '--db', db])
    assert code == 0


def test_cli_list_starts_empty(tmp_path, capsys):
    main(['artifact', 'list', '--db', str(tmp_path / 'a.db'), '--json'])
    assert json.loads(capsys.readouterr().out) == []


def test_cli_run_accepts_artifact_and_kernel_flags():
    from harness.cli.main import build_parser
    parser = build_parser()
    args = parser.parse_args(['run', 'hi', '--artifact', 'agents/study.yaml'])
    assert args.artifact == 'agents/study.yaml'
    args2 = parser.parse_args(['run', 'hi', '--kernel', 'planner'])
    assert args2.kernel == 'planner'


def test_run_artifact_assembly_applies_the_declaration():
    """--artifact 把声明里的 kernel / 工具 / 模型装配进 run 参数。"""
    from harness.cli.main import build_parser
    from harness.cli.runcmd import _apply_artifact
    root = ROOT
    args = build_parser().parse_args(
        ['run', 'hi', '--artifact', str(root / 'agents' / 'research.yaml')])
    _apply_artifact(args)
    assert args.kernel == 'react'
    assert args.include == ['fs.read', 'fs.write', 'proc.run']
    assert args.model == 'deepseek-chat'
    assert args.artifact_loaded.name == 'research-assistant'

    # 显式 --kernel 优先于声明（调试时可以临时换架构）
    args2 = build_parser().parse_args(
        ['run', 'hi', '--kernel', 'workflow',
         '--artifact', str(root / 'agents' / 'study.yaml')])
    _apply_artifact(args2)
    assert args2.kernel == 'workflow'
