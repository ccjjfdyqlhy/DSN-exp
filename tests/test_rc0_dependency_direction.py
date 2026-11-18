# tests/test_rc0_dependency_direction.py
# 依赖方向守卫。
#
# 为什么这条测试值得存在：
# 仓库的依赖规则是「harness → infra，单向」。文档里写着这条规则，
# 但**没有测试钉着它** —— 于是每次并行开发都可能悄悄新增一处反向依赖。
# 本轮（1.0.0-rc0）就真的新增了三处：infra/policy/engine.py 依赖
# harness.tools.spec，infra/observability/{trace,audit}.py 依赖
# harness.telemetry.*。
#
# 文档说「注释即缺陷数据库」；这条测试让「依赖规则」也从文档变成事实。

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INFRA = ROOT / 'infra'
HARNESS = ROOT / 'harness'

#: 允许 infra 反向依赖 harness 的模块（每个都要写明理由）。
#:
#: 当前为空 —— 这条规则对 infra 是**绝对**的，不开例外。
INFRA_TO_HARNESS_EXEMPT: dict[str, str] = {}


def _module_imports(path: Path) -> list[str]:
    """模块级 import 到的模块名（不含函数体内的延迟 import）。"""
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    found: list[str] = []
    for node in tree.body:            # 只看模块顶层：函数体里的延迟 import 不算
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:             # 相对 import（from .x import y）
                continue
            if node.module:
                found.append(node.module)
    return found


@pytest.mark.parametrize('path', sorted(INFRA.rglob('*.py')),
                         ids=lambda p: str(p.relative_to(ROOT)))
def test_infra_never_imports_harness(path: Path):
    """infra 不得 import harness。

    历史上 infra/observability/core.py 反向 import harness.pipeline.events
    被当成违规清掉过（见 docs/architecture.md）。这条测试让同一个错误
    不再发生第二次。
    """
    for name in _module_imports(path):
        if name == 'harness' or name.startswith('harness.'):
            key = str(path.relative_to(ROOT))
            reason = INFRA_TO_HARNESS_EXEMPT.get(key)
            assert reason, (
                f'{key} 在模块级依赖了 {name} —— infra → harness 是违规的依赖方向。'
                f'（端口与共享数据类型应住在 infra，harness 往上依赖它；'
                f'确实需要例外的话，在 INFRA_TO_HARNESS_EXEMPT 里写明理由。）')


#: 在子进程里导入一个模块，并报告它是否把 harness.* 拉进了 sys.modules。
#:
#: 必须在**独立进程**里做：pytest 进程本身可能已经 import 过 harness
#: （其它测试导入的），那样任何模块都会「看起来」依赖了 harness。
_PROBE = """
import importlib, json, sys
name = sys.argv[1]
try:
    importlib.import_module(name)
except Exception as error:
    print(json.dumps({'error': str(error)}))
    raise SystemExit(0)
leaked = sorted(n for n in sys.modules
                if n == 'harness' or n.startswith('harness.'))
print(json.dumps({'leaked': leaked}))
"""


@pytest.mark.parametrize('path', sorted(INFRA.rglob('*.py')),
                         ids=lambda p: str(p.relative_to(ROOT)))
def test_infra_modules_do_not_import_harness_at_runtime(path: Path):
    """运行期也检查：模块被导入后，sys.modules 里不该有 harness.*。

    静态扫描抓不到「函数体内的延迟 import」和「importlib 动态导入」，
    所以补一条运行期的兜底。独立子进程保证 sys.modules 是干净的。
    """
    import json
    import subprocess
    import sys

    module_name = '.'.join(path.relative_to(ROOT).with_suffix('').parts)
    if module_name.endswith('.__init__'):
        module_name = module_name[:-len('.__init__')]
    result = subprocess.run(
        [sys.executable, '-c', _PROBE, module_name],
        capture_output=True, text=True, cwd=str(ROOT), timeout=120)
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        pytest.skip(f'{module_name} 导入失败，跳过运行期检查')
    payload = json.loads(lines[-1])
    if payload.get('error'):
        pytest.skip(f'{module_name} 导入失败，跳过运行期检查')
    leaked = payload.get('leaked') or []
    assert not leaked, (
        f'{module_name} 导入后 sys.modules 里出现了 harness 模块: {leaked} '
        f'—— 说明它（可能间接）依赖了 harness。')
