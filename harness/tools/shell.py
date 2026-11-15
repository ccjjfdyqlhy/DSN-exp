# harness/tools/shell.py
# Persistent shell sessions as a generic tool.
#
# One shell per worker thread: "execute" runs a command to completion
# (killing the previous one first), "read" returns incremental output,
# "write" feeds stdin, "terminate" kills the process tree.  While a command
# runs, every output line also goes to the turn's live sink from the
# ToolContext, so a UI can stream output as it is produced instead of
# waiting for the command to finish.

from __future__ import annotations

import ctypes
import locale
import os
import subprocess
import threading
import time
import weakref
from dataclasses import dataclass, field
from typing import Callable

from .base import Tool
from .context import ToolContext, current_context, resolve_path

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
    """Owns one shell session per worker thread and reaps them on shutdown."""

    def __init__(self) -> None:
        self._local = threading.local()
        self._sessions: weakref.WeakSet[ShellSession] = weakref.WeakSet()
        self._lock = threading.RLock()

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
        proc = session.proc

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
                '<shell_tool_metadata>command execution timed out</shell_tool_metadata>')
        if interrupted:
            session.output.append(
                '<shell_tool_metadata>command interrupted</shell_tool_metadata>')
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


_SHELL_DESCRIPTION = (
    'Persistent shell session with sub-commands:\n'
    + ('- Platform: Windows cmd.exe. Use cd/dir, or invoke powershell '
       '-NoProfile -Command explicitly; do not use Unix pwd/ls.\n'
       if os.name == 'nt' else '- Platform: POSIX shell.\n')
    + '- execute: run a command (kills the previous one). Default timeout 48s; '
      'a timeout is reported with <shell_tool_metadata>.\n'
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
                       sessions: ShellSessions | None = None) -> Tool:
    """Build the sub-command shell Tool bound to a ShellSessions owner.

    Args:
        name: tool name as the model sees it.
        sessions: the session owner; one instance is created per tool when
            omitted.  Share one instance to let several tool names (or a
            root tool and its sub-agents) drive the same per-thread shells.

    Returns:
        A Tool whose handler resolves cwd / interrupt / live_sink from the
        running turn's ToolContext.
    """
    owner = sessions if sessions is not None else ShellSessions()

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

    return Tool(name=name, description=_SHELL_DESCRIPTION,
                parameters=_SHELL_PARAMETERS, handler=handler)
