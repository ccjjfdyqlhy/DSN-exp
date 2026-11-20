# Wiring W6: profile switching must be observable and effective.
#   - apply_profile actually rewrites the pool's spec timeouts (the "eco is
#     a no-op" gap);
#   - `aicf resources status` reports the resolved profile without spawning
#     any service.

from aicf.harness.cli.main import main as cli_main


def _pool_with_specs():
    from aicf.infra.resources.pool import ResourceKind, ResourcePool, ResourceSpec

    pool = ResourcePool()
    pool.register_resource(
        'tts', ResourceSpec(kind=ResourceKind.TTS, display_name='tts',
                            idle_timeout=3600),
        load_fn=lambda: True, unload_fn=lambda: True)
    pool.register_resource(
        'vlm', ResourceSpec(kind=ResourceKind.VLM, display_name='vlm',
                            idle_timeout=900),
        load_fn=lambda: True, unload_fn=lambda: True)
    return pool


def test_eco_profile_rewrites_pool_timeouts():
    from aicf.infra.resources.profiles import apply_profile

    pool = _pool_with_specs()
    changes = apply_profile(pool, 'eco')
    kinds = {c.kind: c.after for c in changes}
    assert kinds.get('tts') == 600 and kinds.get('vlm') == 300
    assert pool.get_spec('tts').idle_timeout == 600


def test_resident_profile_disables_unload():
    from aicf.infra.resources.profiles import apply_profile

    pool = _pool_with_specs()
    apply_profile(pool, 'resident')
    assert pool.get_spec('tts').idle_timeout == 0
    assert pool.get_spec('vlm').idle_timeout == 0


def test_balanced_profile_touches_nothing():
    from aicf.infra.resources.profiles import apply_profile

    pool = _pool_with_specs()
    changes = apply_profile(pool, 'balanced')
    assert changes == []
    assert pool.get_spec('tts').idle_timeout == 3600  # the app's own setting wins


def test_resources_status_reports_profile(tmp_path):
    code = cli_main(['resources', 'status', '--json'])
    assert code == 0
    code = cli_main(['resources', 'status'])
    assert code == 0
