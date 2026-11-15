# tests/test_coding_agent_tools.py
# The coding app's tool suite, on top of the harness mechanisms.

from __future__ import annotations

import os
import subprocess
import time
from threading import Event, Thread

import pytest

from apps.coding_agent.core_tools import core_tools, install_core_tools
from harness.tools.context import ToolContext, pop_context, push_context
from harness.tools.registry import ManagedToolRegistry
from harness.tools.shell import ShellSessions


@pytest.fixture()
def workspace(tmp_path):
    return str(tmp_path)


def _registry(workspace, **kwargs):
    registry = ManagedToolRegistry()
    sessions = install_core_tools(registry, **kwargs)
    return registry


def _push(workspace, interrupt=None, sink=None):
    context = ToolContext(cwd=workspace)
    if interrupt is not None:
        context.interrupt = interrupt
    if sink is not None:
        context.live_sink = sink
    return push_context(context)


# ── file tools ───────────────────────────────────────────────────────

def test_read_write_edit_roundtrip(workspace):
    registry = _registry(workspace)
    token = _push(workspace)
    try:
        text, diff, error = registry.execute('write', {
            'path': 'a.txt', 'content': 'hello\n'})
        assert not error and 'Wrote 6 bytes' in text
        text, _, error = registry.execute('read', {'path': 'a.txt'})
        assert not error and '     1: hello' in text
        # edit with a non-unique old string is rejected
        text, _, error = registry.execute('edit', {
            'path': 'a.txt', 'old': 'l', 'new': 'L'})
        assert error and 'matches of old_string' in text
        text, diff, error = registry.execute('edit', {
            'path': 'a.txt', 'old': 'hello', 'new': 'world'})
        assert not error and 'Replaced 1 occurrence' in text
        assert diff is not None and '-hello' in diff.unified and '+world' in diff.unified
        # the diff is appended to the model text
        assert '<file_diff path="a.txt"' in text
    finally:
        pop_context(token)


def test_read_offset_limit(workspace):
    registry = _registry(workspace)
    token = _push(workspace)
    try:
        registry.execute('write', {'path': 'n.txt',
                                   'content': '\n'.join(f'line{i}' for i in range(10))})
        text, _, _ = registry.execute('read', {'path': 'n.txt', 'offset': 3, 'limit': 2})
        assert 'line2' in text and 'line3' in text and 'line4' not in text
        assert 'showing 2 of 10 lines' in text
    finally:
        pop_context(token)


def test_glob_grep_ls(workspace):
    registry = _registry(workspace)
    token = _push(workspace)
    try:
        os.makedirs(os.path.join(workspace, 'pkg'))
        registry.execute('write', {'path': 'pkg/m.py', 'content': 'alpha = 1\n'})
        text, _, _ = registry.execute('glob', {'pattern': '**/*.py'})
        assert 'pkg/m.py' in text
        text, _, _ = registry.execute('grep', {'pattern': 'alpha', 'include': '*.py'})
        # rg (when installed) prefixes ./ and omits the space; both shapes
        # carry path:line:match
        assert 'm.py:1' in text and 'alpha = 1' in text
        text, _, _ = registry.execute('ls', {})
        assert 'pkg/' in text
    finally:
        pop_context(token)


def test_diff_tool_reports_worktree(workspace):
    registry = _registry(workspace)
    token = _push(workspace)
    try:
        subprocess.run(['git', 'init', '-q'], cwd=workspace, check=True)
        text, _, _ = registry.execute('diff', {})
        assert text == '(no working-tree changes)'
        registry.execute('write', {'path': 'new.py', 'content': 'x = 1\n'})
        text, _, _ = registry.execute('diff', {})
        assert '+x = 1' in text
    finally:
        pop_context(token)


def test_view_image_returns_marker(workspace):
    import struct
    import zlib
    registry = _registry(workspace)
    token = _push(workspace)
    try:
        # a 1x1 red PNG, built by hand so the test needs no fixtures
        def chunk(tag, payload):
            return (struct.pack('>I', len(payload)) + tag + payload
                    + struct.pack('>I', zlib.crc32(tag + payload) & 0xFFFFFFFF))
        ihdr = chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
        idat = chunk(b'IDAT', zlib.compress(b'\x00\xff\x00\x00'))
        iend = chunk(b'IEND', b'')
        (workspace / 'p.png') if False else None
        with open(os.path.join(workspace, 'p.png'), 'wb') as f:
            f.write(b'\x89PNG\r\n\x1a\n' + ihdr + idat + iend)
        text, _, error = registry.execute('view_image', {'path': 'p.png'})
        assert not error
        assert '[image: sessions/images/' in text
    finally:
        pop_context(token)


# ── bash sub-protocol ────────────────────────────────────────────────

def test_bash_execute_read_terminate(workspace):
    registry = _registry(workspace)
    token = _push(workspace)
    try:
        text, _, error = registry.execute('bash', {'sub': 'execute',
                                                   'command': 'echo out1'})
        assert not error and 'out1' in text
        # execute blocks until exit, so a follow-up read has nothing buffered
        text, _, _ = registry.execute('bash', {'sub': 'read'})
        assert text == '(no output)'
        # terminate without a live process reports the idle state
        text, _, _ = registry.execute('bash', {'sub': 'terminate'})
        assert text == '(no running process)'
        text, _, _ = registry.execute('bash', {'sub': 'execute', 'command': 'echo out2'})
        assert 'out2' in text
    finally:
        pop_context(token)


def test_bash_live_sink_streams_lines(workspace):
    registry = _registry(workspace)
    lines: list[str] = []
    token = _push(workspace, sink=lines.append)
    try:
        registry.execute('bash', {'sub': 'execute', 'command': 'echo one; echo two'})
        assert 'one' in lines and 'two' in lines
    finally:
        pop_context(token)


def test_bash_interrupt_flag(workspace):
    registry = _registry(workspace)
    interrupt = Event()

    def setter():
        time.sleep(0.3)
        interrupt.set()
    Thread(target=setter, daemon=True).start()
    token = _push(workspace, interrupt=interrupt)
    try:
        text, _, _ = registry.execute('bash', {
            'sub': 'execute', 'command': 'sleep 30', 'timeout': 20})
        assert 'interrupted' in text
        assert '<bash_tool_metadata>' in text    # the app-level tag survives
    finally:
        pop_context(token)


def test_bash_timeout_metadata(workspace):
    registry = _registry(workspace)
    token = _push(workspace)
    try:
        started = time.monotonic()
        text, _, _ = registry.execute('bash', {
            'sub': 'execute', 'command': 'sleep 30', 'timeout': 1})
        assert time.monotonic() - started < 10
        assert 'timed out' in text
    finally:
        pop_context(token)


def test_shared_shell_sessions_across_registries(workspace):
    sessions = ShellSessions(metadata_tag='bash_tool_metadata')
    first = ManagedToolRegistry()
    second = ManagedToolRegistry()
    install_core_tools(first, shell=sessions)
    install_core_tools(second, shell=sessions)
    token = _push(workspace)
    try:
        first.execute('bash', {'sub': 'execute', 'command': 'echo shared'})
        text, _, _ = second.execute('bash', {'sub': 'read'})
        assert text == '(no output)'    # same per-thread session, already drained
    finally:
        pop_context(token)
        sessions.shutdown()


def test_suite_shape():
    tools = core_tools()
    names = [tool.name for tool in tools]
    assert names == ['read', 'view_image', 'write', 'edit', 'glob', 'grep',
                     'bash', 'fetch', 'diff', 'ls']
    flags = {tool.name: tool for tool in tools}
    assert flags['read'].read_only and flags['write'].snapshot
    assert flags['view_image'].vision_only
    assert not flags['bash'].read_only
