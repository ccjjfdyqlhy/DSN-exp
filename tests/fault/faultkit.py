# tests/fault/faultkit.py
# 故障注入测试（L4 层）的公共工具。
#
# 【这一层要证明什么】
#   策划案 §8.1 把测试分成五层，L4 是「故障注入」层：
#       kill -9 / 断网 / 磁盘满 / 超时 / 重复投递
#   它的门禁是「每夜」跑，而不是每次提交都跑 —— 因为它慢，而且它会
#   真的把子进程杀掉。
#
# 【为什么副作用计数必须写文件】
#   本层的核心场景是「进程被 kill -9」。父进程根本没有机会拿到子进程的
#   内存：子进程被 SIGKILL 之后，它的一切内存状态都随进程一起消失了。
#   所以「副作用只发生了一次」这件事**只能**落在进程外（文件）才能验证。
#   用内存 list 计数 = 验证了一个不存在的东西。
#
# 【为什么子进程用环境变量传参而不是字符串插值】
#   子进程脚本里全是 dict / f-string，字符串插值极易踩到花括号与引号的坑，
#   而且踩到了只在「某个分支」才报错。环境变量没有这个问题：
#   参数与代码彻底分离。

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

#: 仓库根目录（子进程要 import aicf.infra / harness，必须能找到它们）
REPO_ROOT = str(Path(__file__).resolve().parents[2])

#: 注入给子进程的环境变量前缀
ENV_DB = 'FAULT_DB'
ENV_COUNTER = 'FAULT_COUNTER'
ENV_READY = 'FAULT_READY'


class SideEffectCounter:
    """把「副作用发生了几次」写进文件 —— 跨进程可验证。

    用法:
        counter = SideEffectCounter(tmp_path / 'effects.log')
        counter.bump('send_email')
        assert counter.count('send_email') == 1
    """

    def __init__(self, path: os.PathLike[str] | str):
        self.path = str(path)

    def bump(self, tag: str = '') -> None:
        """记一次副作用。落盘 + fsync —— 进程下一秒可能被 SIGKILL。"""
        with open(self.path, 'a', encoding='utf-8') as handle:
            handle.write(tag + '\n')
            handle.flush()
            os.fsync(handle.fileno())

    def count(self, tag: str = '') -> int:
        """数副作用发生了几次。tag 为空则数总数。"""
        if not os.path.exists(self.path):
            return 0
        with open(self.path, encoding='utf-8') as handle:
            lines = [line.strip() for line in handle if line.strip()]
        if not tag:
            return len(lines)
        return sum(1 for line in lines if line == tag)


#: 注入到子进程脚本里的计数器实现（与 SideEffectCounter 等价）。
#:
#: 两份实现必须等价，所以**不要**在这里偷偷加逻辑 ——
#: 父进程数出来的次数和子进程写进去的次数必须对得上。
COUNTER_HELPER = '''
def bump(path, tag):
    """记一次副作用（落盘 + fsync：下一秒可能被 SIGKILL）。"""
    with open(path, 'a', encoding='utf-8') as handle:
        handle.write(tag + '\\n')
        handle.flush()
        os.fsync(handle.fileno())
'''


def child_script(source: str) -> str:
    """拼出子进程脚本：计数器助手 + 仓库路径 + 调用方源码。"""
    body = textwrap.dedent(source)
    return (
        'import os, sys\n'
        f'sys.path.insert(0, os.environ.get("FAULT_REPO", {REPO_ROOT!r}))\n'
        + COUNTER_HELPER
        + body
    )


def run_child(source: str, *, env: dict[str, str] | None = None,
              timeout: int = 60) -> subprocess.CompletedProcess:
    """在子进程里跑一段 python 源码，等它结束。

    用例 1 里子进程自己 os._exit(9)（模拟「工具执行中途被 kill -9」），
    所以这里的 returncode 是 9 而不是 0 —— 那正是我们要断言的。
    """
    child_env = dict(os.environ)
    child_env['FAULT_REPO'] = REPO_ROOT
    child_env.update(env or {})
    return subprocess.run(
        [sys.executable, '-c', child_script(source)],
        capture_output=True, timeout=timeout, env=child_env, cwd=REPO_ROOT,
    )


def spawn_child(source: str, *, env: dict[str, str] | None = None) -> subprocess.Popen:
    """起一个后台子进程（用例 3 用：它要停在审批等待里被真的 SIGKILL）。"""
    child_env = dict(os.environ)
    child_env['FAULT_REPO'] = REPO_ROOT
    child_env.update(env or {})
    return subprocess.Popen(
        [sys.executable, '-c', child_script(source)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=child_env, cwd=REPO_ROOT,
    )


def wait_for_file(path: str | os.PathLike[str], *, timeout: float = 20.0,
                  proc: subprocess.Popen | None = None) -> None:
    """等一个文件出现（子进程用它报告「我已经进入某个状态了」）。

    子进程如果提前死了要立刻报错 —— 否则测试会傻等到超时才失败，
    失败信息还完全看不出原因。
    """
    deadline = time.time() + timeout
    while not os.path.exists(path):
        if proc is not None and proc.poll() is not None:
            out, err = proc.communicate()
            raise AssertionError(
                '子进程在就绪之前就退出了：returncode='
                f'{proc.returncode}\nstdout={out.decode("utf-8", "replace")}'
                f'\nstderr={err.decode("utf-8", "replace")}')
        if time.time() > deadline:
            raise AssertionError(f'等待文件超时（{timeout}s）：{path}')
        time.sleep(0.02)


# ── 沙箱后端探测（R3 落地后自动生效）──────────────────

#: 沙箱后端没落地时的跳过原因（会写进 pytest 的 skip 原因里）
SANDBOX_MISSING_REASON = (
    '沙箱后端（harness/tools/sandbox/restricted.py）尚未落地 —— '
    '路径拦截与出网拦截的**执行层**都在后端里；'
    '判定层（harness/tools/sandbox/paths.py）已单独覆盖。'
)


def sandbox_backend(**kwargs):
    """拿到一个可用的沙箱后端实例；拿不到就返回 None。

    R3 的后端类名与构造参数还在收敛，所以这里按候选探测：
    先试无参构造，再试带参构造；都失败就返回 None（用例 skip）。

    返回 None 时测试会被 skip —— 跳过条件写在 SANDBOX_MISSING_REASON 里，
    不允许「悄悄跳过」：跳过的用例必须让人一眼看出为什么没跑。
    """
    # 优先用包级公开入口（harness.tools.sandbox 导出了后端），
    # 退化时再去子模块里找 —— 后端还在收敛，名字可能变。
    import importlib

    for module_name in ('aicf.harness.tools.sandbox',
                        'aicf.harness.tools.sandbox.restricted'):
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        for name in ('RestrictedSandbox', 'Sandbox', 'create_sandbox',
                     'build_sandbox', 'make_sandbox', 'detect_best_backend'):
            factory = getattr(module, name, None)
            if factory is None:
                continue
            backend = _try_build(factory, kwargs)
            if backend is not None:
                return backend
    return None


def _try_build(factory, kwargs):
    """按候选姿势构造后端；构造不出来返回 None。"""
    # 传了参数就**先**按参数构造 —— 否则会拿到一个「参数被忽略」的
    # 默认实例（比如 network_allowlist 没传进去，白名单永远是空的），
    # 测试就会以「白名单内域名被误伤」的形式假红。
    attempts = []
    if kwargs:
        attempts.append(lambda f=factory: f(**kwargs))
    attempts.append(lambda f=factory: f())
    for attempt in attempts:
        try:
            backend = attempt()
        except TypeError:
            continue
        except Exception:
            continue
        if backend is not None and hasattr(backend, 'run'):
            return backend
    return None


def sandbox_available() -> bool:
    """沙箱后端是否可用。"""
    return sandbox_backend() is not None
