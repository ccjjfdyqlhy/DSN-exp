"""评测集的工具名必须能落到真实注册表上。

── 这条测试存在的理由 ──
1.0.0 之前，``aicf/harness/datasets/basic.yaml`` 里的 27 条工具断言有 26 条
指向**注册表里根本不存在的名字**（fs.read / fs.write / calc.eval / web.search …），
而真实工具叫 file.read / file.write / web.fetch。

后果不是「用例失败」，而是**用例永远不可能通过**，并且失败原因会被误读成
「模型没调用工具」—— 于是「可度量」这根支柱是空的。

抽象名 → 真实名的绑定放在 ``aicf/infra/eval/tool_vocab.py``。
本测试守住三件事：

1. 评测集里出现的每个工具名，都能落到**至少一个真实注册的工具**上；
2. 词表里每个别名指向的工具，都真实存在；
3. 同一条用例不会「要求 A 又禁止 A 的绑定目标」——那种用例自相矛盾，
   永远不可能同时成立（例：要求 web.search 又禁止 web.fetch，
   而现在 web.search 就落到 web.fetch）。
"""

from __future__ import annotations

import glob
import os

import pytest

from aicf.harness.tools import ToolRegistry
from aicf.harness.tools.standard import install_standard_tools
from aicf.infra.eval.tool_vocab import (
    TOOL_NAME_ALIASES,
    resolve_tool_names,
)

DATASETS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'aicf', 'harness', 'datasets',
)


@pytest.fixture(scope='module')
def registered_tool_names() -> set[str]:
    """当前实现真正注册的工具名。"""
    registry = ToolRegistry()
    tools = install_standard_tools(registry)
    return {tool.name for tool in tools}


@pytest.fixture(scope='module')
def dataset_files() -> list[str]:
    files = sorted(glob.glob(os.path.join(DATASETS_DIR, '*.yaml')))
    assert files, f'{DATASETS_DIR} 下没有任何评测集 —— 随包分发必须带上它'
    return files


def _iter_tool_names(case):
    """一条用例里出现的全部工具名（tool_called / forbid_tools 等）。"""
    for assertion in list(case.expect or []) + list(case.metrics or []):
        if not isinstance(assertion, dict):
            continue
        for kind, value in assertion.items():
            if 'tool' not in kind:
                continue
            names = value if isinstance(value, list) else [value]
            for name in names:
                if isinstance(name, str):
                    yield kind, name


def _load_cases(path: str):
    from aicf.infra.eval.dataset import load_dataset
    dataset = load_dataset(path)
    return dataset.cases


def test_dataset_tool_names_resolve_to_real_tools(dataset_files, registered_tool_names):
    """评测集里的每个工具名都必须落到至少一个真实注册的工具上。"""
    unresolved = []
    for path in dataset_files:
      for case in _load_cases(path):
        for _kind, name in _iter_tool_names(case):
            targets = resolve_tool_names(name)
            if not targets:
                unresolved.append(f'{case.id}: {name} → 无任何绑定目标')
            elif not any(t in registered_tool_names for t in targets):
                unresolved.append(
                    f'{case.id}: {name} → {list(targets)}（注册表里没有）')
    assert not unresolved, (
        '评测集里有工具名落不到真实注册表上——这些断言永远不可能成立：\n  '
        + '\n  '.join(unresolved)
    )


def test_alias_targets_are_real_tools(registered_tool_names):
    """词表里的每个绑定目标都必须是真实注册的工具。"""
    bad = {
        abstract: list(targets)
        for abstract, targets in TOOL_NAME_ALIASES.items()
        if not any(t in registered_tool_names for t in targets)
    }
    assert not bad, f'词表指向了不存在的工具：{bad}'


def test_no_case_requires_and_forbids_the_same_tool(dataset_files):
    """同一条用例不能既要求某类工具、又禁止它的绑定目标。"""
    contradictions = []
    for path in dataset_files:
        for case in _load_cases(path):
            required: set[str] = set()
            forbidden: set[str] = set()
            for kind, name in _iter_tool_names(case):
                targets = set(resolve_tool_names(name))
                if kind == 'tool_called':
                    required |= targets
                elif kind == 'forbid_tools':
                    forbidden |= targets
            overlap = required & forbidden
            if overlap:
                contradictions.append(
                    f'{case.id}: 同时要求又禁止 {sorted(overlap)}')
    assert not contradictions, (
        '这些用例自相矛盾，永远不可能同时成立：\n  '
        + '\n  '.join(contradictions)
    )


def test_every_case_id_is_unique(dataset_files):
    """用例 id 必须唯一 —— 报告按 id 归并，重名会静默覆盖。"""
    seen: dict[str, str] = {}
    dupes = []
    for path in dataset_files:
        for case in _load_cases(path):
            if case.id in seen:
                dupes.append(f'{case.id}（{seen[case.id]} 与 {path}）')
            seen[case.id] = path
    assert not dupes, f'用例 id 重复：{dupes}'
