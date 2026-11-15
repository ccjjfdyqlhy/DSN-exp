# apps/coding_agent/core_tools.py
# The coding app's tool suite: files, search, shell, HTTP and diffs.
#
# These are APPLICATION tools, built entirely from harness mechanisms:
# harness.tools.shell (persistent sessions), harness.tools.context (per-turn
# cwd / interrupt / live sink), harness.images (image markers), harness.net
# (proxy-aware HTTP) and the ManagedToolRegistry snapshot-diff execution.
# Naming and error convention ("Error: ..." text the model recovers from)
# follow the suite the coding app was built around.

from __future__ import annotations

import fnmatch
import glob as glob_module
import os
import re
import subprocess
import urllib.error
import urllib.request
from typing import Any, Callable

from harness.filediff import git_worktree_diff
from harness.images import (
    MAX_IMAGE_BYTES, ImageStore, image_info, image_marker, sniff_media_type,
)
from harness.tools.context import current_context, resolve_path
from harness.tools.registry import AnnotatedTool
from harness.tools.shell import ShellSessions, session_shell_tool
from infra import net

_GREP_SKIP_DIRS = frozenset({
    '.git', '.hg', '.svn', 'node_modules', '__pycache__', '.venv', 'venv',
    'dist', 'build', 'out', 'target', '.idea', '.vscode', '.svelte-kit',
    '.next', '.nuxt', '.cache', 'coverage', '.pytest_cache', '.mypy_cache',
    '.ruff_cache',
})
_GREP_MAX_FILE = 10 * 1024 * 1024
_GREP_MAX_RESULTS = 200
_rg_path: str | None | bool = False


def _dict_handler(func: Callable[[dict[str, Any]], str]) -> Callable[..., str]:
    """Adapt an args-dict handler to the harness Tool handler(**params) shape."""
    def wrapper(**kwargs):
        return func(kwargs)
    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    return wrapper


def _base_dir() -> str:
    """Working directory of the running tool call ('' means the process cwd)."""
    return current_context().cwd or '.'


def _resolve(path: str) -> str:
    return resolve_path(path)


def _display_path(path: str) -> str:
    """Shorten an absolute result path back to a cwd-relative one when possible."""
    try:
        relative = os.path.relpath(path, _base_dir())
    except ValueError:
        return path
    if relative.startswith('..'):
        return path
    return relative.replace('\\', '/')


def _read(args: dict[str, Any]) -> str:
    raw_path = str(args['path'])
    path = _resolve(raw_path)
    offset = args.get('offset')
    limit = args.get('limit')
    if not os.path.isfile(path):
        return f'Error: file not found: {raw_path}'
    try:
        with open(path, encoding='utf-8-sig', errors='replace') as stream:
            lines = stream.readlines()
    except Exception as error:
        return f'Error reading {raw_path}: {error}'
    total = len(lines)
    start = 0
    if offset is not None:
        start = max(0, int(offset) - 1)
        lines = lines[start:]
    if limit is not None:
        lines = lines[:int(limit)]
    base = start + 1
    out = ''.join(f'{number:6}: {line}' for number, line in enumerate(lines, base))
    if (offset is not None or limit is not None) and total > start + len(lines):
        out += f'\n(showing {len(lines)} of {total} lines)'
    return out or ('(no lines in range)' if (offset is not None or limit is not None)
                   else '(empty file)')


def _write(args: dict[str, Any]) -> str:
    raw_path = str(args['path'])
    path = _resolve(raw_path)
    content = str(args['content'])
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    encoding = 'utf-8'
    try:
        if os.path.isfile(path):
            with open(path, 'rb') as existing:
                if existing.read(3) == b'\xef\xbb\xbf':
                    encoding = 'utf-8-sig'
        with open(path, 'w', encoding=encoding, newline='') as stream:
            stream.write(content)
    except Exception as error:
        return f'Error writing {raw_path}: {error}'
    written = len(content.encode('utf-8'))
    if encoding == 'utf-8-sig':
        written += 3
    return f'Wrote {written} bytes to {raw_path}'


def _edit(args: dict[str, Any]) -> str:
    raw_path = str(args['path'])
    path = _resolve(raw_path)
    old = str(args['old'])
    new = str(args['new'])
    if not os.path.isfile(path):
        return f'Error: file not found: {raw_path}'
    try:
        with open(path, 'rb') as probe:
            has_bom = probe.read(3) == b'\xef\xbb\xbf'
        encoding = 'utf-8-sig' if has_bom else 'utf-8'
        with open(path, encoding=encoding) as stream:
            content = stream.read()
    except Exception as error:
        return f'Error reading {raw_path}: {error}'
    count = content.count(old)
    if count == 0:
        return f'Error: old_string not found in {raw_path}'
    if count > 1:
        return (f'Error: found {count} matches of old_string in {raw_path}; '
                f'provide more context to make it unique')
    new_content = content.replace(old, new, 1)
    try:
        with open(path, 'w', encoding=encoding, newline='') as stream:
            stream.write(new_content)
    except Exception as error:
        return f'Error writing {raw_path}: {error}'
    return f'Replaced 1 occurrence in {raw_path}'


def _glob(args: dict[str, Any]) -> str:
    pattern = str(args['pattern'])
    joined = os.path.join(_base_dir(), os.path.expanduser(pattern))
    try:
        matches = glob_module.glob(joined, recursive=True)
    except Exception as error:
        return f'Error in glob: {error}'
    if not matches:
        return '(no matches)'
    relative = sorted(_display_path(match) for match in matches)
    return '\n'.join(dict.fromkeys(relative))


def _find_rg() -> str | None:
    global _rg_path
    if _rg_path is False:
        import shutil
        _rg_path = shutil.which('rg')
    return _rg_path


def _grep_include(path: str, include: str) -> bool:
    if fnmatch.fnmatch(os.path.basename(path), include):
        return True
    relative = os.path.relpath(path, _base_dir()).replace('\\', '/')
    if fnmatch.fnmatch(relative, include):
        return True
    try:
        from pathlib import PurePath
        return PurePath(relative).match(include)
    except Exception:
        return False


def _grep_rg(rg: str, args: dict[str, Any]) -> str | None:
    command = [rg, '--no-heading', '--line-number', '--color', 'never',
               '--max-count', str(_GREP_MAX_RESULTS), str(args['pattern'])]
    if args.get('include'):
        command += ['-g', str(args['include'])]
    command += ['.']
    try:
        process = subprocess.run(command, capture_output=True, timeout=30,
                                 cwd=_base_dir())
    except Exception:
        return None
    if process.returncode == 2:
        return None
    if process.returncode == 1 or not process.stdout:
        return '(no matches)'
    text = process.stdout.decode('utf-8', errors='replace').rstrip('\n')
    return '\n'.join(text.split('\n')[:_GREP_MAX_RESULTS])


def _grep_python(args: dict[str, Any]) -> str:
    pattern = str(args['pattern'])
    include = str(args.get('include', '') or '')
    base = _base_dir()
    try:
        regex = re.compile(pattern)
    except re.error as error:
        return f'Invalid regex: {error}'
    files: list[str] = []
    for root, dirs, names in os.walk(base):
        dirs[:] = [name for name in dirs
                   if not name.startswith('.') and name not in _GREP_SKIP_DIRS]
        for name in names:
            path = os.path.join(root, name)
            if include and not _grep_include(path, include):
                continue
            try:
                if os.path.getsize(path) > _GREP_MAX_FILE:
                    continue
            except OSError:
                continue
            files.append(path)

    def search(path: str) -> list[str]:
        local: list[str] = []
        display = _display_path(path)
        try:
            with open(path, 'rb') as stream:
                data = stream.read()
            if b'\x00' in data:
                return local
            text = data.decode('utf-8', errors='replace')
            for number, line in enumerate(text.split('\n'), 1):
                if regex.search(line):
                    local.append(f'{display}:{number}: {line.rstrip()}')
                    if len(local) >= _GREP_MAX_RESULTS:
                        break
        except Exception:
            pass
        return local

    results: list[str] = []
    workers = min(32, (os.cpu_count() or 2) + 4)
    if len(files) > 1 and workers > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(search, path) for path in files]
            for future in as_completed(futures):
                results.extend(future.result())
                if len(results) >= _GREP_MAX_RESULTS:
                    break
    else:
        for path in files:
            results.extend(search(path))
    if not results:
        return '(no matches)'
    return '\n'.join(results[:_GREP_MAX_RESULTS])


def _grep(args: dict[str, Any]) -> str:
    rg = _find_rg()
    if rg:
        output = _grep_rg(rg, args)
        if output is not None:
            return output
    return _grep_python(args)


def _fetch(args: dict[str, Any]) -> str:
    url = str(args['url'])
    method = str(args.get('method', 'GET')).upper()
    headers = args.get('headers') or {}
    if not isinstance(headers, dict):
        headers = {}
    body = args.get('body') or None
    if isinstance(body, str):
        body = body.encode('utf-8')
    try:
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        with net.urlopen(request, timeout=30) as response:
            status = response.status
            raw = response.read(2_000_000)
        text = raw.decode('utf-8', errors='replace')
    except urllib.error.HTTPError as error:
        status = error.code
        try:
            text = error.read().decode('utf-8', errors='replace')
        except Exception:
            text = ''
    except Exception as error:
        return f'Error: {error}'
    if len(text) > 4_000:
        text = text[:4_000] + '\n...(truncated)'
    return f'[{status}]\n{text}'


def _view_image(args: dict[str, Any]) -> str:
    """Copy an image into the session store and hand it to the model.

    The returned marker is expanded into a native image part by the wire
    adapter, so the picture reaches the model without any base64 in the
    stored conversation.
    """
    raw_path = str(args.get('path') or '').strip().strip('"\'')
    if not raw_path:
        return 'Error: path is required'
    if raw_path.startswith(('http://', 'https://')):
        return f'Loaded {raw_path}.\n{image_marker(raw_path)}'
    path = _resolve(raw_path)
    if not os.path.isfile(path):
        return f'Error: file not found: {raw_path}'
    try:
        with open(path, 'rb') as stream:
            data = stream.read(MAX_IMAGE_BYTES + 1)
    except OSError as error:
        return f'Error reading {raw_path}: {error}'
    if len(data) > MAX_IMAGE_BYTES:
        return (f'Error: {raw_path} is larger than '
                f'{MAX_IMAGE_BYTES // 1_048_576} MB')
    media_type = sniff_media_type(data)
    if media_type is None:
        return (f'Error: not a supported image: {raw_path} '
                f'(png, jpeg, gif or webp)')
    store = ImageStore(os.path.join(_base_dir(), 'sessions', 'images'), _base_dir())
    try:
        reference = store.save(data)
    except (ValueError, OSError) as error:
        return f'Error: cannot store {raw_path}: {error}'
    size = image_info(data)
    shape = f'{size[0]}x{size[1]} ' if size else ''
    kilobytes = max(1, round(len(data) / 1024))
    return (f'Loaded {raw_path} ({shape}{media_type}, {kilobytes} KB). '
            f'The image is attached below.\n{image_marker(reference)}')


def _diff(args: dict[str, Any]) -> str:
    file_diff = git_worktree_diff(_base_dir(), str(args.get('path', '') or ''))
    if file_diff is None:
        return '(no working-tree changes)'
    return file_diff.unified or '(no textual diff)'


def _ls(args: dict[str, Any]) -> str:
    raw_path = str(args.get('path', '') or '.')
    path = _resolve(raw_path)
    try:
        entries = sorted(os.listdir(path))
    except Exception as error:
        return f'Error listing {raw_path}: {error}'
    if not entries:
        return '(empty directory)'
    lines = []
    for name in entries:
        full = os.path.join(path, name)
        suffix = '/' if os.path.isdir(full) else ''
        lines.append(f'{name}{suffix}')
    return '\n'.join(lines)


def core_tools(*, shell: ShellSessions | None = None) -> list[AnnotatedTool]:
    """The coding app's ten tools as AnnotatedTool objects.

    Args:
        shell: a shared ShellSessions owner; one is created when omitted.
            Pass the engine's instance so root and sub-agents (and the
            shutdown hook) drive the same sessions.
    """
    return [
        AnnotatedTool(
            name='read', read_only=True,
            description=('Read a file from the filesystem. Returns content with line '
                         'numbers. Use offset/limit for large files.'),
            parameters={
                'type': 'object',
                'properties': {
                    'path': {'type': 'string', 'description': 'File path to read'},
                    'offset': {'type': 'integer', 'description': '1-based first line'},
                    'limit': {'type': 'integer', 'description': 'Maximum lines to return'},
                },
                'required': ['path'],
            },
            handler=_dict_handler(_read),
        ),
        AnnotatedTool(
            name='view_image', read_only=True, vision_only=True,
            description=('Look at an image file yourself: a screenshot, a diagram, '
                         'a photo. The picture is attached to the conversation so '
                         'you can describe or reason about it. Supports png, jpeg, '
                         'gif and webp up to 5 MB, plus http(s) image URLs.'),
            parameters={
                'type': 'object',
                'properties': {
                    'path': {'type': 'string',
                             'description': 'Image file path, or an http(s) URL'},
                },
                'required': ['path'],
            },
            handler=_dict_handler(_view_image),
        ),
        AnnotatedTool(
            name='write', snapshot=True,
            description='Create or overwrite a file with the given content.',
            parameters={
                'type': 'object',
                'properties': {
                    'path': {'type': 'string', 'description': 'File path to write'},
                    'content': {'type': 'string', 'description': 'Full file content'},
                },
                'required': ['path', 'content'],
            },
            handler=_dict_handler(_write),
        ),
        AnnotatedTool(
            name='edit', snapshot=True,
            description=('Replace an exact string in a file. The old string must appear '
                         'exactly once in the file.'),
            parameters={
                'type': 'object',
                'properties': {
                    'path': {'type': 'string'},
                    'old': {'type': 'string', 'description': 'Exact text to find'},
                    'new': {'type': 'string', 'description': 'Replacement text'},
                },
                'required': ['path', 'old', 'new'],
            },
            handler=_dict_handler(_edit),
        ),
        AnnotatedTool(
            name='glob', read_only=True,
            description='Find files matching a glob pattern. Supports ** recursion.',
            parameters={
                'type': 'object',
                'properties': {
                    'pattern': {'type': 'string', 'description': 'e.g. "src/**/*.py"'},
                },
                'required': ['pattern'],
            },
            handler=_dict_handler(_glob),
        ),
        AnnotatedTool(
            name='grep', read_only=True,
            description='Search file contents with a regular expression.',
            parameters={
                'type': 'object',
                'properties': {
                    'pattern': {'type': 'string', 'description': 'Regex to search for'},
                    'include': {'type': 'string', 'description': 'File filter, e.g. "*.py"'},
                },
                'required': ['pattern'],
            },
            handler=_dict_handler(_grep),
        ),
        session_shell_tool(name='bash', sessions=shell,
                           metadata_tag='bash_tool_metadata'),
        AnnotatedTool(
            name='fetch', read_only=True,
            description='Make an HTTP request and return the status and body.',
            parameters={
                'type': 'object',
                'properties': {
                    'url': {'type': 'string'},
                    'method': {'type': 'string', 'description': 'GET, POST, PUT, DELETE'},
                    'headers': {'type': 'object'},
                    'body': {'type': 'string'},
                },
                'required': ['url'],
            },
            handler=_dict_handler(_fetch),
        ),
        AnnotatedTool(
            name='diff', read_only=True,
            description='Show the current Git working-tree diff, optionally for one path.',
            parameters={
                'type': 'object',
                'properties': {'path': {'type': 'string', 'description': 'Optional path'}},
                'required': [],
            },
            handler=_dict_handler(_diff),
        ),
        AnnotatedTool(
            name='ls', read_only=True,
            description='List directory entries.',
            parameters={
                'type': 'object',
                'properties': {'path': {'type': 'string',
                                        'description': 'Directory (default .)'}},
                'required': [],
            },
            handler=_dict_handler(_ls),
        ),
    ]


def install_core_tools(registry, *, shell: ShellSessions | None = None) -> list[str]:
    """Register the suite on a ManagedToolRegistry and return the names."""
    installed = []
    for tool in core_tools(shell=shell):
        registry.register(tool, replace=True, source='builtin')
        installed.append(tool.name)
    return installed
