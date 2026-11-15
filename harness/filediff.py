# harness/filediff.py
# File snapshots, unified diffs, and Git work-tree inspection.
#
# Tools and UIs share this: a registry snapshots a file around a write and
# appends the diff to the tool result, and a transcript can carry the same
# FileDiff for display.

from __future__ import annotations

import difflib
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

MAX_SNAPSHOT_BYTES = 1_000_000
MAX_DIFF_LINES = 400


@dataclass(frozen=True)
class FileSnapshot:
    exists: bool
    text: str | None
    omitted: bool = False


@dataclass(frozen=True)
class FileDiff:
    path: str
    unified: str
    additions: int
    deletions: int
    omitted: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.unified) or self.omitted


@dataclass(frozen=True)
class DiffLine:
    kind: str      # meta | hunk | add | del | ctx
    text: str
    old_number: int | None = None
    new_number: int | None = None


def snapshot_file(path: str | os.PathLike[str]) -> FileSnapshot:
    file_path = Path(path)
    if not file_path.is_file():
        return FileSnapshot(False, None)
    try:
        if file_path.stat().st_size > MAX_SNAPSHOT_BYTES:
            return FileSnapshot(True, None, omitted=True)
        content = file_path.read_bytes()
        if b'\x00' in content:
            return FileSnapshot(True, None, omitted=True)
        return FileSnapshot(True, content.decode('utf-8-sig', errors='replace'))
    except OSError:
        return FileSnapshot(True, None, omitted=True)


def make_file_diff(path: str, before: FileSnapshot, after: FileSnapshot,
                   max_lines: int = MAX_DIFF_LINES) -> FileDiff | None:
    if before.omitted or after.omitted:
        if before.exists != after.exists or before.omitted != after.omitted:
            return FileDiff(path, '', 0, 0, omitted=True)
        return None
    old_text = before.text or ''
    new_text = after.text or ''
    if before.exists == after.exists and old_text == new_text:
        return None
    raw_lines = list(difflib.unified_diff(
        old_text.splitlines(), new_text.splitlines(),
        fromfile=f'a/{path}', tofile=f'b/{path}', lineterm='', n=3,
    ))
    additions = sum(1 for line in raw_lines
                    if line.startswith('+') and not line.startswith('+++'))
    deletions = sum(1 for line in raw_lines
                    if line.startswith('-') and not line.startswith('---'))
    omitted = len(raw_lines) > max_lines
    if omitted:
        head = max_lines * 2 // 3
        tail = max_lines - head
        raw_lines = [
            *raw_lines[:head],
            f'... <diff truncated: {len(raw_lines) - max_lines} lines omitted> ...',
            *raw_lines[-tail:],
        ]
    return FileDiff(path, '\n'.join(raw_lines), additions, deletions, omitted)


def format_diff_for_model(file_diff: FileDiff | None) -> str:
    if file_diff is None:
        return ''
    if file_diff.omitted and not file_diff.unified:
        return f'\n<file_diff path="{file_diff.path}" omitted="true" />'
    return (
        f'\n<file_diff path="{file_diff.path}" additions="{file_diff.additions}" '
        f'deletions="{file_diff.deletions}">\n{file_diff.unified}\n</file_diff>'
    )


def diff_lines(file_diff: FileDiff) -> list[DiffLine]:
    """Split a unified diff into typed lines with old/new line numbers."""
    hunk_re = re.compile(r'^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@')
    result: list[DiffLine] = []
    old_line: int | None = None
    new_line: int | None = None
    for line in file_diff.unified.splitlines():
        match = hunk_re.match(line)
        if match:
            old_line, new_line = int(match.group(1)), int(match.group(2))
            result.append(DiffLine('hunk', line))
            continue
        if line.startswith('---') or line.startswith('+++'):
            result.append(DiffLine('meta', line))
            continue
        if line.startswith('+'):
            result.append(DiffLine('add', line[1:], new_number=new_line))
            if new_line is not None:
                new_line += 1
            continue
        if line.startswith('-'):
            result.append(DiffLine('del', line[1:], old_number=old_line))
            if old_line is not None:
                old_line += 1
            continue
        if line.startswith(' '):
            result.append(DiffLine('ctx', line[1:],
                                   old_number=old_line, new_number=new_line))
            if old_line is not None:
                old_line += 1
            if new_line is not None:
                new_line += 1
            continue
        result.append(DiffLine('meta', line))
    return result


def git_worktree_diff(cwd: str = '.', path: str = '') -> FileDiff | None:
    """Return a safe, hook-free diff of the working tree, including untracked files."""
    root = Path(cwd)
    try:
        inside = _run_git(root, ['rev-parse', '--is-inside-work-tree']).strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if inside != 'true':
        return None
    try:
        tracked = _run_git(root, [
            'diff', '--no-ext-diff', '--no-textconv', '--no-color', '--',
            *([path] if path else []),
        ], allow_one=True)
        untracked = _run_git(root, [
            'ls-files', '--others', '--exclude-standard', '-z',
            *(['--', path] if path else []),
        ])
    except (OSError, subprocess.SubprocessError):
        return None
    parts = [tracked]
    null_path = 'NUL' if os.name == 'nt' else '/dev/null'
    for entry in filter(None, untracked.split('\0')):
        try:
            parts.append(_run_git(root, [
                'diff', '--no-index', '--no-ext-diff', '--no-textconv',
                '--no-color', '--', null_path, entry,
            ], allow_one=True))
        except (OSError, subprocess.SubprocessError):
            continue
    unified = ''.join(parts).strip()
    if not unified:
        return None
    lines = unified.splitlines()
    additions = sum(1 for line in lines
                    if line.startswith('+') and not line.startswith('+++'))
    deletions = sum(1 for line in lines
                    if line.startswith('-') and not line.startswith('---'))
    omitted = len(lines) > MAX_DIFF_LINES
    if omitted:
        head = MAX_DIFF_LINES * 2 // 3
        tail = MAX_DIFF_LINES - head
        lines = [*lines[:head], '... <diff truncated> ...', *lines[-tail:]]
    return FileDiff(path or '.', '\n'.join(lines), additions, deletions, omitted)


def _run_git(cwd: Path, arguments: list[str], allow_one: bool = False) -> str:
    command = [
        'git',
        '-c', 'core.hooksPath=NUL' if os.name == 'nt' else 'core.hooksPath=/dev/null',
        '-c', 'core.quotePath=false',
        *arguments,
    ]
    result = subprocess.run(
        command, cwd=cwd, capture_output=True, text=True, encoding='utf-8',
        errors='replace', timeout=30,
    )
    allowed = {0, 1} if allow_one else {0}
    if result.returncode not in allowed:
        raise subprocess.SubprocessError(result.stderr.strip() or 'git command failed')
    return result.stdout
