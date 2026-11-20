# tests/test_rc1_contracts.py
# rc1 新模块的契约测试 —— import 独立性、约定一致性、策略加载器。
#
# 与 test_rc0_contracts.py 同一思路：契约先钉住，实现随便换。

from __future__ import annotations

from pathlib import Path

import pytest

from infra.policy.loader import PolicyFileError, load_policy_file, policy_from_dict

ROOT = Path(__file__).resolve().parents[1]


# ── import 独立性 ────────────────────────────────────────
def test_new_infra_packages_import_standalone():
    """所有新增包都必须能单独 import 并通过冒烟（策划案 §6.2）。"""
    import importlib
    for name in ('infra.control', 'infra.control.artifact',
                 'infra.control.lifecycle', 'infra.control.store',
                 'infra.control.cost', 'infra.control.identity',
                 'infra.control.adoption',
                 'infra.eval.sampling', 'infra.eval.badcase',
                 'infra.runtime.scheduler', 'infra.runtime.isolation',
                 'infra.policy.loader'):
        importlib.import_module(name)


def test_harness_kernel_new_modules_import_standalone():
    import importlib
    for name in ('harness.kernel.workflow', 'harness.kernel.planner',
                 'harness.tools.discovery', 'harness.grounding',
                 'harness.memory.layers'):
        importlib.import_module(name)


def test_control_plane_modules_never_import_harness_at_runtime():
    """模块级静态检查由 test_rc0_dependency_direction.py 负责；
    这里做**运行期**确认：sys.modules 里这些包没有把 harness 拖进来。"""
    import importlib
    import sys
    before = set(sys.modules)
    importlib.import_module('infra.control')
    importlib.import_module('infra.eval.sampling')
    importlib.import_module('infra.eval.badcase')
    importlib.import_module('infra.runtime.scheduler')
    dragged = {m for m in set(sys.modules) - before
               if m == 'harness' or m.startswith('harness.')}
    assert not dragged, f'infra 模块把 harness 拖进了运行时: {sorted(dragged)}'


# ── 状态目录约定 ─────────────────────────────────────────
def test_state_dir_convention_is_pinned_across_layers(monkeypatch, tmp_path):
    """infra 与 harness 各自读 $AICF_HOME —— 约定由交叉测试钉住。

    （与幂等键同一模式：两份实现，一条交叉测试。）
    """
    monkeypatch.setenv('AICF_HOME', str(tmp_path / 'custom-home'))
    from harness.paths import state_dir
    assert state_dir() == tmp_path / 'custom-home'

    from infra.runtime.isolation import WorkspaceManager
    manager = WorkspaceManager()
    assert str(manager._base).startswith(str(tmp_path / 'custom-home'))


def test_default_state_dir_is_the_user_home(monkeypatch):
    monkeypatch.delenv('AICF_HOME', raising=False)
    from harness.paths import state_dir
    from infra.runtime.isolation import WorkspaceManager
    assert str(WorkspaceManager()._base).startswith(str(state_dir()))


# ── 策略加载器 ───────────────────────────────────────────
def test_policy_loader_builds_a_rule_engine():
    engine = policy_from_dict({
        'rules': [
            {'action': 'deny', 'id': 'd1', 'tool': 'proc.run',
             'reason': '禁 shell'},
            {'action': 'allow', 'id': 'a1', 'tool_prefix': 'fs.read'},
        ],
        'auto_approve_risk': 'medium',
        'allow_readonly': True,
    })
    from harness.tools.spec import ToolSpec
    # deny 规则生效
    decision = engine.admit('proc.run', spec=ToolSpec(name='proc.run'))
    assert not decision.allowed and decision.reason == 'policy'
    # allow 规则生效
    decision = engine.admit('fs.read', spec=ToolSpec(name='fs.read',
                                                     effect='pure'))
    assert decision.allowed


def test_policy_loader_fails_closed_on_bad_rules():
    """一条写错的规则 = 一次静默放权 —— 加载器必须抛错而不是跳过。"""
    with pytest.raises(PolicyFileError):
        policy_from_dict({'rules': [{'action': 'maybe', 'tool': 'x'}]})
    with pytest.raises(PolicyFileError):
        # 字段拼错 → 报错，不吞（拼错的 deny 规则是最危险的拼写错误）
        policy_from_dict({'rules': [{'action': 'deny', 'toolz': 'x'}]})
    with pytest.raises(PolicyFileError):
        policy_from_dict({'rules': 'not-a-list'})
    with pytest.raises(PolicyFileError):
        load_policy_file('/nonexistent/policies.yaml')


def test_shipped_policy_files_load(tmp_path):
    """仓库里的 policies/*.yaml 必须能加载（策划案 §6.1）。"""
    approval = load_policy_file(ROOT / 'policies' / 'approval.yaml')
    assert approval.allow_readonly is True
    assert any(r.id == 'deny-destructive' for r in approval.rules)
    # network.yaml 是 WorkspaceSpec 的声明来源，不是 RulePolicyEngine
    import yaml
    data = yaml.safe_load((ROOT / 'policies' / 'network.yaml').read_text(
        encoding='utf-8'))
    from infra.runtime.isolation import WorkspaceSpec
    spec = WorkspaceSpec.from_dict({
        'net': data['net'], 'net_allowlist': data['allowlist']})
    assert spec.net == 'allowlist'
    assert manager_net_check(spec, 'pypi.org') is True
    assert manager_net_check(spec, 'evil.example') is False


def manager_net_check(spec, host):
    from infra.runtime.isolation import Workspace, WorkspaceManager
    manager = WorkspaceManager(base='/tmp/rc1-policy-check')
    ws = Workspace(id='w', session_id='s', root='/tmp/rc1-policy-check/s',
                   spec=spec)
    return manager.net_check(ws, host)
