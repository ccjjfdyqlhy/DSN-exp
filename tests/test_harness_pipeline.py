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
    # 与 DSN 引擎调度约定一致：priority 值小者先执行（help=5 在 task=40 前）
    assert order == ["p2", "p1"]


def test_plugin_short_circuit_stops_dispatch():
    pm = PluginManager()
    calls = []

    class Stopper(Plugin):
        name = "stopper"
        hooks = [HookPoint.INBOUND]
        priority = 1   # 升序调度：值小者先执行，故先短路

        def on_hook(self, hook, ctx):
            calls.append("stop")
            ctx.filtered = True
            return ctx

    class After(Plugin):
        name = "after"
        hooks = [HookPoint.INBOUND]
        priority = 100

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
def test_hookpoint_superset_contains_dsn_hooks():
    """harness HookPoint 是 dsn 引擎钩子的超集。"""
    from harness.pipeline import HookPoint as HP
    for name in ("PRE_FILTER", "PRE_PROCESS", "POST_TTS"):
        assert hasattr(HP, name), f"缺少 dsn 兼容钩子 {name}"
    # dsn 专属顺序可独立编排
    dsn_order = [HP.PRE_FILTER, HP.PRE_PROCESS, HP.MODEL_INVOKE,
                 HP.POST_PROCESS, HP.POST_TTS]
    assert all(h in HP for h in dsn_order)


def test_context_superset_contains_dsn_fields():
    """harness Context 是 dsn PluginContext 字段的超集。"""
    from harness.pipeline import Context as C
    ctx = C(
        user_id=1, chat_id=42, chat_name="测试", is_asr_input=True,
        tts_enabled=True, model_type="openai", nickname="用户",
        image_data="data:image/png;base64,xxx",
        original_reply="<tool>x</tool>", full_history=[{"role": "user", "content": "hi"}],
        agent_active=True, agent_max_steps=10, agent_token_budget=100,
        skip_model=False, cross_user_id=2, recall_engine=None,
    )
    assert ctx.chat_id == 42
    assert ctx.image_data.startswith("data:")
    assert ctx.agent_active and ctx.agent_max_steps == 10
    assert ctx.original_reply == "<tool>x</tool>"
    # 与 dsn PluginContext 同一对象
    from harness.pipeline import Context as PluginContext
    assert PluginContext is C


def test_dsn_pipeline_subclasses_harness_pipeline():
    """dsn ChatPipeline 继承 harness Pipeline（全局引擎单一实现）。"""
    from apps.dsn.plugins.pipeline import ChatPipeline
    from harness.pipeline import Pipeline
    assert issubclass(ChatPipeline, Pipeline)
    pm = PluginManager()
    pipe = ChatPipeline(pm)
    assert pipe.pm is pm
    assert pipe.hook_order == [HookPoint.PRE_FILTER, HookPoint.PRE_PROCESS,
                               HookPoint.MODEL_INVOKE, HookPoint.POST_PROCESS,
                               HookPoint.POST_TTS]
