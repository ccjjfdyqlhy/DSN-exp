# harness/tools/context.py
# Per-turn execution context for tools.
#
# Tools learn where they run (cwd), whether the user interrupted, and where
# incremental output goes (live_sink) from this context instead of globals.
# contextvars keep concurrent turns / sub-agents isolated: one turn's live
# sink must never receive another turn's shell output.

from __future__ import annotations

import contextvars
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


def push_context(context: ToolContext):
    return _CURRENT.set(context)


def pop_context(token) -> None:
    _CURRENT.reset(token)


def resolve_path(path: str) -> str:
    """Resolve a tool path against the context's working directory."""
    base = current_context().cwd or '.'
    text = os.path.expanduser(str(path)) if path else ''
    if not text:
        return base
    if os.path.isabs(text):
        return text
    return os.path.normpath(os.path.join(base, text))
