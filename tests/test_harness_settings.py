# tests/test_harness_settings.py
# 命名空间配置测试

from __future__ import annotations

import pytest

from harness.settings import Namespace, Settings, as_bool, as_int, as_float


def _env(**kv):
    return {k: str(v) for k, v in kv.items()}


def test_plain_binding_reads_env():
    env = _env(TTS_ENABLED="true")
    ns = Namespace("voice", loader=env.get)
    ns.bind_bool("tts_enabled", "TTS_ENABLED", default=False)
    assert ns.tts_enabled is True


def test_bool_converter_defaults():
    env = _env()
    ns = Namespace("voice", loader=env.get)
    ns.bind_bool("flag", "FLAG", default=True)
    assert ns.flag is True


def test_bool_truthy_variants():
    for raw in ("1", "true", "TRUE", "yes", "on", "On"):
        assert as_bool(raw) is True
    for raw in ("0", "false", "no", "off", ""):
        assert as_bool(raw) is False


def test_int_and_float_conversion():
    env = _env(MAX_STEPS="15", TEMP="0.7")
    ns = Namespace("agent", loader=env.get)
    ns.bind_int("max_steps", "MAX_STEPS", default=5)
    ns.bind_float("temperature", "TEMP", default=1.0)
    assert ns.max_steps == 15
    assert ns.temperature == 0.7


def test_converter_fallback_on_bad_value():
    env = _env(N="abc")
    ns = Namespace("x", loader=env.get)
    ns.bind_int("n", "N", default=9)
    assert ns.n == 9


def test_unknown_attr_raises():
    env = _env()
    ns = Namespace("x", loader=env.get)
    ns.bind_bool("known", "KNOWN", default=False)
    with pytest.raises(AttributeError):
        ns.unknown_attr
    assert "known" in ns
    assert "unknown_attr" not in ns


def test_underscore_attr_never_delegates():
    ns = Namespace("x", loader=_env().get)
    assert ns._name == "x"
    with pytest.raises(AttributeError):
        ns._no_such_underscore


def test_as_dict():
    env = _env(A="1", B="hi")
    ns = Namespace("x", loader=env.get)
    ns.bind_bool("a", "A", default=False)
    ns.bind("b", "B", default="")
    assert ns.as_dict() == {"a": True, "b": "hi"}


def test_settings_namespace_create_and_reuse():
    settings = Settings()
    a = settings.namespace("voice")
    b = settings.namespace("voice")
    assert a is b
    c = settings.namespace("companion")
    assert c is not a
    assert set(settings.namespaces()) == {"voice", "companion"}


def test_settings_namespace_no_create():
    settings = Settings()
    assert settings.namespace("missing", create=False) is None
    assert settings.namespace("voice") is not None


def test_custom_loader():
    store = {"K": "value"}
    settings = Settings(loader=store.get)
    ns = settings.namespace("test")
    ns.bind("k", "K", default="d")
    assert ns.k == "value"


def test_default_loader_reads_process_env(monkeypatch):
    monkeypatch.setenv("HARNESS_TEST_ENV", "42")
    settings = Settings()
    ns = settings.namespace("probe")
    ns.bind_int("answer", "HARNESS_TEST_ENV", default=0)
    assert ns.answer == 42
