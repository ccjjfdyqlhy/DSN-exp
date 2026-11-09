# apps/dsn_study_cli/tui.py
# 终端交互 —— 标准库 termios/tty/select（无第三方依赖）。
#
# 与 dsn CLI 同形：cbreak 模式 + 非阻塞单键读取 + 原始模式下的行输入。

from __future__ import annotations

import os
import select
import sys

_IS_WIN = os.name == "nt"

if not _IS_WIN:
    import termios
    import tty


class TerminalState:
    """保存/恢复 termios 状态（VLC 等会破坏终端标志 —— study_CLI 无 VLC，
    保留恢复逻辑纯粹是为了 Ctrl+C 后的终端卫生）。"""

    def __init__(self):
        self.fd = sys.stdin.fileno()
        self._saved = None
        if not _IS_WIN:
            try:
                self._saved = termios.tcgetattr(self.fd)
            except Exception:   # noqa: BLE001 - 管道输入下无 termios
                self._saved = None

    def set_cbreak(self):
        if not _IS_WIN and self._saved is not None:
            try:
                tty.setcbreak(self.fd)
            except Exception:   # noqa: BLE001
                pass

    def restore(self):
        if not _IS_WIN and self._saved is not None:
            try:
                termios.tcsetattr(self.fd, termios.TCSADRAIN, self._saved)
            except Exception:   # noqa: BLE001
                pass


_STATE: TerminalState | None = None


def _state() -> TerminalState:
    global _STATE
    if _STATE is None:
        _STATE = TerminalState()
    return _STATE


def raw_mode():
    """上下文管理器：进入/退出 cbreak 模式。"""
    class _Ctx:
        def __enter__(self):
            s = _state()
            s.set_cbreak()
            return s

        def __exit__(self, *exc):
            s = _state()
            s.restore()
            return False

    return _Ctx()


def read_key(timeout: float = 0.1) -> str | None:
    """非阻塞读单键。无按键返回 None；Ctrl+C 抛 KeyboardInterrupt。"""
    if _IS_WIN:
        import msvcrt
        if msvcrt.kbhit():
            return msvcrt.getch().decode("utf-8", errors="ignore")
        return None
    fd = _state().fd
    r, _, _ = select.select([fd], [], [], timeout)
    if not r:
        return None
    ch = os.read(fd, 1).decode("utf-8", errors="ignore")
    if ch == "\x03":
        raise KeyboardInterrupt
    return ch


def raw_input(prompt: str = "") -> str:
    """cbreak 模式下的行输入（退格可用；Ctrl+D 返回空）。"""
    state = _state()
    state.restore()   # 行输入回显交给终端本身
    try:
        try:
            return input(prompt) if prompt else input()
        except EOFError:
            return ""
    finally:
        state.set_cbreak()
