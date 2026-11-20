# tests/test_version.py
# One version, everywhere: the package metadata, the runtime string and the
# docs must agree, or a release tag check (or a user) is the one who finds out.

from __future__ import annotations

import re
from pathlib import Path

try:                          # Python 3.11+; the package still supports 3.10
    import tomllib
except ModuleNotFoundError:   # pragma: no cover - interpreter dependent
    tomllib = None

import aicf.harness

ROOT = Path(__file__).resolve().parent.parent


def _declared() -> str:
    path = ROOT / 'pyproject.toml'
    if tomllib is not None:
        with path.open('rb') as stream:
            return tomllib.load(stream)['project']['version']
    match = re.search(r'^version = "([^"]+)"', path.read_text(encoding='utf-8'),
                      re.MULTILINE)
    assert match, 'pyproject.toml has no version line'
    return match.group(1)


def test_the_runtime_version_matches_the_package_metadata():
    assert aicf.harness.__version__ == _declared(), (
        'aicf.harness.__version__ and pyproject.toml disagree; bump both')


def test_the_docs_quote_the_same_version():
    text = (ROOT / 'docs' / 'getting-started.md').read_text(encoding='utf-8')
    assert f'期望 {_declared()}' in text, 'docs/getting-started.md is stale'


def test_the_version_is_a_release_number():
    """Three numeric parts, plus an optional pre-release suffix.

    The suffix is what marks a release candidate (1.0.0rc0).
    """
    match = re.fullmatch(r'\d+\.\d+\.\d+(?:[a-z]+\d*)?', _declared())
    assert match, f'{_declared()} is not a release number'
