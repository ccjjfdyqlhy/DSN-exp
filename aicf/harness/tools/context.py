# harness/tools/context.py
# Per-turn execution context for tools.
#
# Tools learn where they run (cwd), whether the user interrupted, and where
# incremental output goes (live_sink) from this context instead of globals.
# contextvars keep concurrent turns / sub-agents isolated: one turn's live
# sink must never receive another turn's shell output.

from __future__ import annotations

import contextvars
import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ToolContext:
    cwd: str = '.'
    interrupt: threading.Event = field(default_factory=threading.Event)
    live_sink: Callable[[str], None] | None = None
    agent: str = 'root'
    #: 本次运行的依赖（ToolDeps 实例）。用户自定义工具通过
    #: ``current_deps().extra["..."]`` 拿自己的应用状态（数据库、连接、缓存…）。
    deps: Any = None
    #: 沙箱后端。工具需要起子进程时从这里拿 —— 由 ToolGuard 注入。
    #: 没有它时工具自己起进程（legacy 行为）。
    sandbox: Any = None
    #: 本次调用的工具契约（ToolSpec）。由 ToolGuard 注入，
    #: 工具据此读到自己声明的副作用等级与网络档位。
    tool_spec: Any = None
    #: 本次调用产生的**结构化违规记录**。
    #:
    #: 为什么要有这个通道：沙箱拒绝执行时，工具需要给模型一句人能读的
    #: 文本（「Error: 沙箱拒绝执行（path:escape）」），但审计需要结构化的
    #: 违规码与原因。两者不能靠「从返回文本里正则嗅探」来连接 ——
    #: 那是把审计建在文案上，改一次文案就丢一次审计。
    #:
    #: 工具 append，ToolGuard 读。默认空列表（每次 ToolContext 一个新的）。
    violations: list = field(default_factory=list)
    #: 会话 / 轮次标识。工具（或沙箱）据此定位工作区与幂等键。
    session_id: str = ''
    turn_id: str = ''


logger = logging.getLogger(__name__)

_CURRENT: contextvars.ContextVar[ToolContext | None] = contextvars.ContextVar(
    'harness_tool_context', default=None)


def current_context() -> ToolContext:
    """Return this thread's context, creating one lazily.

    A single shared default instance would let one thread's ``live_sink`` leak
    into another thread that never pushed a context of its own.
    """
    context = _CURRENT.get()
    if context is None:
        context = ToolContext()
        _CURRENT.set(context)
    return context


def current_sandbox() -> Any:
    """Return the sandbox backend the guard injected for this call.

    None means no backend is attached, so the tool runs with the current
    user's permissions. Callers must treat that as a degraded path and say so.
    """
    return getattr(current_context(), 'sandbox', None)


def current_deps() -> Any:
    """当前这次运行的依赖（ToolDeps）。

    没注入时返回 None —— 工具要自己判空，不要假设一定有。
    """
    return current_context().deps


def push_context(context: ToolContext):
    return _CURRENT.set(context)


def pop_context(token) -> None:
    """Restore the context a push replaced.

    A token can only be reset in the context it was created in.  When a turn
    is cancelled while a tool call is in flight (the session is closing while
    an approval is pending, for instance), the cleanup can run in another
    context -- and the old code turned that into a failed turn with a
    "was created in a different Context" traceback.  Losing the restore is
    harmless; failing the turn over it is not.
    """
    try:
        _CURRENT.reset(token)
    except ValueError:
        logger.debug('tool context token belongs to another context; skipped')


def resolve_path(path: str) -> str:
    """Resolve a tool path against the context's working directory."""
    base = current_context().cwd or '.'
    text = os.path.expanduser(str(path)) if path else ''
    if not text:
        return base
    if os.path.isabs(text):
        return text
    return os.path.normpath(os.path.join(base, text))
