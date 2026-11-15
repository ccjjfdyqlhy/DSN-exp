# tests/test_tools_runtime.py
# Tool runtime facilities: per-turn contexts, the managed registry and the
# persistent shell sessions.

from __future__ import annotations

import asyncio
import time
from threading import Event, Thread

import pytest

from harness.filediff import make_file_diff, snapshot_file
from harness.tools.base import Tool
from harness.tools.context import (
    ToolContext, current_context, pop_context, push_context, resolve_path,
)
from harness.tools.registry import AnnotatedTool, ManagedToolRegistry
from harness.tools.shell import ShellSessions, session_shell_tool


# ── ToolContext ──────────────────────────────────────────────────────

def test_context_push_pop_and_lazy_default():
    token = push_context(ToolContext(cwd='/tmp/turn-a'))
    try:
        assert current_context().cwd == '/tmp/turn-a'
        assert resolve_path('x.txt') == '/tmp/turn-a/x.txt'
        assert resolve_path('/abs/y.txt') == '/abs/y.txt'
        assert resolve_path('') == '/tmp/turn-a'
    finally:
        pop_context(token)
    # without a push, a per-thread default is created lazily
    default = current_context()
    assert isinstance(default.interrupt, Event)
    assert default.live_sink is None


def test_context_isolates_threads():
    import threading
    seen: dict[str, str] = {}

    def worker():
        seen['cwd'] = current_context().cwd

    token = push_context(ToolContext(cwd='/tmp/turn-main'))
    try:
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        assert seen['cwd'] in ('.', str(__import__('os').getcwd()))  # fresh default
        assert current_context().cwd == '/tmp/turn-main'             # main untouched
    finally:
        pop_context(token)


# ── ManagedToolRegistry ──────────────────────────────────────────────

def _writer_tool():
    from harness.tools.context import resolve_path

    def handler(path, content):
        # real tools resolve their paths through the turn's ToolContext
        with open(resolve_path(path), 'w', encoding='utf-8') as stream:
            stream.write(content)
        return f'wrote {path}'
    return AnnotatedTool(name='setfile', description='write a file',
                         parameters={'type': 'object', 'properties': {
                             'path': {'type': 'string'},
                             'content': {'type': 'string'}},
                             'required': ['path', 'content']},
                         handler=handler, snapshot=True)


def test_registry_source_tracking():
    registry = ManagedToolRegistry()
    registry.register(_writer_tool(), source='skill')
    assert registry.source_of('setfile') == 'skill'
    assert registry.names_by_source('skill') == ['setfile']
    registry.register(_writer_tool(), replace=True, source='mcp:docs')
    assert registry.unregister_source_prefix('mcp:') == ['setfile']
    assert registry.get('setfile') is None
    assert registry.unregister_source('skill') == []


def test_registry_vision_filter():
    registry = ManagedToolRegistry()
    registry.register(AnnotatedTool(
        name='peek_image', description='look', vision_only=True,
        parameters={'type': 'object', 'properties': {}},
        handler=lambda: 'img'))
    registry.register(AnnotatedTool(
        name='plain', description='text',
        parameters={'type': 'object', 'properties': {}},
        handler=lambda: 'txt'))
    assert 'peek_image' not in [s['name'] for s in registry.build_schema(vision=False)]
    assert 'peek_image' in [s['name'] for s in registry.build_schema(vision=True)]


def test_registry_execute_snapshots_write(tmp_path):
    registry = ManagedToolRegistry()
    registry.register(_writer_tool())
    target = tmp_path / 'f.txt'
    target.write_text('before\n', encoding='utf-8')
    token = push_context(ToolContext(cwd=str(tmp_path)))
    try:
        text, diff, error = registry.execute('setfile',
                                             {'path': 'f.txt', 'content': 'after\n'})
        assert not error and diff is not None
        assert '-before' in diff.unified and '+after' in diff.unified
        assert '<file_diff path="f.txt"' in text
        # failures keep the engine convention and carry no diff spam
        registry.register(AnnotatedTool(
            name='boom', description='fails',
            parameters={'type': 'object', 'properties': {}},
            handler=lambda: 'Error: nope'))
        text, diff, error = registry.execute('boom', {})
        assert error and text == 'Error: nope'
        # exceptions come back normalized by Tool.run as Error: text
        registry.register(AnnotatedTool(
            name='crash', description='raises',
            parameters={'type': 'object', 'properties': {}},
            handler=lambda: 1 / 0))
        text, _, error = registry.execute('crash', {})
        assert error and text.startswith('Error:')
        # unknown tool
        text, _, error = registry.execute('ghost', {})
        assert error and 'unknown tool' in text
    finally:
        pop_context(token)


def test_tool_run_async_offloads_sync_handlers(tmp_path):
    registry = ManagedToolRegistry()
    registry.register(_writer_tool())
    target = tmp_path / 'a.txt'

    async def runner():
        tool = registry.require('setfile')
        return await tool.run_async(path=str(target), content='hi')

    result = asyncio.run(runner())
    assert result.success is True
    assert 'hi' in target.read_text(encoding='utf-8')


# ── ShellSessions ────────────────────────────────────────────────────

@pytest.fixture()
def shell(tmp_path):
    sessions = ShellSessions()
    token = push_context(ToolContext(cwd=str(tmp_path)))
    try:
        yield sessions
    finally:
        pop_context(token)
        sessions.shutdown()


def test_shell_execute_read_terminate(shell):
    text = shell.execute('echo out1')
    assert 'out1' in text
    assert shell.read() == '(no output)'          # execute blocks until exit
    assert shell.terminate() == '(no running process)'
    text = shell.execute('echo out2')
    assert 'out2' in text


def test_shell_live_sink_streams_lines(shell):
    lines: list[str] = []
    token = push_context(ToolContext(cwd='.', live_sink=lines.append))
    try:
        shell.execute('echo one; echo two')
        assert 'one' in lines and 'two' in lines
    finally:
        pop_context(token)


def test_shell_interrupt_flag(shell):
    interrupt = Event()

    def setter():
        time.sleep(0.3)
        interrupt.set()
    Thread(target=setter, daemon=True).start()
    token = push_context(ToolContext(cwd='.', interrupt=interrupt))
    try:
        text = shell.execute('sleep 30', timeout=20)
        assert 'interrupted' in text
    finally:
        pop_context(token)


def test_shell_timeout_metadata(shell):
    started = time.monotonic()
    text = shell.execute('sleep 30', timeout=1)
    assert time.monotonic() - started < 10
    assert 'timed out' in text


def test_shell_write_needs_running_process(shell):
    assert shell.write('x') == 'Error: no running process'


def test_session_shell_tool_dispatch():
    tool = session_shell_tool(name='bash')
    assert tool.name == 'bash'
    result = tool.run(sub='execute', command='echo via-tool')
    assert result.success is True
    assert 'via-tool' in str(result.output)
    result = tool.run(sub='nonsense')
    assert result.success is True    # handler returns an Error: string
    assert str(result.output).startswith('Error: unknown shell sub-command')
