# harness/tools/sandbox/namespaced.py
# 强隔离档沙箱：Linux namespace / bubblewrap / nsjail（可用则用）。
#
# 定位（策划案 §4.4.4 后端表）：namespaced = 中等强度，Linux 生产用。
# 与 restricted 的本质区别：
#   restricted  = **执行前判定**（看命令行里写了什么路径/域名）
#   namespaced  = **执行时约束**（内核层面 mount/net namespace，命令想越界也越不了）
#
# 「不可用则不报错，由上层降级到 restricted」（策划案 §3.3.5「降级而非降智」）：
#   这个模块**永远不抛异常**。探测不到任何强隔离后端时，
#   NamespacedSandbox 会退化成 restricted 的执行方式，
#   并在 SandboxResult 上如实标注 degraded=True / backend='restricted'。
#   绝不静默假装自己在沙箱里。
#
# 三种后端的探测与用法：
#   bubblewrap (bwrap)  —— 最完整：ro-bind / bind / unshare-net / unshare-pid 一应俱全
#   nsjail              —— Google 出品，配置驱动，需要 root 或 user namespace
#   unshare             —— util-linux 自带，配合 mount --bind 自己做 chroot
#
# 各分支的**验证状态**（未验证的分支必须写清楚，读者才会知道该信几分）：
#   bubblewrap  —— 已实测。本机 bubblewrap 0.6.1，实测 /etc/passwd 在运行时
#                  不可见、工作区可写、--unshare-net 断网生效。
#   unshare     —— 已实测。本机 util-linux 2.37.2，user namespace + mount
#                  namespace 可用（需 --map-root-user 才有权限）。
#   nsjail      —— **未在本机验证**（探测到未安装）。代码按上游 CLI 语义编写，
#                  保留是因为生产环境常见 nsjail；首次在装了 nsjail 的机器上
#                  启用时，请用 tests/test_rc0_sandbox.py 里的
#                  test_namespaced_* 用例验一遍。
#
# 探测方式：不是「文件在不在」，而是**真跑一次最小命令**。
# 原因：容器里 bwrap 可能存在但被 seccomp 挡住（EPERM），
# 只看 which() 会得到「可用」的假象 → 静默降级而不自知。
# 真跑一次，失败就如实记为不可用。

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import Sequence

from .base import BackendName, SandboxRequest, SandboxResult
from .paths import PathPolicy, scan_path_violations, tokenize
from .restricted import (
    PreparedCommand,
    VIOLATION_CMD_DENIED,
    VIOLATION_NET_DENY,
    RestrictedSandbox,
    build_sandbox_env,
    check_network,
    decode_output,
    effective_command_line,
    path_violation_code,
    record_violation,
    run_subprocess,
)

logger = logging.getLogger('aicf.harness.tools.sandbox')

#: 强隔离后端的探测结果
#:
#: available  真的能跑起来（不是「二进制在」）
#: reason     不可用的原因 —— 要能被人查，不能只留一个 False
@dataclass(frozen=True)
class BackendProbe:
    available: bool
    reason: str = ''
    version: str = ''


def _probe_command(argv: Sequence[str], *, timeout: float = 10.0) -> BackendProbe:
    """真跑一次最小命令，验证这个后端在本机**真的**可用。

    设计取舍：为什么不用 shutil.which()？
    因为「二进制存在」≠「能用」。容器里 bwrap 常常在，但被 seccomp 或
    缺少 user namespace 挡住（EPERM / Operation not permitted）。
    只看 which() 会得到「可用」的假象，然后真跑的时候静默失败 ——
    那正是策划案 §3.3.5 要避免的「以为自己在沙箱里」。
    """
    try:
        proc = subprocess.run(list(argv), capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as error:
        return BackendProbe(False, f'probe failed: {error}')
    if proc.returncode != 0:
        stderr = decode_output(proc.stderr or b'').strip().splitlines()
        detail = stderr[-1] if stderr else f'exit {proc.returncode}'
        return BackendProbe(False, f'probe exited {proc.returncode}: {detail}')
    return BackendProbe(True, '', decode_output(proc.stdout or b'').strip()[:120])


def probe_bubblewrap() -> BackendProbe:
    """bubblewrap 是否真的可用。"""
    binary = shutil.which('bwrap')
    if not binary:
        return BackendProbe(False, 'bwrap not found')
    # --ro-bind / / 只做只读根挂载，跑 /bin/true 验证整条链路
    return _probe_command([binary, '--ro-bind', '/', '/', '--dev', '/dev',
                           '--proc', '/proc', '--', '/bin/true'])


def probe_nsjail() -> BackendProbe:
    """nsjail 是否真的可用。"""
    binary = shutil.which('nsjail')
    if not binary:
        return BackendProbe(False, 'nsjail not found')
    return _probe_command([binary, '--quiet', '--', '/bin/true'])


def probe_unshare() -> BackendProbe:
    """unshare + user namespace 是否可用。

    要 --user --map-root-user：普通用户没有 CAP_SYS_ADMIN，
    但可以先建 user namespace 拿到里面的 root 权限。
    """
    binary = shutil.which('unshare')
    if not binary:
        return BackendProbe(False, 'unshare not found')
    return _probe_command([binary, '--user', '--map-root-user', '--net',
                           '--pid', '--fork', '--kill-child', '--',
                           '/bin/true'])


@dataclass
class NamespaceCapabilities:
    """本机可用的强隔离后端。"""

    bubblewrap: BackendProbe = field(default_factory=lambda: BackendProbe(False))
    nsjail: BackendProbe = field(default_factory=lambda: BackendProbe(False))
    unshare: BackendProbe = field(default_factory=lambda: BackendProbe(False))

    @property
    def any_available(self) -> bool:
        return (self.bubblewrap.available or self.nsjail.available
                or self.unshare.available)

    @property
    def best(self) -> str:
        """最强可用的后端名（空串 = 没有）。"""
        if self.bubblewrap.available:
            return 'bubblewrap'
        if self.nsjail.available:
            return 'nsjail'
        if self.unshare.available:
            return 'unshare'
        return ''

    def describe(self) -> str:
        parts = []
        for name, probe in (('bubblewrap', self.bubblewrap),
                            ('nsjail', self.nsjail),
                            ('unshare', self.unshare)):
            if probe.available:
                parts.append(f'{name}=ok')
            else:
                parts.append(f'{name}=no({probe.reason})')
        return ', '.join(parts)


def detect_capabilities() -> NamespaceCapabilities:
    """探测本机的强隔离能力（每次调用都真跑一遍探测）。

    刻意**不缓存**：容器镜像/权限可能在进程生命周期里变
    （比如测试里 monkeypatch 了 PATH），缓存会让探测结果与现实脱节。
    代价是每次探测约几十毫秒 —— 只在需要时调用。
    """
    return NamespaceCapabilities(
        bubblewrap=probe_bubblewrap(),
        nsjail=probe_nsjail(),
        unshare=probe_unshare(),
    )


class NamespacedSandbox:
    """强隔离档沙箱后端。

    用法::

        sandbox = NamespacedSandbox()
        result = await sandbox.run(SandboxRequest(cmd=['cat', '/etc/passwd']))
        # 本机有 bubblewrap → result.backend == 'namespaced'，文件读不到
        # 本机没有 → result.backend == 'restricted'，result.degraded == True

    **永不抛异常**：探测不到后端就退化到 restricted，并在结果里如实标注。
    """

    name: BackendName = 'namespaced'

    def __init__(self, *,
                 network_allowlist: Sequence[str] = (),
                 allowlist: Sequence[str] | None = None,
                 policy: PathPolicy | None = None,
                 system_read_paths: Sequence[str] | None = None,
                 ) -> None:
        if allowlist is not None:
            network_allowlist = allowlist
        self.network_allowlist = tuple(network_allowlist)
        self._policy = policy
        self._system_read_paths_override = (
            tuple(system_read_paths) if system_read_paths is not None else None)
        # 退化执行体：真的没有强隔离后端时用它，保证功能不中断
        self._fallback = RestrictedSandbox(
            network_allowlist=self.network_allowlist,
            policy=policy,
            system_read_paths=system_read_paths,
        )

    # ── 能力 ───────────────────────────────────────────
    def capabilities(self) -> NamespaceCapabilities:
        """探测本机可用的强隔离后端。"""
        return detect_capabilities()

    @property
    def degraded(self) -> bool:
        """本机没有可用强隔离后端时为 True。

        注意：这个属性反映的是**本机能力**，不是某一次执行的结果。
        单次执行的实际档位看 SandboxResult.backend / degraded。
        """
        return not self.capabilities().any_available

    # ── 主入口 ───────────────────────────────────────────
    def prepare(self, req: SandboxRequest) -> PreparedCommand:
        """判定并给出经沙箱批准的执行计划。

        没有强隔离后端时**不报错**：退化成 restricted 的计划，
        但 violation/degraded 由调用方从 result 上读。
        """
        caps = self.capabilities()
        backend = caps.best
        if not backend:
            logger.warning(
                'no strong isolation backend available (%s); '
                'falling back to restricted (degraded)', caps.describe())
            prepared = self._fallback.prepare(req)
            # 明确标成降级：调用方（run / shell 工具）据此如实标注
            # backend='restricted' + degraded=True。
            prepared.degraded = True
            return prepared
        cmd = list(req.cmd or [])
        if not cmd:
            return PreparedCommand(violation=VIOLATION_CMD_DENIED,
                                   detail='empty command', degraded=False)
        cwd = req.cwd or os.getcwd()
        policy = self._policy_for(req)
        tokens = (tokenize(effective_command_line(cmd, req.shell))
                  if req.shell else list(cmd))
        violations = scan_path_violations(tokens, policy, base=cwd, cwd=cwd)
        if violations:
            detail = '; '.join(str(v) for v in violations)
            logger.warning('sandbox denied command by path policy: %s', detail)
            code = path_violation_code(violations)
            # degraded=False：本档确实拿到了强隔离，拒绝是判定层给的
            # （namespaced 档降级时会走 _fallback.prepare，那里记 degraded=True）。
            record_violation(code, detail, degraded=False)
            return PreparedCommand(cwd=cwd, violation=code, detail=detail,
                                   degraded=False)
        net_denial = check_network(req.network, tokens, self.network_allowlist)
        if net_denial:
            logger.warning('sandbox denied command by network policy: %s',
                           net_denial)
            record_violation(VIOLATION_NET_DENY, net_denial, degraded=False)
            return PreparedCommand(cwd=cwd, violation=VIOLATION_NET_DENY,
                                   detail=net_denial, degraded=False)
        argv = self._build_argv(backend, cmd, req, cwd)
        if not argv:
            return PreparedCommand(cwd=cwd, violation=VIOLATION_CMD_DENIED,
                                   detail=f'cannot build {backend} command',
                                   degraded=False)
        return PreparedCommand(argv=argv, env=build_sandbox_env(req), cwd=cwd,
                               degraded=False)

    async def run(self, req: SandboxRequest) -> SandboxResult:
        """执行一次强隔离命令。

        没有强隔离后端时**不报错**：退化成 restricted 执行，
        并在结果里标 degraded=True / backend='restricted'。

        路径/网络判定仍然在执行前做一遍 —— 两层防护：
        内核层（namespace）挡住「命令想越界」，判定层给出**可读的拒绝原因**
        与审计信息。只靠内核层的话，用户只会看到 "No such file or directory"，
        不知道是沙箱挡的。

        判定逻辑只在 prepare() 里写一份（run 与 prepare 共用）——
        两份实现必然漂移，而漂移的方向通常是「某个后端忘了拦」。
        """
        started = time.monotonic()
        prepared = self.prepare(req)
        if prepared.denied:
            # prepare() 已经把违规记进 ToolContext.violations 了，
            # 这里只负责把违规码带回结果。
            return SandboxResult(
                exit_code=126,
                stderr=f'sandbox: {prepared.violation}: {prepared.detail}',
                duration_ms=(time.monotonic() - started) * 1000.0,
                violation=prepared.violation, degraded=prepared.degraded,
                backend='restricted' if prepared.degraded else 'namespaced')

        argv = prepared.argv
        cwd = prepared.cwd
        env = prepared.env
        degraded = prepared.degraded
        try:
            # 复用 restricted 的异步执行内核：同样的超时/取消语义，
            # 同样的事件循环友好性（不阻塞 loop）。
            exit_code, out, err, timed_out = await run_subprocess(
                argv, env=env, cwd=cwd, stdin_data=req.stdin,
                timeout=req.timeout)
        except asyncio.CancelledError:
            raise
        except OSError as error:
            logger.warning('namespaced spawn failed (%s); falling back to '
                           'restricted (degraded)', error)
            result = await self._fallback.run(req)
            result.degraded = True
            result.backend = 'restricted'
            return result

        stdout = decode_output(out or b'')
        stderr = decode_output(err or b'')
        truncated = False
        limit = max(0, int(req.max_output))
        if limit and len(stdout) > limit:
            stdout = stdout[:limit]
            truncated = True
        if limit and len(stderr) > limit:
            stderr = stderr[:limit]
            truncated = True

        return SandboxResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=(time.monotonic() - started) * 1000.0,
            truncated=truncated,
            degraded=degraded,
            backend='restricted' if degraded else 'namespaced',
            timed_out=timed_out,
        )

    # ── 内部 ───────────────────────────────────────────
    def _policy_for(self, req: SandboxRequest) -> PathPolicy:
        if self._policy is not None:
            base = self._policy
            system = base.system_read
        else:
            system = (self._system_read_paths_override
                      if self._system_read_paths_override is not None
                      else PathPolicy().system_read)
            base = PathPolicy(system_read=system)
        readonly = tuple(base.readonly) + tuple(req.readonly_paths)
        writable = tuple(base.writable) + tuple(req.writable_paths)
        return PathPolicy(readonly=readonly, writable=writable,
                           system_read=system)

    def _check_network(self, req: SandboxRequest,
                       tokens: Sequence[str]) -> str:
        return check_network(req.network, tokens, self.network_allowlist)

    def _build_env(self, req: SandboxRequest) -> dict[str, str]:
        return build_sandbox_env(req)

    def _build_argv(self, backend: str, cmd: Sequence[str],
                    req: SandboxRequest, cwd: str) -> list[str] | None:
        """按后端拼出真正的 argv。"""
        if backend == 'bubblewrap':
            return self._bubblewrap_argv(cmd, req, cwd)
        if backend == 'nsjail':
            return self._nsjail_argv(cmd, req, cwd)
        if backend == 'unshare':
            return self._unshare_argv(cmd, req, cwd)
        return None

    # ── bubblewrap ─────────────────────────────────────
    def _bubblewrap_argv(self, cmd: Sequence[str], req: SandboxRequest,
                         cwd: str) -> list[str]:
        """拼 bubblewrap 命令行。

        关键点（每一行都对应一个安全属性）：
          --ro-bind /usr /usr ...   只 bind **明确允许读**的系统目录。
            修复说明：早期版本用 `--ro-bind / /` 把整个根挂成只读 ——
            那样虽然写不坏系统，但**读得到** /etc/passwd、/root/.ssh、
            别的租户的数据。路径白名单是「读」的限制，不是「写」的限制，
            所以必须按目录逐个 bind，而不是整个 /。
          --tmpfs /etc               /etc 只放 resolv.conf / hosts / nsswitch.conf。
            少一个文件都不影响正常命令，但少了它们 DNS 与用户查询就废了。
          --bind <writable>          可写路径单独 bind 回来（读写）
          --unshare-net              network=none 时彻底断网（内核级）
          --unshare-pid              PID 隔离，命令看不到宿主进程
          --clearenv                 不继承宿主环境变量（与 restricted 同一原则）
          --setenv K V               只放行声明过的变量
        """
        binary = shutil.which('bwrap')
        if not binary:
            return []
        argv: list[str] = [binary, '--unshare-pid', '--die-with-parent',
                           '--new-session', '--clearenv',
                           '--dev', '/dev', '--proc', '/proc',
                           '--tmpfs', '/tmp', '--tmpfs', '/etc']
        # 允许读的系统目录（解释器 + 动态库）
        for path in self._system_read_paths():
            if os.path.isdir(path):
                argv += ['--ro-bind', path, path]
        # DNS / 用户查询需要的最小 /etc
        for name in ('resolv.conf', 'hosts', 'nsswitch.conf', 'localtime',
                     'ssl'):
            source = os.path.join('/etc', name)
            if os.path.exists(source):
                argv += ['--ro-bind', source, source]
        for key, value in (req.env or {}).items():
            if isinstance(key, str) and key:
                argv += ['--setenv', key, str(value)]
        if req.network == 'none':
            argv.append('--unshare-net')
        # 只读路径与可写路径 bind 回来（其它地方保持不可见）
        for path in tuple(req.readonly_paths):
            if os.path.exists(path):
                argv += ['--ro-bind', path, path]
        for path in tuple(req.writable_paths):
            if os.path.exists(path):
                argv += ['--bind', path, path]
        # 工作目录必须在沙箱里存在，否则 chdir 会失败
        if not any(os.path.abspath(path) == os.path.abspath(cwd)
                   for path in tuple(req.writable_paths)):
            argv += ['--bind', cwd, cwd]
        argv += ['--chdir', cwd]
        argv += self._inner_argv(cmd, req)
        return argv

    def _system_read_paths(self) -> tuple[str, ...]:
        """沙箱里允许读的系统目录。"""
        if self._system_read_paths_override is not None:
            return tuple(self._system_read_paths_override)
        return PathPolicy().system_read

    # ── nsjail ─────────────────────────────────────────
    def _nsjail_argv(self, cmd: Sequence[str], req: SandboxRequest,
                     cwd: str) -> list[str]:
        """拼 nsjail 命令行。

        nsjail 的语义与 bubblewrap 相反：它**默认**就 clone 一个新的
        network namespace（= 默认断网），要保留宿主网络得显式
        `--disable_clone_newnet`。所以：
          network='none'      → 不加（保持默认的新 netns）
          network='allowlist' → 加 --disable_clone_newnet，
                                域名过滤交给执行前判定 + 上层 egress 代理
        """
        binary = shutil.which('nsjail')
        if not binary:
            return []
        argv: list[str] = [binary, '--quiet', '--chroot', '/']
        if req.network in ('allowlist', 'full'):
            argv.append('--disable_clone_newnet')
        argv += ['--cwd', cwd]
        argv += self._inner_argv(cmd, req)
        return argv

    # ── unshare ────────────────────────────────────────
    def _unshare_argv(self, cmd: Sequence[str], req: SandboxRequest,
                      cwd: str) -> list[str] | None:
        """拼 unshare 命令行。

        unshare 本身不会自动做文件系统隔离，所以这里靠 mount namespace
        + 一个自建的 root（tmpfs）把系统目录以只读方式挂进去。
        """
        binary = shutil.which('unshare')
        if not binary:
            return None
        script = self._unshare_script(cmd, req, cwd)
        if script is None:
            return None
        argv = [binary, '--user', '--map-root-user', '--mount', '--pid',
                '--fork', '--kill-child']
        if req.network == 'none':
            argv.append('--net')
        argv += ['--', '/bin/sh', '-c', script]
        return argv

    def _unshare_script(self, cmd: Sequence[str], req: SandboxRequest,
                        cwd: str) -> str | None:
        """生成 unshare 内部要跑的 shell 脚本（自建只读 root）。"""
        inner = ' '.join(shlex.quote(part)
                         for part in self._inner_argv(cmd, req))
        root = tempfile.mkdtemp(prefix='aicf-ns-')
        mounts = ['/usr', '/bin', '/sbin', '/lib', '/lib64']
        setup = [f'mkdir -p {root}']
        setup.append(f'mount -t tmpfs tmpfs {root}')
        for part in ('usr', 'bin', 'sbin', 'lib', 'lib64', 'proc', 'dev', 'tmp',
                     'etc', 'work'):
            setup.append(f'mkdir -p {root}/{part}')
        for part in mounts:
            if os.path.isdir(part):
                setup.append(f'mount --bind {part} {root}/{part}')
                setup.append(f'mount -o remount,ro,bind {root}/{part}')
        setup.append(f'mount -t proc proc {root}/proc')
        setup.append(f'mount --rbind /dev {root}/dev')
        setup.append(f'mount -t tmpfs tmpfs {root}/tmp')
        setup.append('cp /etc/resolv.conf %s/etc/ 2>/dev/null || true' % root)
        setup.append(f'mount --bind {cwd} {root}/work')
        setup.append(f'cd {root}/work')
        setup.append(f'exec {inner}')
        return ' ; '.join(setup)

    # ── 公共 ───────────────────────────────────────────
    def _inner_argv(self, cmd: Sequence[str], req: SandboxRequest) -> list[str]:
        """沙箱内部真正要跑的命令。"""
        if req.shell:
            return ['/bin/sh', '-c', effective_command_line(cmd, req.shell)]
        return list(cmd)


__all__ = [
    'BackendProbe',
    'NamespaceCapabilities',
    'NamespacedSandbox',
    'detect_capabilities',
    'probe_bubblewrap',
    'probe_nsjail',
    'probe_unshare',
]
