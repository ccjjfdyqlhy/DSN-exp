# harness/tools/sandbox/restricted.py
# 默认降级档沙箱：子进程 + ulimit + 路径白名单 + 环境变量白名单。
#
# 这个档位的定位（策划案 §4.4.4 后端表）：
#   restricted = 子进程 + ulimit + 只读挂载 + 路径白名单 + 环境变量白名单，强度「弱」。
#   它是**兜底档**，不是「安全档」—— 只要没有 bubblewrap / nsjail / unshare，
#   上层就得按降级处理（degraded=True），让策略可以选择「降级即拒绝」。
#
# 为什么 restricted 也必须能拦路径（而不是「弱就放行」）：
#   弱的是**隔离强度**（没有内核级 mount namespace），不是**判定能力**。
#   路径逃逸在执行前就能判定出来 —— 命令行里的路径参数先 resolve 再判前缀，
#   越界的直接拒绝执行。这比「跑起来再靠权限报错」强得多：
#   后者已经产生了副作用（读了不该读的东西、写了一半的文件）。
#
# 为什么网络拦截是「按域名判定 + 显式失败」而不是「真断网」：
#   纯标准库没有 iptables / netns 的能力（那是 namespaced 档的活）。
#   restricted 档能做的是：**在执行前**把命令里指向非白名单域名的部分
#   判出来并拒绝，让上层记 net:deny 审计。
#   这拦不住「自己写 socket 直连 IP」的写法 —— 那种写法在 restricted 档
#   只能靠环境变量白名单 + 事后审计兜，**必须在 degraded 里如实说明**。
#
# 环境变量白名单（硬要求）：
#   子进程**不继承** os.environ。只放行 SandboxRequest.env 里声明过的变量，
#   加上沙箱自己注入的少数几个（PATH / LANG 之类）。理由：
#   os.environ 里通常有 API key、数据库口令、代理配置 —— 继承过去等于
#   把凭据交给模型控制的进程。

from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .base import BackendName, NetworkLevel, SandboxRequest, SandboxResult
from .paths import PathPolicy, scan_path_violations, tokenize

logger = logging.getLogger('harness.tools.sandbox')

#: 沙箱注入的固定环境变量（**不是**从 os.environ 继承的）。
#:
#: 为什么要有这几个：子进程要能跑 sh、找到基本命令、要能正确处理中文输出。
#: 这些都是「执行前提」，不是「环境泄漏」。
_BASE_ENV: dict[str, str] = {
    'PATH': '/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin',
    'LANG': 'C.UTF-8',
    'LC_ALL': 'C.UTF-8',
    'HOME': '/tmp',
    'SHELL': '/bin/sh',
}

#: violation 的取值（**稳定契约**，fault 测试按这些字符串断言）
#:
#: path:escape   路径越界（../ 穿越 / 符号链接逃逸 / 引用根外路径）
#: path:denied   往只读区域写
#: net:deny      出网被拦（域名不在 allowlist，或 network=none 却要出网）
#: cmd:denied    命令本身被策略拒绝（如空命令）
VIOLATION_PATH_ESCAPE = 'path:escape'
VIOLATION_PATH_DENIED = 'path:denied'
VIOLATION_NET_DENY = 'net:deny'
VIOLATION_CMD_DENIED = 'cmd:denied'

#: 从命令行里抠出「可能的网络目标」。
#:
#: 覆盖三种常见写法：
#:   curl http://example.com/x     → URL
#:   curl example.com               → 裸域名（作为 curl/wget 的参数）
#:   nc example.com 443             → 裸域名
#: 判定刻意保守：只认「像域名或 IP」的 token，宁可漏判也不误杀
#: （误杀会让正常的 echo /path/to/file 变成拒绝执行）。
_URL_RE = re.compile(
    r'\b(?:[a-z][a-z0-9+.\-]*)://'
    r'(?P<host>[A-Za-z0-9_.\-]+(?::\d+)?)', re.IGNORECASE)
_BARE_HOST_RE = re.compile(
    r'^(?P<host>[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?'
    r'(?:\.[A-Za-z0-9\-]+)+)(?::\d+)?$')
_IP_RE = re.compile(r'^\d{1,3}(?:\.\d{1,3}){3}$')

#: **一定要连出去**的网络客户端：这些命令的唯一用途就是访问远端。
#:
#: network=none 时见到它们就拒；network=allowlist 时它们必须能解析出
#: 目标主机，否则无法确认在白名单内 → 也拒。
_NETWORK_CLIENTS = frozenset({
    'curl', 'wget', 'nc', 'ncat', 'netcat', 'telnet', 'ssh', 'scp', 'sftp',
    'rsync', 'ftp', 'tftp', 'aria2c', 'http', 'httpie',
})

#: **可能**连出去的工具：本地用法与联网用法都有。
#:
#: `git status` / `pip list` / `go build` 是纯本地操作 ——
#: 把它们在 network=none 下一律拒掉，是在制造「沙箱太吵」而不是在提升安全。
#: 所以只当命令里**出现明确的 URL / 目标主机**时才按网络操作判定。
_MAY_FETCH = frozenset({
    'git', 'pip', 'pip3', 'npm', 'yarn', 'pnpm', 'apt', 'apt-get', 'yum',
    'dnf', 'go', 'cargo', 'docker', 'pipenv', 'poetry', 'uv', 'mvn', 'gradle',
})

#: 裸域名只在这些命令后面才算「网络目标」
_NETWORK_COMMANDS = _NETWORK_CLIENTS | _MAY_FETCH


@dataclass
class PreparedCommand:
    """一条命令**经沙箱批准后**的执行计划。

    为什么要有这一层（而不是只有 run()）：
      - run() 是**一次性**的：跑完就返回结果。适合「跑一条命令拿结果」。
      - 但 shell 工具是**会话**语义：命令还在跑的时候要能写 stdin、
        要能中途 terminate、要能边跑边把输出流给 UI。
        这些都需要拿到「活着的子进程」，一次性接口给不了。
      - prepare() 把两边的共同部分抽出来：**沙箱决定 argv / env / cwd，
        也就是「这条命令允许以什么形式跑」**；谁来 fork 出进程由调用方决定。

    violation 非空 = 这条命令被拒了，**不要执行**。
    """

    argv: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str = ''
    violation: str = ''
    detail: str = ''
    #: 这份计划是不是「降级档」产出的。
    #:
    #: restricted 档永远为 True；namespaced 档在探测不到强隔离后端、
    #: 退化到 restricted 时也为 True。调用方据此如实标注 backend/degraded。
    degraded: bool = True

    @property
    def denied(self) -> bool:
        return bool(self.violation)


@dataclass
class ResourceLimits:
    """子进程的资源上限。

    设计取舍：这些是「防 runaway」的上限，不是「防攻击」的上限。
    真正防攻击靠路径/网络判定 + 上层审批。

    address_space 默认 0 = 不限制。
    修复说明：RLIMIT_AS 会打爆 Node / Java / Go 这类运行时 ——
    它们**预留**（reserve）巨量虚拟地址空间，2G 的 VSZ 上限会让
    「正常跑一次构建」变成 Cannot allocate memory。沙箱因为越界
    而把工具搞坏，比少一条限制更糟。需要时按构造参数显式开启。
    """

    cpu: int = 60
    file_size: int = 128 * 1024 * 1024
    open_files: int = 256
    core: int = 0
    address_space: int = 0

    def ulimit_script(self) -> str:
        """生成 sh 里的 ulimit 前缀。

        为什么用 `sh -c 'ulimit ...; exec "$@"'` 而不是 preexec_fn：
          - preexec_fn 在**多线程**宿主里有死锁风险（fork 之后、子进程里
            再进 Python 代码，可能撞上别的线程持有的锁）。shell 工具
            恰恰是多线程场景。
          - `exec "$@"` 保留原始 argv，不多一层 shell，也不改参数语义。
        注意 ulimit -f 的单位：POSIX sh 是 512 字节块，bash 是 1024 字节块。
        这里取两种解释里都成立（偏严）的值。
        """
        parts = [
            f'ulimit -t {self.cpu}',
            f'ulimit -f {max(1, self.file_size // 512)}',
            f'ulimit -n {self.open_files}',
            f'ulimit -c {self.core}',
        ]
        if self.address_space:
            parts.append(f'ulimit -v {self.address_space // 1024}')
        return '; '.join(parts) + '; exec "$@"'


def _shell_for_limits() -> str:
    """找一个能设 ulimit 的 POSIX shell。"""
    for candidate in ('/bin/sh', '/usr/bin/sh'):
        if os.path.exists(candidate):
            return candidate
    return shutil.which('sh') or '/bin/sh'


def build_sandbox_env(req: SandboxRequest) -> dict[str, str]:
    """组装子进程环境变量。

    硬要求：**不继承 os.environ**。只放行：
      - 沙箱自己的固定基线（PATH / LANG / …）
      - SandboxRequest.env 里声明过的变量

    为什么这条不能松：os.environ 里通常有 API key、数据库口令、
    代理配置。继承过去 = 把凭据交给模型控制的进程 —— 那模型只要
    `env > /tmp/x` 就能把密钥抄走，审批与审计全都白做。
    """
    env = dict(_BASE_ENV)
    for key, value in (req.env or {}).items():
        if not isinstance(key, str) or not key:
            continue
        env[key] = str(value)
    return env


def extract_network_targets(tokens: Sequence[str]) -> list[str]:
    """从命令行里抽出网络目标（域名或 IP）。

    两条规则：
      1. 任何 token 里带 scheme:// → 取 host 部分。
      2. 紧跟在「明显带网络意图的命令」后面的裸域名/IP → 也算。
    """
    targets: list[str] = []
    expect_host = False
    for token in tokens:
        if token.startswith('-'):
            continue
        match = _URL_RE.search(token)
        if match:
            host = match.group('host')
            if ':' in host:
                host = host.rsplit(':', 1)[0]
            targets.append(host.lower())
            expect_host = False
            continue
        if expect_host:
            host_match = _BARE_HOST_RE.match(token)
            if host_match:
                targets.append(host_match.group('host').lower())
            expect_host = False
            continue
        if os.path.basename(token) in _NETWORK_COMMANDS:
            expect_host = True
    return targets


def uses_network_client(tokens: Sequence[str]) -> bool:
    """命令行里是否出现了「一定要连出去」的网络客户端。"""
    for token in tokens:
        if token.startswith('-'):
            continue
        if os.path.basename(token) in _NETWORK_CLIENTS:
            return True
    return False


def host_allowed(host: str, allowlist: Iterable[str]) -> bool:
    """host 是否在白名单里。

    匹配规则：
      - 完全相等
      - 白名单项以 '.' 开头 → 匹配该域及其子域（'.example.com' 放行 a.example.com）
      - 白名单项本身是 IP → 只精确匹配
    """
    host = host.lower().rstrip('.')
    for entry in allowlist:
        entry = str(entry).lower().strip().rstrip('.')
        if not entry:
            continue
        if entry.startswith('.'):
            if host == entry[1:] or host.endswith(entry):
                return True
            continue
        if host == entry:
            return True
        # 'example.com' 也放行 'a.example.com'（子域）
        if not _IP_RE.match(entry) and host.endswith('.' + entry):
            return True
    return False


def kill_process_tree(proc: subprocess.Popen) -> None:
    """杀掉子进程及其子孙。

    修复说明（来自 harness/tools/shell.py 的教训）：os.getpgid 在某些情况下
    返回 0（内核线程），而 killpg(0, sig) 等于给**调用者自己**的进程组发信号 ——
    pytest 进程会被自己的 SIGTERM 打死。所以这里先校验 pgid 可信，
    不可信就退回 proc.kill()。
    """
    if proc.poll() is not None:
        return
    try:
        pgid = os.getpgid(proc.pid)
    except (OSError, AttributeError):
        pgid = 0
    try:
        own = os.getpgid(0)
    except OSError:
        own = 0
    if pgid and pgid > 0 and pgid != own:
        try:
            os.killpg(pgid, signal.SIGKILL)
            return
        except OSError:
            pass
    try:
        proc.kill()
    except OSError:
        pass


def decode_output(data: bytes) -> str:
    """子进程输出解码（容忍非法字节）。"""
    if data.startswith(b'\xef\xbb\xbf'):
        data = data[3:]
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return data.decode('utf-8', errors='replace')


def effective_command_line(cmd: Sequence[str], shell: bool) -> str:
    """算出 shell 模式下真正要交给 sh -c 的命令行。

    规则（必须写死，否则调用方一多元素就静默出错）：
      - 只有一个元素 → 它**就是**整条命令行，原样使用。
        （工具层传的就是一条命令字符串：`cmd=['cat ../../etc/passwd']`）
      - 多个元素 → 它们是 argv，逐个 shell 引用后拼接。
        （`cmd=['sh','-c','echo hi']` → `sh -c 'echo hi'`；
          不引用的话 `echo hi` 会被拆成两个词，语义全错。）

    修复说明：早期版本对多元素直接用空格 join，于是
    `cmd=['sh','-c','echo hi']` 变成 `sh -c echo hi` ——
    引号丢了，命令跑出来的结果跟调用方要的完全不是一回事。
    """
    if not cmd:
        return ''
    if len(cmd) == 1:
        return cmd[0]
    return ' '.join(shlex.quote(str(part)) for part in cmd)


def check_network(level: NetworkLevel, tokens: Sequence[str],
                  allowlist: Sequence[str]) -> str:
    """网络判定。返回空串表示放行，否则返回可读的原因。

    两个档位的拦法不同，理由要说清楚：

    network='none'
        命中「明确带网络意图的命令」（curl/wget/nc/…）或出现 URL 就拒绝。
        即便命令没写域名也拒 —— network=none 的语义是「不许出网」，
        而不是一个域名一个域名地核。

    network='allowlist'
        按域名核。命中白名单放行，不在白名单拒绝。
        白名单为空 = 一个域名都不放行（默认拒绝）。

    设计取舍（务必如实理解）：restricted 档**没有**内核级断网能力。
    上面拦的是「命令行里写明的出网目标」。命令自己 `import socket` 直连
    IP 是拦不住的 —— 那种情况只能靠上层审批 + 事后审计兜底。
    这正是 restricted 永远 degraded=True 的原因：它没有假装自己是防火墙。
    """
    if level == 'full':
        return ''
    targets = extract_network_targets(tokens)
    if level == 'none':
        if targets:
            return f'net:deny: network=none but command targets {targets[0]}'
        if uses_network_client(tokens):
            return 'net:deny: network=none but command is a network client'
        return ''
    for host in targets:
        if not host_allowed(host, allowlist):
            return f'net:deny: {host} not in allowlist'
    if uses_network_client(tokens) and not targets:
        # 用了网络客户端但看不出目标域名 → 无法确认在白名单内 → 拒绝
        return ('net:deny: network command without a resolvable target '
                'host cannot be checked against the allowlist')
    return ''


def record_violation(code: str, detail: str = '', *,
                     degraded: bool = False, context: Any = None) -> bool:
    """把沙箱拒绝**结构化**记录到 ToolContext.violations（供 ToolGuard 读走）。

    为什么在沙箱这一层记，而不是要求每个工具自己记：
      guard.py 的注释里写着「如果每个调用点自己插一刀，迟早有一个调用点忘了」。
      沙箱拒绝就发生在沙箱这一层 —— 在这里记一次，
      所有用沙箱的工具（不管是谁写的）都自动带上审计记录。
      工具层仍可自己补一条更贴切的记录，重复的会被去重。

    去重规则：同一次拒绝里 (code, detail) 相同就算同一条。
    谁先记谁生效 —— 沙箱自己记的更准（它知道自己有没有降级）。

    约定（lead 定的）：工具 append 到 ToolContext.violations，
    ToolGuard 在执行后读走并发 tool_blocked / audit.denied。
    """
    try:
        # 延迟 import：沙箱包不依赖 tools.context 的导入时机，
        # 免得在包初始化顺序上打架。
        from ..context import current_context
        # 优先用调用方给的上下文；没有就用当前上下文
        # （ToolGuard 注入的是当前上下文那条）。
        ctx = context if context is not None else current_context()
        violations = getattr(ctx, 'violations', None)
        if violations is None:
            return False
        for existing in violations:
            if (isinstance(existing, dict)
                    and existing.get('code') == code
                    and existing.get('detail') == detail):
                return True
        violations.append({'code': code, 'detail': detail, 'kind': 'sandbox',
                           'degraded': bool(degraded)})
        return True
    except Exception:  # noqa: BLE001 - 审计通道不该拖垮工具执行
        return False


def path_violation_code(violations) -> str:
    """把路径违规列表映射成一个稳定的 violation 码。"""
    if violations and all(v.kind == 'write_denied' for v in violations):
        return VIOLATION_PATH_DENIED
    return VIOLATION_PATH_ESCAPE


async def run_subprocess(argv: Sequence[str], *, env: dict[str, str],
                         cwd: str, stdin_data: bytes | None,
                         timeout: float) -> tuple[int, bytes, bytes, bool]:
    """跑一个子进程并收齐输出。

    用 asyncio 的子进程 API 而不是 subprocess.Popen + communicate：
      - communicate 是**阻塞**的，放进 async 函数里会把整个事件循环卡住
        （一次 60 秒的命令 = 整个 turn 卡 60 秒）。
      - 阻塞版还拿不到取消语义：上层 interrupt 只能等超时。
    这里让 stdout/stderr 各跑一个读任务，主任务只等进程退出，
    这样 timeout 与 CancelledError 都能立刻杀掉进程树。

    返回 (exit_code, stdout, stderr, timed_out)。
    """
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE if stdin_data is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        # 独立进程组：超时时能整组回收，且不会误伤调用者
        # （对比 infra/observability 的 killpg(0) 事故，见 kill_process_tree）。
        start_new_session=(os.name != 'nt'),
    )
    if stdin_data is not None and proc.stdin is not None:
        try:
            proc.stdin.write(stdin_data)
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass

    out_task = asyncio.create_task(proc.stdout.read())
    err_task = asyncio.create_task(proc.stderr.read())
    timed_out = False
    try:
        try:
            await asyncio.wait_for(proc.wait(), timeout=max(0.1, timeout))
        except asyncio.TimeoutError:
            timed_out = True
            _kill_async(proc)
            await proc.wait()
        except asyncio.CancelledError:
            # 上层中断：立刻收尸，别留孤儿进程
            _kill_async(proc)
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
            raise
        out, err = await out_task, await err_task
    finally:
        for task in (out_task, err_task):
            if not task.done():
                task.cancel()
    exit_code = proc.returncode if proc.returncode is not None else 1
    if timed_out:
        exit_code = 124
    return exit_code, out or b'', err or b'', timed_out


def _kill_async(proc) -> None:
    """杀掉 asyncio 子进程及其子孙。"""
    try:
        kill_process_tree(proc)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 - 收尾不该再抛
        pass


class RestrictedSandbox:
    """默认降级档沙箱后端。

    用法::

        sandbox = RestrictedSandbox()
        result = await sandbox.run(SandboxRequest(
            cmd=['cat', '../../etc/passwd'],
            cwd='/workspace',
            writable_paths=('/workspace',),
        ))
        assert result.violation == 'path:escape'

    构造参数：

    network_allowlist  network='allowlist' 时允许的域名（支持 '.example.com' 形式）
    policy             路径白名单策略；不传则按 req 里的路径字段推导
    system_read_paths  额外允许读的系统目录（默认只有解释器与动态库那几个）
    limits             资源上限
    """

    name: BackendName = 'restricted'

    def __init__(self, *,
                 network_allowlist: Sequence[str] = (),
                 allowlist: Sequence[str] | None = None,
                 policy: PathPolicy | None = None,
                 system_read_paths: Sequence[str] | None = None,
                 limits: ResourceLimits | None = None,
                 ) -> None:
        # allowlist 是 network_allowlist 的别名 —— 两个名字都收，
        # 免得调用方（fault 测试 / 上层装配）猜错。
        if allowlist is not None:
            network_allowlist = allowlist
        self.network_allowlist = tuple(network_allowlist)
        self._policy = policy
        self._system_read_paths = (
            tuple(system_read_paths) if system_read_paths is not None else None)
        self._limits = limits or ResourceLimits()

    @property
    def degraded(self) -> bool:
        """restricted 档**永远**是降级档。

        策划案 §3.3.5：降级必须如实标注。它没有内核级隔离，
        只有「执行前判定」，所以它不能自称「在沙箱里」。
        """
        return True

    @property
    def default_network_level(self) -> NetworkLevel:
        """这个后端默认用哪一档网络策略。

        配了 allowlist 就用 allowlist 档，没配就是 none 档 ——
        免得「配了白名单但请求写 none」让白名单变成死配置。
        """
        return 'allowlist' if self.network_allowlist else 'none'

    # ── 策略推导 ─────────────────────────────────────────
    def policy_for(self, req: SandboxRequest) -> PathPolicy:
        """从请求推出路径白名单。

        规则：
          - writable_paths：可读可写
          - readonly_paths：可读不可写
          - cwd：额外算一个可读可写根（工作目录本身就是这一轮的工作区）
          - system_read_paths：默认系统只读目录
        """
        if self._policy is not None:
            base = self._policy
            system = base.system_read
        else:
            system = (self._system_read_paths
                      if self._system_read_paths is not None
                      else PathPolicy().system_read)
            base = PathPolicy(system_read=system)
        readonly = tuple(base.readonly) + tuple(req.readonly_paths)
        writable = tuple(base.writable) + tuple(req.writable_paths)
        # 工作目录是否算可写根由请求说了算（只读档要求它不可写）。
        cwd_writable = base.cwd_writable and req.cwd_writable
        return PathPolicy(readonly=readonly, writable=writable,
                           system_read=system, cwd_writable=cwd_writable)

    # ── 主入口 ───────────────────────────────────────────
    def prepare(self, req: SandboxRequest) -> PreparedCommand:
        """判定一条命令能不能跑，并给出**经沙箱批准后**的执行计划。

        流程（顺序不能换）：
          1. 路径判定 → 越界直接拒绝，**不执行**
          2. 网络判定 → 非白名单直接拒绝，**不执行**
          3. 组装环境变量白名单与 ulimit 包装后的 argv

        判定与执行**分离**是刻意的：判定是纯函数式的，好测；
        执行怎么 fork（一次性 run 还是活着的会话）由调用方决定。
        """
        cmd = list(req.cmd or [])
        if not cmd:
            return PreparedCommand(violation=VIOLATION_CMD_DENIED,
                                   detail='empty command')
        cwd = req.cwd or os.getcwd()
        policy = self.policy_for(req)

        # shell 模式下命令行是一整串，先切成 token 再判定；
        # 非 shell 模式 argv 本身就是 token。
        tokens = (tokenize(effective_command_line(cmd, req.shell))
                  if req.shell else list(cmd))
        violations = scan_path_violations(tokens, policy, base=cwd, cwd=cwd)
        if violations:
            detail = '; '.join(str(v) for v in violations)
            logger.warning('sandbox denied command by path policy: %s', detail)
            code = path_violation_code(violations)
            record_violation(code, detail, degraded=self.degraded)
            return PreparedCommand(cwd=cwd, violation=code, detail=detail)

        net_denial = check_network(req.network, tokens, self.network_allowlist)
        if net_denial:
            logger.warning('sandbox denied command by network policy: %s',
                           net_denial)
            record_violation(VIOLATION_NET_DENY, net_denial,
                             degraded=self.degraded)
            return PreparedCommand(cwd=cwd, violation=VIOLATION_NET_DENY,
                                   detail=net_denial)

        return PreparedCommand(argv=self.build_argv(cmd, req),
                               env=build_sandbox_env(req),
                               cwd=cwd, degraded=True)

    async def run(self, req: SandboxRequest) -> SandboxResult:
        """执行一次受限命令（一次性）。

        判定 → 执行 → 收集输出 → 按 max_output 截断。
        """
        started = time.monotonic()
        prepared = self.prepare(req)
        if prepared.denied:
            return SandboxResult(
                exit_code=126,
                stderr=f'sandbox: {prepared.violation}: {prepared.detail}',
                duration_ms=(time.monotonic() - started) * 1000.0,
                violation=prepared.violation, degraded=self.degraded,
                backend=self.name)

        argv = prepared.argv
        env = prepared.env
        cwd = prepared.cwd
        try:
            exit_code, out, err, timed_out = await run_subprocess(
                argv, env=env, cwd=cwd, stdin_data=req.stdin,
                timeout=req.timeout)
        except asyncio.CancelledError:
            raise
        except OSError as error:
            return SandboxResult(
                exit_code=127, stderr=f'sandbox: spawn failed: {error}',
                duration_ms=(time.monotonic() - started) * 1000.0,
                degraded=self.degraded, backend=self.name)

        stdout = decode_output(out)
        stderr = decode_output(err)
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
            degraded=self.degraded,
            backend=self.name,
            timed_out=timed_out,
        )

    # ── 内部 ───────────────────────────────────────────
    def build_argv(self, cmd: Sequence[str], req: SandboxRequest) -> list[str]:
        """组装 argv。

        shell=True 时 cmd 是**整条命令行**（一整串），交给 sh -c；
        否则 cmd 就是 argv 本身，直接执行。

        两种模式都套一层 `sh -c 'ulimit ...; exec "$@"'`：
        ulimit 必须在 exec 之前设好，而 exec "$@" 保留原始 argv。
        """
        inner = self.inner_argv(cmd, req)
        return [_shell_for_limits(), '-c', self._limits.ulimit_script(),
                'sh', *inner]

    def inner_argv(self, cmd: Sequence[str], req: SandboxRequest) -> list[str]:
        """沙箱内部真正要跑的命令（不含 ulimit 包装）。"""
        if req.shell:
            return ['/bin/sh', '-c', effective_command_line(cmd, req.shell)]
        return list(cmd)


__all__ = [
    'PreparedCommand',
    'record_violation',
    'ResourceLimits',
    'effective_command_line',
    'RestrictedSandbox',
    'VIOLATION_CMD_DENIED',
    'VIOLATION_NET_DENY',
    'VIOLATION_PATH_DENIED',
    'VIOLATION_PATH_ESCAPE',
    'build_sandbox_env',
    'check_network',
    'decode_output',
    'extract_network_targets',
    'host_allowed',
    'kill_process_tree',
    'path_violation_code',
    'run_subprocess',
    'uses_network_client',
]
