# tests/test_eval_offline.py
# roadmap 段 3 的验收测试：陌生人照 README 走完，看到的是成功。
#
# 三条可执行断言：
#   1. offline 冒烟数据集真实存在、可装载、纯结构性断言（不依赖输出内容）
#   2. `aicf run --dataset offline` 端到端跑完 → trace 落盘
#   3. `aicf eval` + `aicf gate` 全绿 —— 不需要任何 API key
#
# 外加 --group 过滤的单元测试（段 3 顺手落的能力）。

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aicf.harness.cli.main import main as cli_main
from aicf.infra.eval.dataset import load_dataset

REPO = Path(__file__).resolve().parents[1]
OFFLINE_YAML = REPO / 'aicf' / 'harness' / 'datasets' / 'offline.yaml'


@pytest.fixture(autouse=True)
def _in_tmp(tmp_path):
    old = Path.cwd()
    os.chdir(tmp_path)
    yield
    os.chdir(old)


# ── 数据集本身 ──────────────────────────────────────────────

def test_offline_dataset_loads_with_structural_assertions_only():
    dataset = load_dataset(str(OFFLINE_YAML))
    assert dataset.id == 'offline'
    assert len(dataset.cases) >= 5
    assert all(c.group == 'offline' for c in dataset.cases)
    # 纯结构性：不允许内容类断言 —— 桩模型的回声不该被用来「过内容检查」。
    forbidden = {'output_contains', 'output_matches'}
    for case in dataset.cases:
        for assertion in case.expect:
            kind = next(iter(assertion)) if isinstance(assertion, dict) else assertion
            assert kind not in forbidden, f'{case.id} 用了内容类断言 {kind}'
    assert dataset.critical_count >= 1, '链路自检得有一条关键用例'


def test_offline_dataset_does_not_touch_basic():
    """offline 是新增的冒烟集；basic 的 40 case 口径一个都不能动。"""
    basic = load_dataset(str(REPO / 'aicf' / 'harness' / 'datasets' / 'basic.yaml'))
    assert len(basic.cases) == 40
    offline = load_dataset(str(OFFLINE_YAML))
    assert len(offline.cases) < len(basic.cases)
    assert basic.id == 'offline'.replace('offline', 'basic')


# ── 验收核心：run → eval → gate 离线全绿 ────────────────────

def _cli(argv, capsys):
    code = cli_main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_run_eval_gate_offline_chain_is_green(tmp_path, capsys):
    code, out, err = _cli(
        ['run', '--dataset', 'offline', '--trace-dir', 'traces/'], capsys)
    assert code == 0, err or out
    traces = sorted(p.name for p in (tmp_path / 'traces').glob('*.jsonl'))
    assert len(traces) >= 5, f'trace 没有按用例落盘: {traces}'

    code, out, err = _cli(
        ['eval', '--dataset', 'offline', '--traces', 'traces/',
         '--out', 'run.json'], capsys)
    assert code == 0, err or out
    run = json.loads((tmp_path / 'run.json').read_text(encoding='utf-8'))
    assert run['status'] == 'passed'

    code, out, err = _cli(['gate', '--run', 'run.json', '--out', 'gate.json'],
                          capsys)
    assert code == 0, err or out
    gate = json.loads((tmp_path / 'gate.json').read_text(encoding='utf-8'))
    assert gate['verdict'] == 'pass'
    assert gate['failed_gates'] == []


def test_dataset_run_writes_setup_files_into_workspace(tmp_path, capsys):
    """basic 的 file_io 用例带 setup.files —— 数据集模式要真的把它们写出来。

    多个用例共用同一个工作区，后写的用例覆盖先写的（共享工作区语义）；
    所以这里只断言「文件被写出来了 + 每个用例有自己的 trace」。
    """
    code, out, err = _cli(
        ['run', '--dataset', 'basic', '--trace-dir', 'traces/',
         '--workspace', 'ws'], capsys)
    assert code == 0, err or out
    a_txt = tmp_path / 'ws' / 'a.txt'
    assert a_txt.exists() and a_txt.read_text(encoding='utf-8').strip()
    assert (tmp_path / 'traces' / 'read_file_returns_content.jsonl').exists()


# ── --group 过滤 ────────────────────────────────────────────

def test_eval_group_filter_scores_only_selected_group(tmp_path, capsys):
    dataset = load_dataset(str(REPO / 'aicf' / 'harness' / 'datasets' / 'basic.yaml'))
    subset = dataset.filtered({'file_io'})
    assert subset.id == dataset.id
    assert {c.group for c in subset.cases} == {'file_io'}
    # 子集 hash 与全集不同 —— 「评了子集」必须能从 run 记录里看出来
    assert subset.hash != dataset.hash
    # 原对象不被改动
    assert len(dataset.cases) == 40


def test_eval_cli_group_filter(tmp_path, capsys):
    code, out, err = _cli(
        ['run', '--dataset', 'offline', '--trace-dir', 'traces/'], capsys)
    assert code == 0
    code, out, err = _cli(
        ['eval', '--dataset', 'offline', '--traces', 'traces/',
         '--group', 'offline', '--out', 'run.json'], capsys)
    assert code == 0, err or out

    code, out, err = _cli(
        ['eval', '--dataset', 'offline', '--traces', 'traces/',
         '--group', 'no-such-group'], capsys)
    assert code == 2
    assert '没有用例' in err


# ── 最小可运行例 ────────────────────────────────────────────

def test_minimal_example_runs_and_prints_results(tmp_path):
    """examples/minimal.py：零依赖、无 key、打印结果 —— README 指向它。"""
    import subprocess
    env = {k: v for k, v in os.environ.items()
           if k not in ('OPENAI_API_KEY', 'OPENAI_BASE_URL')}
    env['PYTHONPATH'] = str(REPO) + os.pathsep + env.get('PYTHONPATH', '')
    proc = subprocess.run([sys.executable, str(REPO / 'examples' / 'minimal.py')],
                          cwd=tmp_path, env=env, capture_output=True,
                          text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert 'agent.chat' in proc.stdout
    assert 'add(1, 2) = 3' in proc.stdout
