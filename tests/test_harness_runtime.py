# tests/test_harness_runtime.py
# Runtime DI 容器与生命周期测试

from __future__ import annotations

import pytest

from harness import Runtime


class _DummyService:
    def __init__(self, value: int = 1):
        self.value = value


class _AnotherService:
    pass


@pytest.fixture(autouse=True)
def _clean_runtime_context():
    yield


def test_register_and_resolve():
    rt = Runtime()
    svc = _DummyService(42)
    rt.register("db", svc)
    assert rt.resolve("db") is svc
    assert rt.has("db")


def test_register_by_type_key():
    rt = Runtime()
    svc = _DummyService(1)
    rt.register(_DummyService, svc)
    assert rt.resolve(_DummyService) is svc
    assert rt.has(_DummyService)


def test_get_with_default():
    rt = Runtime()
    assert rt.get("missing", "fallback") == "fallback"
    assert rt.get("missing") is None


def test_resolve_missing_raises():
    rt = Runtime()
    with pytest.raises(KeyError):
        rt.resolve("nope")


def test_register_factory_lazy_and_cached():
    rt = Runtime()
    calls = []

    def make():
        calls.append(1)
        return _DummyService()

    rt.register_factory("svc", make)
    assert calls == []
    a = rt.resolve("svc")
    b = rt.resolve("svc")
    assert a is b
    assert len(calls) == 1


def test_register_collision_raises():
    rt = Runtime()
    rt.register("k", 1)
    with pytest.raises(KeyError):
        rt.register("k", 2)
    rt.register("k", 2, replace=True)
    assert rt.resolve("k") == 2


def test_register_factory_overwrites_instance():
    rt = Runtime()
    rt.register("k", 1)
    rt.register_factory("k", lambda: 3, replace=True)
    assert rt.resolve("k") == 3


def test_register_all():
    rt = Runtime()
    rt.register_all(db=1, engine=2)
    assert rt.resolve("db") == 1
    assert rt.resolve("engine") == 2


def test_lifecycle_start_stop_order():
    rt = Runtime()
    order = []
    rt.on_start(lambda: order.append("start1"))
    rt.on_start(lambda: order.append("start2"))
    rt.on_stop(lambda: order.append("stop1"))
    rt.on_stop(lambda: order.append("stop2"))

    rt.start()
    assert order == ["start1", "start2"]
    assert rt.started

    rt.stop()
    assert order == ["start1", "start2", "stop2", "stop1"]
    assert not rt.started


def test_start_is_idempotent():
    rt = Runtime()
    calls = []
    rt.on_start(lambda: calls.append(1))
    rt.start()
    rt.start()
    assert calls == [1]


def test_start_hook_exception_does_not_abort():
    rt = Runtime()
    calls = []

    def boom():
        raise RuntimeError("hook failed")

    rt.on_start(boom)
    rt.on_start(lambda: calls.append(1))
    rt.start()
    assert calls == [1]
    assert rt.started


def test_current_default_and_activate():
    rt = Runtime()
    rt.set_default()
    assert Runtime.current() is rt

    rt2 = Runtime(name="other")
    with Runtime.activate(rt2):
        assert Runtime.current() is rt2
    assert Runtime.current() is rt


def test_keys_and_snapshot():
    rt = Runtime()
    rt.register("a", 1)
    rt.register_factory("b", lambda: 2)
    assert rt.keys() == {"a", "b"}
    assert rt.snapshot() == {"a": 1}


def test_repr():
    rt = Runtime(name="x")
    assert "x" in repr(rt)
