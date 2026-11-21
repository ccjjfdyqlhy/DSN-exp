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


def test_the_english_docs_quote_the_same_version():
    """英文上手文档也必须钉着同一个版本号。"""
    text = (ROOT / 'docs' / 'en' / 'getting-started.md').read_text(encoding='utf-8')
    assert f'expected {_declared()}' in text, 'docs/en/getting-started.md is stale'


def test_no_doc_claims_a_different_current_release():
    """任何「当前发布版是 X」的声明，X 必须等于 pyproject 的版本。

    版本号散落在 README、上手文档、拆仓文档里，改了 pyproject 忘了改文档，
    就会对用户撒谎（"当前发布版是 1.0.0" 而 PyPI 上已经是 1.0.1）。
    这里把所有「当前版本」句式扫一遍，逐个核对。
    """
    version = _declared()
    # 只抓「当前/最新发布版」这类**当前状态**的断言；
    # 「1.0.0 之前」「1.0.0 起」「迁移到 1.0.0」是历史陈述，不在其列。
    patterns = [
        r'当前发布版是\s*([0-9][0-9a-z.]*)',
        r'当前版本(?:号)?(?:是|为)\s*\**([0-9][0-9a-z.]*)',
        r'the current release is\s*([0-9][0-9a-z.]*)',
        r'currently at\s*\**([0-9][0-9a-z.]*)',
        r'当前发布版[：:]\s*([0-9][0-9a-z.]*)',
    ]
    docs = [
        'README.md', 'README_zh.md',
        'docs/getting-started.md', 'docs/en/getting-started.md',
        'docs/split_migration.md', 'docs/community.md',
        'docs/site/index.html', 'docs/site/en/index.html',
    ]
    stale = []
    for rel in docs:
        path = ROOT / rel
        if not path.exists():
            continue
        text = path.read_text(encoding='utf-8')
        for pattern in patterns:
            for found in re.findall(pattern, text):
                if found != version:
                    stale.append(f'{rel}: 声称当前版本是 {found}，实际 {version}')
    assert not stale, '文档里的当前版本声明与 pyproject 不一致：\n  ' + '\n  '.join(stale)


def test_floor_claims_are_not_above_the_current_version():
    """「必须是 X 或更新」这类下限声明，X 不能高于当前版本。

    README 里写着「`aicf --version` 必须打出 1.0.0 或更新」——
    如果哪天版本号退到 1.0.0 以下，这句话就变成空头支票。
    """
    version = _declared()
    for rel in ('README.md', 'README_zh.md', 'docs/community.md'):
        text = (ROOT / rel).read_text(encoding='utf-8')
        for found in re.findall(r'(?:或更新|or newer|≥\s*)([0-9]+\.[0-9]+\.[0-9]+)', text):
            assert _tuple(found) <= _tuple(version), (
                f'{rel}: 下限声明 {found} 高于当前版本 {version}')


def _tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split('.')[:3])


def test_the_version_is_a_release_number():
    """Three numeric parts, plus an optional pre-release suffix.

    The suffix is what marks a release candidate (1.0.0rc0).
    """
    match = re.fullmatch(r'\d+\.\d+\.\d+(?:[a-z]+\d*)?', _declared())
    assert match, f'{_declared()} is not a release number'
