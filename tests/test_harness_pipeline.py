# tests/test_harness_pipeline.py
from __future__ import annotations

import asyncio

from harness.pipeline import (
    HookPoint, Context, Plugin, AsyncPlugin, PluginManager, Pipeline, EventBus,
)


def test_context_emit_and_short_circuit():
    ctx = Context(message="hi")
    ctx.emit("greeting", "hello").set_output("text", "x").short_circuit("stop")
    assert ctx.filtered
    assert ctx.extra["_events"] == [("greeting", "hello")]
    assert ctx.outputs["text"] == "x"


def test_plugin_manager_priority_order():
    pm = PluginManager()
    order = []

    class P1(Plugin):
        name = "p1"
        hooks = [HookPoint.PREPARE]
        priority = 90

        def on_hook(self, hook, ctx):
            order.append("p1")
            return ctx

    class P2(Plugin):
        name = "p2"
        hooks = [HookPoint.PREPARE]
        priority = 10

        def on_hook(self, hook, ctx):
            order.append("p2")
            return ctx

    pm.register(P2())
    pm.register(P1())
    asyncio.run(pm.dispatch(HookPoint.PREPARE, Context()))
    assert order == ["p1", "p2"]  # 高优先级先


def test_plugin_short_circuit_stops_dispatch():
    pm = PluginManager()
    calls = []

    class Stopper(Plugin):
        name = "stopper"
        hooks = [HookPoint.INBOUND]
        priority = 100

        def on_hook(self, hook, ctx):
            calls.append("stop")
            ctx.filtered = True
            return ctx

    class After(Plugin):
        name = "after"
        hooks = [HookPoint.INBOUND]
        priority = 1

        def on_hook(self, hook, ctx):
            calls.append("after")
            return ctx

    pm.register(After())
    pm.register(Stopper())
    asyncio.run(pm.dispatch(HookPoint.INBOUND, Context()))
    assert calls == ["stop"]


def test_disable_plugin():
    pm = PluginManager()
    calls = []

    class P(Plugin):
        name = "p"
        hooks = [HookPoint.PREPARE]

        def on_hook(self, hook, ctx):
            calls.append(1)
            return ctx

    pm.register(P())
    pm.disable("p")
    asyncio.run(pm.dispatch(HookPoint.PREPARE, Context()))
    assert calls == []


def test_pipeline_runs_all_hooks_in_order():
    pm = PluginManager()
    seen = []

    class Probe(Plugin):
        name = "probe"
        hooks = [HookPoint.INBOUND, HookPoint.PREPARE, HookPoint.MODEL_INVOKE,
                 HookPoint.POST_PROCESS, HookPoint.OUTPUT]
        priority = 50

        def on_hook(self, hook, ctx):
            seen.append(hook.value)
            return ctx

    pm.register(Probe())
    pipe = Pipeline(pm)
    ctx = asyncio.run(pipe.process(Context(message="x")))
    assert seen == ["inbound", "prepare", "model_invoke", "post_process", "output"]
    assert "total_ms" in ctx.extra["_pipeline_timing"]


def test_event_bus_sync_and_async():
    bus = EventBus()
    got = []

    bus.subscribe("evt", lambda p: got.append(("sync", p)))
    async def handler(p):
        got.append(("async", p))
    bus.subscribe("evt", handler)

    asyncio.run(bus.publish_async("evt", 42))
    assert ("sync", 42) in got
    assert ("async", 42) in got


def test_event_bus_unsubscribe():
    bus = EventBus()
    got = []

    def h(p):
        got.append(p)

    unsub = bus.subscribe("e", h)
    bus.publish("e", 1)
    unsub()
    bus.publish("e", 2)
    assert got == [1]
