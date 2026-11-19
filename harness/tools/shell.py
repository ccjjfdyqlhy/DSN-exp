# harness/tools/shell.py
# Persistent shell sessions as a generic tool.
#
# One shell per worker thread: "execute" runs a command to completion
# (killing the previous one first), "read" returns incremental output,
# "write" feeds stdin, "terminate" kills the process tree.  While a command
# runs, every output line also goes to the turn's live sink from the
# ToolContext, so a UI can stream output as it is produced instead of
# waiting for the command to finish.
#
# ── rc0 改造：执行权交给沙箱 ──────────────────────────────────
#
# 现状问题（策划案 §2.3）：这个文件直接 subprocess，模型能以**当前用户权限**
# 执行任意 shell —— 无审批、无审计、无路径边界。沙箱就是补这一层。
#
# 改造方式（签名与行为全部保持不变，既有测试必须仍然全绿）：
#   - 执行前向沙箱后端要一份「执行计划」（argv / env / cwd）；
#     沙箱说不行（路径越界 / 出网不在白名单）就**不执行**，直接回报拒绝原因。
#   - 沙箱后端从 ToolContext.sandbox 取（由 ToolGuard 注入）。
#     没有沙箱时走原来的 legacy 路径，并打显著告警 —— 静默降级等于
#     「以为自己在沙箱里」（策划案 §3.3.5 明令禁止）。
#   - 沙箱用哪个档位由 ToolSpec.sandbox / ToolSpec.network 决定。
#
# 为什么沙箱不接管「会话」这一层：
#   本工具的价值在**交互式会话**（边跑边读、写 stdin、中途 kill 进程树），
#   而 Sandbox 协议是一次性 run()。所以分工是：
#     沙箱 = 决定「这条命令允许以什么形式跑」（argv/env/cwd 与是否放行）
#     本文件 = 负责会话生命周期（流式输出、stdin、超时、kill 进程树）
#   这样既拿到沙箱的判定力，又不丢掉交互能力。

from __future__ import annotations

import ctypes
import locale
import logging
import os
import subprocess
import threading
import time
import weakref
from dataclasses import dataclass, field
from typing import Any, Callable

from .base import Tool
from .context import ToolContext, current_context, resolve_path
from .registry import AnnotatedTool

logger = logging.getLogger('harness.tools.shell')

_MAX_OUTPUT_LINES = 5_000
_DEFAULT_TIMEOUT = 48.0


@dataclass(eq=False)
class ShellSession:
    proc: subprocess.Popen[bytes] | None = None
    output: list[str] = field(default_factory=list)
    read_pos: int = 0
    workdir: str = '.'
    reader: threading.Thread | None = None


def _console_output_codepage() -> str:
    if os.name != 'nt':
        return ''
    try:
        code_page = ctypes.windll.kernel32.GetConsoleOutputCP()
        return f'cp{code_page}' if code_page else ''
    except Exception:
        return ''


def _decode_output(data: bytes) -> str:
    if data.startswith(b'\xef\xbb\xbf'):
        data = data[3:]
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        encoding = _console_output_codepage() or locale.getpreferredencoding(False) or 'utf-8'
        return data.decode(encoding, errors='replace')


def _close_process_pipes(proc: subprocess.Popen[bytes]) -> None:
    for pipe in (proc.stdin, proc.stdout, proc.stderr):
        if pipe is not None and not pipe.closed:
            try:
                pipe.close()
            except OSError:
                pass


def _kill_tree(proc: subprocess.Popen[bytes]) -> None:
    """Kill the shell and every child it spawned (shell=True on Windows)."""
    if os.name == 'nt':
        try:
            subprocess.run(
                ['taskkill', '/F', '/T', '/PID', str(proc.pid)],
                capture_output=True, timeout=5,
            )
            return
        except Exception:
            pass
    else:
        try:
            import signal
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            return
        except Exception:
            pass
    try:
        proc.kill()
    except Exception:
        pass


class ShellSessions:
    """Owns one shell session per worker thread and reaps them on shutdown.

    rc0 起，本类**不再自己决定**一条命令能不能跑：
    沙箱后端（ToolContext.sandbox，由 ToolGuard 注入）先给一份执行计划，
    放行才执行。沙箱不在场时走 legacy 路径并打显著告警。
    """

    def __init__(self, *, metadata_tag: str = 'shell_tool_metadata',
                 sandbox: Any = None) -> None:
        self._local = threading.local()
        self._sessions: weakref.WeakSet[ShellSession] = weakref.WeakSet()
        self._lock = threading.RLock()
        # the timeout / interrupt marker is wrapped in this tag; applications
        # that have UI conventions around a specific tag can rename it
        self._metadata_tag = metadata_tag
        # 显式注入的沙箱后端；为 None 时每次执行都从 ToolContext 取
        # （ToolGuard 的注入点是 ToolContext.sandbox）。
        self._sandbox = sandbox
        # legacy 降级只告警一次 —— 每次调用都刷屏会淹掉真正的错误。
        self._legacy_warned = False

    # ── 沙箱接入 ─────────────────────────────────────────
    def _resolve_sandbox(self, context: ToolContext | None) -> Any:
        """找到本次执行该用的沙箱后端。

        优先级：显式注入 > ToolContext.sandbox（ToolGuard 注入）。
        """
        if self._sandbox is not None:
            return self._sandbox
        ctx = context or current_context()
        return getattr(ctx, 'sandbox', None)

    def _warn_legacy_once(self) -> None:
        """没有沙箱后端时显著告警（只一次）。

        为什么不静默：策划案 §3.3.5「降级必须如实标注」。
        没有沙箱 = 命令以**当前用户权限**裸跑，与改造前无异 ——
        这件事必须让人知道，而不是藏在日志的 DEBUG 里。
        """
        if self._legacy_warned:
            return
        self._legacy_warned = True
        logger.warning(
            'shell 工具未挂沙箱后端：以当前用户权限直接执行命令'
            '（无路径边界、无环境变量白名单、无审计）。'
            '请装配 ToolGuard 并注入 sandbox 后端。')

    def _sandbox_plan(self, backend: Any, *, command: str, workdir: str,
                      timeout: float, context: ToolContext | None):
        """向沙箱要一份执行计划。

        返回 PreparedCommand；被拒时 plan.denied 为 True，plan.violation
        是稳定的违规码（path:escape / net:deny / …），由调用方回报给模型。

        网络档位从 ToolSpec.network 取（未声明 = none，默认拒绝）。
        """
        from .sandbox.base import SandboxRequest

        spec = getattr(context, 'tool_spec', None)
        network = getattr(spec, 'network', None) or 'none'
        # 工具自己声明的沙箱档位决定请求的路径口径：
        #   readonly  工作目录只读 —— 不把它算成可写根
        #   workspace 工作目录可写 —— 写边界由后端的可写根决定
        #   none      没有边界 —— 工作目录照旧可写
        # 不在这里判断，是因为「这条命令准不准写」是**声明**的事：
        # 同一份声明在策略、审批、审计三处都读得到。
        level = str(getattr(spec, 'sandbox', '') or '')
        read_only = level == 'readonly'
        request = SandboxRequest(
            cmd=[command],
            workspace_id=getattr(context, 'workspace_id', '') or '',
            timeout=timeout,
            env={},
            stdin=None,
            network=network,
            readonly_paths=(workdir,) if (read_only and workdir) else (),
            writable_paths=() if read_only else ((workdir,) if workdir else ()),
            cwd=workdir,
            shell=True,
            cwd_writable=not read_only,
        )
        prepare = getattr(backend, 'prepare', None)
        if prepare is None:
            # 后端只实现了 run()（一次性协议），没有 prepare()。
            # 这种后端没法参与会话式执行 —— 退回 legacy 并告警，
            # 绝不「假装经过了沙箱」。
            return None
        return prepare(request)

    def _record_violation(self, context: ToolContext | None, backend: Any,
                          code: str, detail: str) -> None:
        """把违规**结构化**递上去（ToolGuard 读走并发 audit.denied）。

        为什么不用「从返回文本里正则嗅探违规码」：
        那是把审计建在文案上 —— 改一次文案就丢一次审计。
        约定（lead 定的）：工具 append 到 ToolContext.violations，
        ToolGuard 在执行后读走并发 tool_blocked / audit.denied。

        为什么不用抛异常：
        沙箱拒绝要给模型一句人能读的文本（「Error: 沙箱拒绝执行（path:escape）」），
        抛异常会破坏「工具失败仍然是 ToolResult」的既有约定。
        两条通道各司其职：文本给模型，结构化记录给审计。

        注意：只在**真的被沙箱拒绝**时才记 —— legacy 路径不记，
        否则没人读走的默认列表会随调用次数一直长。
        """
        from .sandbox.restricted import record_violation
        record_violation(code, detail,
                         degraded=bool(getattr(backend, 'degraded', False)),
                         context=context)

    def _execute_planned(self, session: ShellSession, plan: Any, *,
                         live_sink: Callable[[str], None] | None,
                         timeout: float,
                         context: ToolContext | None = None) -> str:
        """按沙箱给的执行计划起进程，并沿用原有的流式读取逻辑。"""
        argv = list(plan.argv)
        env = dict(plan.env)
        env.setdefault('PYTHONIOENCODING', 'utf-8')
        env.setdefault('PYTHONUTF8', '1')
        cwd = plan.cwd or session.workdir
        try:
            session.proc = subprocess.Popen(
                argv,
                cwd=cwd,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=(os.name != 'nt'),
            )
        except Exception as error:  # noqa: BLE001
            session.proc = None
            return f'Error: {error}'
        return self._pump(session, live_sink=live_sink, timeout=timeout,
                          context=context)

    def session(self) -> ShellSession:
        session = getattr(self._local, 'session', None)
        if session is None:
            session = ShellSession()
            self._local.session = session
            with self._lock:
                self._sessions.add(session)
        return session

    def kill(self, session: ShellSession | None = None) -> None:
        active = session or self.session()
        reader = active.reader
        active.reader = None
        if active.proc:
            proc = active.proc
            _kill_tree(proc)
            try:
                proc.wait(timeout=3)
            except Exception:
                pass
            _close_process_pipes(proc)
            active.proc = None
        if reader is not None and reader is not threading.current_thread():
            # Reap the old reader before the next command reuses the buffer, so
            # a killed process cannot append stale lines to the new output.
            reader.join(timeout=1)

    def shutdown(self) -> None:
        with self._lock:
            sessions = list(self._sessions)
        for session in sessions:
            self.kill(session)

    # ── sub-commands ────────────────────────────────────────
    def execute(self, command: str, *, workdir: str = '.',
                timeout: float = _DEFAULT_TIMEOUT,
                context: ToolContext | None = None) -> str:
        """执行一条命令。

        rc0 改造后的顺序：
          1. 先向沙箱要执行计划 —— 越界/出网被拒就**不执行**，回报原因。
          2. 放行则按计划起进程，沿用原有的流式读取 / 超时 / 中断逻辑。
          3. 没有沙箱后端 → legacy 路径 + 显著告警（只一次）。
        """
        session = self.session()
        self.kill(session)
        session.workdir = resolve_path(str(workdir or '.'))
        try:
            timeout = float(timeout)
        except (TypeError, ValueError):
            timeout = _DEFAULT_TIMEOUT
        session.output = []
        session.read_pos = 0
        context = context or current_context()
        live_sink = context.live_sink

        backend = self._resolve_sandbox(context)
        if backend is not None:
            plan = self._sandbox_plan(backend, command=command,
                                      workdir=session.workdir,
                                      timeout=timeout, context=context)
            if plan is not None:
                if getattr(plan, 'denied', False):
                    # 被沙箱拒绝：**不执行**。把稳定的违规码回报给模型，
                    # 它才知道是被边界挡了而不是命令本身坏了。
                    violation = getattr(plan, 'violation', 'sandbox:denied')
                    detail = getattr(plan, 'detail', '')
                    self._record_violation(context, backend, violation, detail)
                    session.output = []
                    session.read_pos = 0
                    message = f'Error: 沙箱拒绝执行（{violation}）'
                    if detail:
                        message += f': {detail}'
                    session.output.append(message)
                    return self.read()
                return self._execute_planned(session, plan,
                                             live_sink=live_sink,
                                             timeout=timeout,
                                             context=context)
            # 后端不支持 prepare() → 落到 legacy，但必须告警。
            self._warn_legacy_once()
        else:
            self._warn_legacy_once()

        try:
            session.proc = subprocess.Popen(
                command, shell=True, cwd=session.workdir,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'},
                start_new_session=(os.name != 'nt'),
            )
        except Exception as error:
            session.proc = None
            return f'Error: {error}'
        return self._pump(session, live_sink=live_sink, timeout=timeout,
                          context=context)

    def _pump(self, session: ShellSession, *,
              live_sink: Callable[[str], None] | None,
              timeout: float,
              context: ToolContext | None = None) -> str:
        """读取子进程输出直到结束，处理超时与中断。

        从 execute() 里抽出来是为了让 legacy 与沙箱两条路径共用同一套
        流式读取 / 超时 / 中断逻辑 —— 两份实现必然漂移。
        """
        proc = session.proc
        if proc is None:
            return 'Error: no running process'
        # 中断信号来自 ToolContext；没传就用当前上下文。
        context = context or current_context()

        def reader() -> None:
            assert proc.stdout is not None
            for line in iter(proc.stdout.readline, b''):
                try:
                    decoded = _decode_output(line).rstrip('\r\n')
                    session.output.append(decoded)
                    if len(session.output) > _MAX_OUTPUT_LINES:
                        drop = len(session.output) - _MAX_OUTPUT_LINES
                        del session.output[:drop]
                        session.read_pos = max(0, session.read_pos - drop)
                    # The sink is captured in this thread's closure: contextvars
                    # do not propagate to new threads automatically.
                    if live_sink is not None:
                        live_sink(decoded)
                except Exception:
                    pass

        thread = threading.Thread(target=reader, daemon=True)
        session.reader = thread
        thread.start()
        interrupted = False
        timed_out = False
        deadline = time.monotonic() + max(0.1, timeout)
        while True:
            try:
                proc.wait(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                if context.interrupt.is_set():
                    interrupted = True
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    break
        if interrupted or timed_out:
            _kill_tree(proc)
            # Reap the dead process before reporting: otherwise the pipes stay
            # open and every later read claims the command is still running.
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
        thread.join(timeout=1)
        if timed_out:
            session.output.append(
                f'<{self._metadata_tag}>command execution timed out</{self._metadata_tag}>')
        if interrupted:
            session.output.append(
                f'<{self._metadata_tag}>command interrupted</{self._metadata_tag}>')
        if proc.poll() is not None:
            _close_process_pipes(proc)
            if session.proc is proc:
                session.proc = None
        if session.reader is thread:
            session.reader = None
        return self.read()

    def read(self) -> str:
        session = self.session()
        new_lines = session.output[session.read_pos:]
        session.read_pos = len(session.output)
        if not new_lines:
            if session.proc and session.proc.poll() is None:
                return '(process still running, no new output)'
            return '(no output)'
        return '\n'.join(new_lines)

    def write(self, text: str) -> str:
        session = self.session()
        if not session.proc or session.proc.stdin is None:
            return 'Error: no running process'
        try:
            session.proc.stdin.write((text + '\n').encode('utf-8'))
            session.proc.stdin.flush()
            return f'Wrote {len(text)} bytes to stdin'
        except Exception as error:
            return f'Error writing to stdin: {error}'

    def terminate(self) -> str:
        session = self.session()
        if not session.proc:
            return '(no running process)'
        self.kill(session)
        return 'Process terminated'


def _shell_description(metadata_tag: str) -> str:
    return (
        'Persistent shell session with sub-commands:\n'
        + ('- Platform: Windows cmd.exe. Use cd/dir, or invoke powershell '
           '-NoProfile -Command explicitly; do not use Unix pwd/ls.\n'
           if os.name == 'nt' else '- Platform: POSIX shell.\n')
        + f'- execute: run a command (kills the previous one). Default timeout 48s; '
          f'a timeout is reported with <{metadata_tag}>.\n'
        + '- read: incremental output since the last read.\n'
        + '- write: send input to stdin (a newline is appended).\n'
        + '- terminate: kill the running process.'
    )

_SHELL_PARAMETERS = {
    'type': 'object',
    'properties': {
        'sub': {'type': 'string', 'enum': ['execute', 'read', 'write', 'terminate']},
        'command': {'type': 'string', 'description': 'Shell command (execute)'},
        'workdir': {'type': 'string', 'description': 'Working directory (execute)'},
        'timeout': {'type': 'integer', 'description': 'Timeout seconds (execute)'},
        'input': {'type': 'string', 'description': 'Stdin text (write)'},
    },
    'required': ['sub'],
}


def session_shell_tool(name: str = 'shell', *,
                       sessions: ShellSessions | None = None,
                       metadata_tag: str = 'shell_tool_metadata',
                       sandbox: Any = None) -> Tool:
    """Build the sub-command shell Tool bound to a ShellSessions owner.

    Args:
        name: tool name as the model sees it.
        sessions: the session owner; one instance is created per tool when
            omitted.  Share one instance to let several tool names (or a
            root tool and its sub-agents) drive the same per-thread shells.
        metadata_tag: tag wrapping timeout / interrupt markers in the output.
        sandbox: 显式指定沙箱后端；省略时由 ToolGuard 经
            ToolContext.sandbox 注入（推荐做法）。

    Returns:
        An AnnotatedTool whose handler resolves cwd / interrupt / live_sink
        from the running turn's ToolContext.
    """
    owner = sessions if sessions is not None else ShellSessions(
        metadata_tag=metadata_tag, sandbox=sandbox)

    def handler(**params):
        sub = str(params.get('sub', 'execute'))
        if sub == 'execute':
            return owner.execute(str(params.get('command', '')),
                                 workdir=str(params.get('workdir', '') or '.'),
                                 timeout=params.get('timeout', _DEFAULT_TIMEOUT))
        if sub == 'read':
            return owner.read()
        if sub == 'write':
            return owner.write(str(params.get('input', '')))
        if sub == 'terminate':
            return owner.terminate()
        return f'Error: unknown shell sub-command: {sub}'

    return AnnotatedTool(name=name, description=_shell_description(metadata_tag),
                         parameters=_SHELL_PARAMETERS, handler=handler)
