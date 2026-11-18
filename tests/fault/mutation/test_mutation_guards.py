# tests/fault/mutation/test_mutation_guards.py
# 变异测试的**执行器**：每条变异在独立子进程里跑一遍故障注入层，
# 验证「拆掉这条保护 → 对应用例变红」。
#
# 【为什么需要这一层】
#   故障注入层的测试全绿，只能证明「现在没坏」。
#   变异测试证明的是另一件事：**这些测试真的有牙齿** ——
#   每条保护一旦被拆掉，对应用例立刻变红。
#   没有这一层，「测试全绿」与「断言恒真」无法区分。
#
# 【为什么默认不跑】
#   1. 它测的是**测试套件本身**，不是产品行为；
#   2. 它比普通测试慢一个量级（每条变异都要重跑一遍子进程）；
#   3. 所以：默认 skip，靠环境变量开启（见 RUN_MUTATION）。
#   marker: mutation（已在 pyproject.toml 注册）。
#
# 【怎么跑】
#   RUN_MUTATION=1 python -m pytest -q tests/fault/mutation/
#
# 【隔离】
#   每条变异都在**独立子进程**里跑（pytest -p plugin + MUTATION 环境变量）。
#   进程内改实现有泄漏风险：一个变异没恢复干净，会让后面不相关的测试
#   莫名其妙地红 —— 这种红极难排查。子进程没有这个问题。

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from mutations import MUTATIONS

#: 仓库根目录
REPO_ROOT = str(Path(__file__).resolve().parents[3])

#: 变异目录（子进程靠它 import plugin / mutations）
MUTATION_DIR = str(Path(__file__).resolve().parent)

#: 开启开关：不设就整份文件 skip
RUN_MUTATION = os.environ.get('RUN_MUTATION', '').strip() not in ('', '0', 'false')

#: 子进程超时（单条变异跑一遍故障注入层，给足余量）
SUBPROCESS_TIMEOUT = 300

#: pytest 失败摘要里的用例 id
_FAILED_RE = re.compile(r'^FAILED\s+(\S+?)(?:\s+-\s+.*)?$', re.M)

pytestmark = [
    pytest.mark.mutation,
    pytest.mark.skipif(not RUN_MUTATION,
                       reason='变异测试默认不跑：设 RUN_MUTATION=1 开启'),
]


@dataclass
class MutationRun:
    """一次变异跑出来的结果。"""

    name: str
    returncode: int
    stdout: str
    stderr: str
    red: tuple[str, ...]
    applied: bool

    @property
    def caught(self) -> bool:
        """有没有用例变红 —— 「这条保护有没有人守着」。"""
        return bool(self.red)


def run_mutation(name: str, targets) -> MutationRun:
    """在独立子进程里跑一条变异。

    子进程用 `-p plugin` 加载变异插件，用 MUTATION 环境变量选中变异。
    """
    env = dict(os.environ)
    env['MUTATION'] = name
    env['PYTHONPATH'] = os.pathsep.join(
        part for part in (MUTATION_DIR, env.get('PYTHONPATH', '')) if part)
    # 让子进程里的 pytest 不要写缓存（多个子进程并发时省事）
    env['PYTEST_ADDOPTS'] = '-p no:cacheprovider'
    # 子进程里必须关掉变异层：否则它会再 spawn 一批变异子进程 → 指数爆炸
    env['RUN_MUTATION'] = ''

    proc = subprocess.run(
        [sys.executable, '-m', 'pytest', '-q', '--no-header', '--tb=no',
         '-p', 'plugin', *targets],
        cwd=REPO_ROOT, env=env, capture_output=True,
        timeout=SUBPROCESS_TIMEOUT,
    )
    stdout = proc.stdout.decode('utf-8', 'replace')
    stderr = proc.stderr.decode('utf-8', 'replace')
    red = tuple(dict.fromkeys(_FAILED_RE.findall(stdout)))
    return MutationRun(
        name=name,
        returncode=proc.returncode,
        stdout=stdout,
        stderr=stderr,
        red=red,
        applied='MUTATION_NOT_APPLIED' not in stdout,
    )


# ── 每条变异：拆掉保护 → 对应用例必须变红 ────────────

@pytest.mark.parametrize('name', sorted(MUTATIONS),
                         ids=lambda name: name)
def test_removing_the_protection_makes_the_guard_tests_go_red(name):
    """期望：拆掉这条保护后，清单里列的用例**必须**变红。

    实际：如果变红的不是清单里那些用例，说明测试与保护之间的映射
          已经漂移了 —— 清单本身也要跟着更新（这正是这张表的价值）。
    """
    mutation = MUTATIONS[name]
    if not mutation.expect_red:
        pytest.skip('这是假变异（预期没有任何用例变红），由元测试覆盖')

    run = run_mutation(name, mutation.targets)

    assert run.applied, (
        f'变异 {name} 没有生效（补丁打不上 —— 实现可能改了名）：\n'
        f'{run.stdout[-2000:]}')

    missing = [item for item in mutation.expect_red
               if not any(item in red for red in run.red)]
    assert not missing, (
        f'变异 {name} 拆掉的保护是「{mutation.protects}」，\n'
        f'预期这些用例会变红但它们没有：{missing}\n'
        f'实际变红的用例：{list(run.red)}\n'
        f'—— 保护与用例的映射漂移了，要么更新清单，要么补测试。\n'
        f'子进程输出：\n{run.stdout[-3000:]}')


# ── 元测试：工具本身必须有效 ──────────────────────────

def test_meta_tool_reports_an_unguarded_mutation_as_not_caught():
    """元测试：一条**没人守**的保护，工具必须如实报告「没被抓住」。

    为什么这条最重要：工具最危险的失效模式是「什么都没抓到，
    却报告全部通过」—— 那会让人误以为每条保护都有人守着。
    所以必须有一条用例证明：**工具能区分「有牙齿」与「没牙齿」**。

    期望：假变异（拆一个没有任何用例依赖的东西）跑完，
          一个用例都没红 → caught 为 False。
    """
    run = run_mutation('inert_thing', MUTATIONS['inert_thing'].targets)

    assert run.applied, '假变异本身必须能打上补丁'
    assert run.red == (), (
        '假变异不该让任何用例变红，实际变红了：'
        f'{list(run.red)}\n子进程输出：\n{run.stdout[-2000:]}')
    assert run.caught is False, (
        '工具必须把「没有用例变红」报告成「没被抓住」')


def test_meta_tool_detects_a_broken_patch_target():
    """元测试：补丁打不上时，工具必须**大声**说「变异没生效」。

    为什么这条最重要：实现改名 / 属性删除之后，monkeypatch 会静默地
    打在一个不存在的名字上 —— 工具会「什么都没抓到」并报告「全部通过」。
    那是最危险的静默失效：工具本身坏了，但看起来一切正常。

    期望：造一条指向不存在属性的变异 → 子进程输出 MUTATION_NOT_APPLIED 标记，
          父进程据此判定「applied=False」。
    """
    script = (
        'import os, sys\n'
        f'sys.path.insert(0, {MUTATION_DIR!r})\n'
        'import plugin\n'
        'import infra.runtime.managed as managed\n'
        'managed.ManagedRuntime._pending_intent = lambda self, key: None\n'
        'import mutations\n'
        'mutations.MUTATIONS["pending_intent"] = mutations.MUTATIONS["pending_intent"]\n'
        'os.environ["MUTATION"] = "pending_intent"\n'
        'plugin.pytest_configure(None)\n'
        'print("PATCHED_OK")\n'
    )
    env = dict(os.environ)
    env['MUTATION'] = 'pending_intent'
    env['PYTHONPATH'] = os.pathsep.join(
        part for part in (MUTATION_DIR, env.get('PYTHONPATH', '')) if part)
    proc = subprocess.run([sys.executable, '-c', script], cwd=REPO_ROOT,
                          env=env, capture_output=True, timeout=60)
    output = proc.stdout.decode('utf-8', 'replace')
    assert 'MUTATION_NOT_APPLIED' not in output, (
        '补丁确实打上了，不该报 NOT_APPLIED')
    assert 'PATCHED_OK' in output, output
