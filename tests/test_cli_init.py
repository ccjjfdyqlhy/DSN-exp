# tests/test_cli_init.py
# roadmap 段 2 的验收测试：`aicf init` 空白脚手架。
#
# 验收标准（roadmap 原文）：
#   一个从没用过 aicf 的人，`pip install aicf-core && aicf init demo && cd demo`
#   之后，10 分钟内能让 agent 调通自己的第一个工具。
#
# 落到这里就是四条可执行断言：
#   1. init 生成完整骨架（每个接入点都有文件）
#   2. 生成后立刻能跑：python agent.py 起得来（离线、桩模型）
#   3. aicf tool list 看得见自己注册的工具
#   4. aicf tool exec 能真的调通第一个工具（离线，不需要 --yes）

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aicf.harness.cli.main import main as cli_main
from aicf.harness.tools.local import (
    LocalToolsError,
    attach_local_tools,
    load_local_tools,
)
from aicf.harness.tools.registry import ManagedToolRegistry

EXPECTED_FILES = (
    'agent.py',
    'tools/greet.py',
    'skills/hello/skill.yaml',
    'skills/hello/hello.py',
    'policies/policy.yaml',
    'traces/.gitkeep',
    'README.md',
    'pyproject.toml',
    '.gitignore',
)


@pytest.fixture(autouse=True)
def _in_tmp(tmp_path):
    """init 按「当前目录」工作 —— 测试一律在临时目录里跑。"""
    old = Path.cwd()
    os.chdir(tmp_path)
    yield
    os.chdir(old)


# ── 单元：骨架生成 ──────────────────────────────────────────

def test_init_creates_complete_skeleton(tmp_path, capsys):
    code = cli_main(['init', 'demo'])
    assert code == 0, capsys.readouterr().out
    target = tmp_path / 'demo'
    for rel in EXPECTED_FILES:
        assert (target / rel).exists(), f'骨架缺文件: {rel}'
    # pyproject 里的项目名要跟目录名走
    assert 'name = "demo"' in (target / 'pyproject.toml').read_text(encoding='utf-8')


def test_init_refuses_to_overwrite_non_empty_dir(tmp_path, capsys):
    cli_main(['init', 'demo'])
    target = tmp_path / 'demo'
    (target / 'user-file.txt').write_text('用户自己的东西', encoding='utf-8')
    code = cli_main(['init', 'demo'])
    assert code == 2
    err = capsys.readouterr().err
    assert '拒绝覆盖' in err
    # 用户的东西没被动过
    assert (target / 'user-file.txt').read_text(encoding='utf-8') == '用户自己的东西'


def test_init_force_overwrites(tmp_path):
    cli_main(['init', 'demo'])
    (tmp_path / 'demo' / 'agent.py').write_text('# 用户改坏了', encoding='utf-8')
    code = cli_main(['init', 'demo', '--force'])
    assert code == 0
    text = (tmp_path / 'demo' / 'agent.py').read_text(encoding='utf-8')
    assert 'create_agent' in text


def test_init_json_output_lists_files(tmp_path, capsys):
    code = cli_main(['init', 'demo', '--json'])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['project'] == 'demo'
    assert 'agent.py' in payload['files']
    assert payload['template'] == 'default'


def test_init_invalid_template_exits_2(tmp_path, capsys):
    code = cli_main(['init', 'demo', '--template', 'voice'])
    assert code == 2
    assert 'voice' in capsys.readouterr().err


def test_init_default_name_is_my_agent(tmp_path):
    code = cli_main(['init'])
    assert code == 0
    assert (tmp_path / 'my-agent' / 'agent.py').exists()


# ── 验收核心：生成后立刻能跑 ────────────────────────────────

def _run_cli_in(tmp_path, argv, capsys=None):
    """在 tmp_path 里跑一条 CLI 命令，返回 (code, out, err)。"""
    import contextlib
    import io

    old_cwd = Path.cwd()
    out, err = io.StringIO(), io.StringIO()
    try:
        os.chdir(tmp_path)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli_main(argv)
    finally:
        os.chdir(old_cwd)
    return code, out.getvalue(), err.getvalue()


def test_skeleton_tool_visible_in_aicf_tool_list(tmp_path):
    """`aicf tool list` 必须看得见骨架里用户自己的 greet 工具。"""
    _run_cli_in(tmp_path, ['init', 'demo'], None)
    code, out, _err = _run_cli_in(tmp_path / 'demo', ['tool', 'list', '--json'], None)
    assert code == 0
    names = [row['name'] for row in json.loads(out)]
    assert 'greet' in names, f'自己的工具没出现在目录里: {names}'


def test_skeleton_first_tool_executes_offline(tmp_path):
    """`aicf tool exec greet` 离线调通第一个工具 —— 不需要 --yes。

    greet 声明了 pure + readonly 契约，默认策略（auto_approve_risk=low）
    自动放行；这也钉住「声明契约的工具不会被误判成 effectful」。
    """
    _run_cli_in(tmp_path, ['init', 'demo'], None)
    code, out, err = _run_cli_in(
        tmp_path / 'demo',
        ['tool', 'exec', 'greet', '--args', '{"name":"世界"}'], None)
    assert code == 0, err or out
    assert '你好，世界' in out


def test_skeleton_agent_py_runs_offline(tmp_path):
    """生成的 agent.py 不需要 API key 就能起得来并打印结果。"""
    _run_cli_in(tmp_path, ['init', 'demo'], None)
    project = tmp_path / 'demo'
    env = {k: v for k, v in os.environ.items()
           if k not in ('OPENAI_API_KEY', 'OPENAI_BASE_URL')}
    # 开发环境：让子进程吃到仓库里的包（发布后 pip install 自带本模块）
    repo = str(Path(__file__).resolve().parents[1])
    env['PYTHONPATH'] = repo + os.pathsep + env.get('PYTHONPATH', '')
    proc = subprocess.run(
        [sys.executable, 'agent.py', '用 greet 打个招呼'],
        cwd=project, env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-2000:]
    # 桩模型回显输入；关键是进程起得来、循环跑得完、有输出。
    assert proc.stdout.strip(), 'agent.py 没有打印任何结果'


def test_skeleton_agent_tool_table_starts_empty_and_loads_tools(tmp_path):
    """agent.py 的工具表来自 tools/ 目录 —— 用户加一个文件就该多一个工具。"""
    _run_cli_in(tmp_path, ['init', 'demo'], None)
    project = tmp_path / 'demo'
    extra = project / 'tools' / 'echo_tool.py'
    extra.write_text(
        'def echo(text: str) -> str:\n'
        '    """原样返回输入。"""\n'
        '    return text\n\n'
        'TOOLS = [echo]\n',
        encoding='utf-8')
    code, out, _ = _run_cli_in(project, ['tool', 'list', '--json'], None)
    assert code == 0
    names = [row['name'] for row in json.loads(out)]
    assert 'echo' in names and 'greet' in names


def test_tools_dir_without_marker_is_never_scanned(tmp_path, capsys):
    """没有标记文件的 tools/ 目录不会被隐式扫描 —— 别在人家的工作目录里
    静默执行任意 python 文件（仓库自己的 tools/ 就是这么被误伤的）。"""
    (tmp_path / 'tools').mkdir()
    (tmp_path / 'tools' / 'boom.py').write_text(
        'raise RuntimeError("不该被执行")\n', encoding='utf-8')
    code, out, err = _run_cli_in(tmp_path, ['tool', 'list', '--json'], capsys)
    assert code == 0
    assert '不该被执行' not in err


# ── 单元：tools/ 装载器 ─────────────────────────────────────

def _make_tool_dir(tmp_path, *files: tuple[str, str]) -> Path:
    d = tmp_path / 'tools'
    d.mkdir(exist_ok=True)
    for name, content in files:
        (d / name).write_text(content, encoding='utf-8')
    return d


def test_load_local_tools_missing_dir_raises(tmp_path):
    with pytest.raises(LocalToolsError):
        load_local_tools(tmp_path / 'nope')


def test_load_local_tools_skips_bad_file_but_loads_good_one(tmp_path, capsys):
    d = _make_tool_dir(
        tmp_path,
        ('broken.py', 'import 不存在的模块_xyz\nTOOLS = []\n'),
        ('ok.py', 'def a(x: int) -> int:\n    """加一。"""\n    return x + 1\n\n'
                  'TOOLS = [a]\n'),
        ('_private.py', 'def b() -> str:\n    """不该被装载。"""\n    return "b"\n\n'
                        'TOOLS = [b]\n'),
        ('no_tools.py', 'VALUE = 1\n'),
    )
    tools = load_local_tools(d)
    assert [t.name for t in tools] == ['a']
    err = capsys.readouterr().err
    assert 'broken.py' in err          # 坏文件被报告
    assert 'no_tools.py' in err        # 没写 TOOLS 也要说清楚
    assert '_private' not in err       # 下划线文件不扫


def test_attach_local_tools_skips_name_clash(tmp_path, capsys):
    d = _make_tool_dir(
        tmp_path,
        ('ok.py', 'def a(x: int) -> int:\n    """加一。"""\n    return x + 1\n\n'
                  'TOOLS = [a]\n'))
    registry = ManagedToolRegistry()
    registry.register_tool('a', '已有同名标准工具', lambda: None)
    assert attach_local_tools(registry, d) == 0
    assert '重名' in capsys.readouterr().err


def test_attach_local_tools_reports_and_registers(tmp_path):
    d = _make_tool_dir(
        tmp_path,
        ('ok.py', 'def a(x: int) -> int:\n    """加一。"""\n    return x + 1\n\n'
                  'TOOLS = [a]\n'))
    registry = ManagedToolRegistry()
    assert attach_local_tools(registry, d) == 1
    assert registry.get('a') is not None
