# tests/test_resource_profiles.py
# roadmap 段 6 的验收测试：随时可用 vs 显存。
#
# 验收标准（roadmap 原文）：选 `resident` 时，第一次语音请求的延迟
# == 常驻时的延迟。落到框架层就是一条可执行断言：
# **resident 档下 IdleReaper 永不回收已加载的资源** —— 不卸载就没有
# 冷启动，第一次请求不用等模型重新加载。
#
# 三档语义：
#   resident  显存换延迟（idle_timeout 全部 → 0，永不卸载）
#   balanced  不动配置（各资源的独立设置继续有效 —— 默认，向后兼容）
#   eco       显存优先（tts/asr 600s、vlm/decision 300s）

import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aicf.infra.resources.idle import IdleReaper
from aicf.infra.resources.pool import ResourceKind, ResourcePool, ResourceSpec
from aicf.infra.resources.profiles import (
    ResourceProfile,
    apply_profile,
    describe_profile,
    profile_idle_timeout,
    resolve_profile,
)


@pytest.fixture(autouse=True)
def _isolated_profile_env(tmp_path, monkeypatch):
    """档位解析的环境与配置全部隔离到临时目录。"""
    monkeypatch.delenv('AICF_RESOURCE_PROFILE', raising=False)
    monkeypatch.setenv('AICF_CONFIG_DIR', str(tmp_path / '.aicf'))
    yield


def _make_pool(*specs: tuple[str, ResourceKind, int]) -> ResourcePool:
    """带假 load/unload 的资源池（不起任何真进程）。"""
    pool = ResourcePool(max_concurrent=2)
    state: dict = {'load': [], 'unload': []}
    for name, kind, timeout in specs:
        pool.register_resource(
            name=name,
            spec=ResourceSpec(kind=kind, display_name=name, resident=True,
                              extra={'managed': True}, idle_timeout=timeout),
            load_fn=lambda n=name: state['load'].append(n) or True,
            unload_fn=lambda n=name: state['unload'].append(n) or True,
        )
    pool.state = state
    return pool


# ── 档位解析 ────────────────────────────────────────────────

def test_resolve_order_explicit_beats_everything(tmp_path, monkeypatch):
    monkeypatch.setenv('AICF_RESOURCE_PROFILE', 'eco')
    (tmp_path / '.aicf').mkdir()
    (tmp_path / '.aicf' / 'resource_profile').write_text('resident\n')
    assert resolve_profile('resident') is ResourceProfile.RESIDENT


def test_resolve_order_env_beats_config(tmp_path, monkeypatch):
    monkeypatch.setenv('AICF_RESOURCE_PROFILE', 'eco')
    (tmp_path / '.aicf').mkdir()
    (tmp_path / '.aicf' / 'resource_profile').write_text('resident\n')
    assert resolve_profile() is ResourceProfile.ECO


def test_resolve_order_config_beats_default(tmp_path):
    (tmp_path / '.aicf').mkdir()
    (tmp_path / '.aicf' / 'resource_profile').write_text('resident\n')
    assert resolve_profile() is ResourceProfile.RESIDENT
    assert resolve_profile() is not ResourceProfile.BALANCED


def test_resolve_defaults_to_balanced():
    assert resolve_profile() is ResourceProfile.BALANCED


def test_invalid_profile_name_is_an_error():
    with pytest.raises(ValueError):
        ResourceProfile.parse('turbo')
    with pytest.raises(ValueError):
        resolve_profile('turbo')


def test_invalid_saved_config_falls_back_to_balanced(tmp_path):
    (tmp_path / '.aicf').mkdir()
    (tmp_path / '.aicf' / 'resource_profile').write_text('turbo\n')
    assert resolve_profile() is ResourceProfile.BALANCED


# ── 落到资源池 ──────────────────────────────────────────────

def test_resident_never_reaps_the_pool():
    """验收核心：resident 档 → 永不回收 → 没有冷启动延迟。"""
    pool = _make_pool(('tts', ResourceKind.TTS, 3600),
                      ('asr', ResourceKind.ASR, 3600))
    changes = apply_profile(pool, 'resident')
    assert {(c.name, c.after) for c in changes} == {('tts', 0), ('asr', 0)}
    # 模拟「闲置了两天」—— 任何阈值下的 reaper 都不该动它
    reaper = IdleReaper(pool, interval=60.0, clock=lambda: time.time() + 172800)
    reclaimed = reaper.reap_once()
    assert reclaimed == []
    assert pool.state['unload'] == []


def test_eco_tightens_timeouts():
    pool = _make_pool(('tts', ResourceKind.TTS, 3600),
                      ('decision', ResourceKind.DECISION, 900))
    changes = apply_profile(pool, 'eco')
    by_name = {c.name: c.after for c in changes}
    assert by_name['tts'] == 600
    assert by_name['decision'] == 300


def test_balanced_changes_nothing():
    pool = _make_pool(('tts', ResourceKind.TTS, 3600))
    changes = apply_profile(pool, 'balanced')
    assert changes == []
    assert pool.get_spec('tts').idle_timeout == 3600


def test_enable_idle_shutdown_applies_profile():
    """框架默认路径：enable_idle_shutdown 自动应用档位（环境变量驱动）。"""
    pool = _make_pool(('tts', ResourceKind.TTS, 3600))
    os.environ['AICF_RESOURCE_PROFILE'] = 'resident'
    try:
        reaper = pool.enable_idle_shutdown(interval=60.0)
        try:
            assert pool.get_spec('tts').idle_timeout == 0
        finally:
            reaper.stop()
    finally:
        del os.environ['AICF_RESOURCE_PROFILE']


def test_first_voice_request_pays_no_reload_under_resident():
    """端到端口径的验收：resident 下「闲置很久 → 请求」不触发重载。"""
    pool = _make_pool(('tts', ResourceKind.TTS, 3600))
    apply_profile(pool, 'resident')
    # 资源已加载（模拟常驻）
    pool.ensure_running('tts', timeout=1.0)
    loaded_before = pool.state['load']
    reaper = IdleReaper(pool, interval=60.0, clock=lambda: time.time() + 999999)
    reaper.reap_once()
    # 没有卸载，也没有为「下次请求」重新加载 —— 常驻延迟 == 请求延迟
    assert pool.state['unload'] == []
    assert pool.state['load'] == loaded_before


# ── profile_idle_timeout ────────────────────────────────────

def test_profile_timeouts_table():
    assert profile_idle_timeout('resident', 'tts') == 0
    assert profile_idle_timeout('resident', 'decision') == 0
    assert profile_idle_timeout('eco', 'tts') == 600
    assert profile_idle_timeout('eco', 'vlm') == 300
    assert profile_idle_timeout('balanced', 'tts') == 0   # balanced 不覆盖


# ── CLI ─────────────────────────────────────────────────────

def _cli(argv):
    from aicf.harness.cli.main import main as cli_main
    return cli_main(argv)


def test_cli_profile_show_default(capsys):
    assert _cli(['resources', 'profile']) == 0
    out = capsys.readouterr().out
    assert 'balanced' in out
    assert 'resident' in out


def test_cli_profile_set_and_read_back(tmp_path, capsys):
    assert _cli(['resources', 'profile', '--set', 'resident']) == 0
    saved = (tmp_path / '.aicf' / 'resource_profile').read_text().strip()
    assert saved == 'resident'
    assert resolve_profile() is ResourceProfile.RESIDENT
    capsys.readouterr().out


def test_cli_profile_set_invalid_exits_2(capsys):
    assert _cli(['resources', 'profile', '--set', 'turbo']) == 2
    assert 'turbo' in capsys.readouterr().err


def test_cli_profile_json(capsys):
    import json
    assert _cli(['resources', 'profile', '--json']) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['profile'] == 'balanced'
    assert 'idle_timeouts' in payload


# ── describe ────────────────────────────────────────────────

def test_describe_reports_source():
    os.environ['AICF_RESOURCE_PROFILE'] = 'eco'
    try:
        info = describe_profile()
        assert info['profile'] == 'eco'
        assert 'env' in info['source']
    finally:
        del os.environ['AICF_RESOURCE_PROFILE']
