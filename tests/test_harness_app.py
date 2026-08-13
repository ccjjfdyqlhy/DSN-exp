# tests/test_harness_app.py
# 应用层测试：harness-native 参考应用 + DSN bundle 拆包。

from __future__ import annotations

from apps.dsn.bundles import make_dsn_bundles
from apps.dsn.settings import bind_dsn_settings
from apps.text_agent import TextAgentApp
from harness import AppBundleRegistry, Runtime, Settings
from harness.models.base import ChatResponse, ToolCall
from harness.models.stub import StubChatClient


def test_text_agent_runs_on_harness():
    stub = StubChatClient(responses=[
        ChatResponse(content="", tool_calls=[
            ToolCall(id="1", name="calculator.eval", arguments={"expression": "2*21"})]),
        ChatResponse(content="等于 42", model="stub"),
    ])
    app = TextAgentApp(stub)
    assert "calculator.eval" in app.tools
    reply = app.run("2*21 等于多少？")
    assert reply == "等于 42"
    assert app.memory.count() == 1
    assert Runtime.current() is app.runtime


def test_text_agent_time_tool():
    stub = StubChatClient(responses=[
        ChatResponse(content="", tool_calls=[ToolCall(id="1", name="time.now", arguments={})]),
        ChatResponse(content="现在是某时刻", model="stub"),
    ])
    app = TextAgentApp(stub)
    reply = app.run("现在几点？")
    assert reply == "现在是某时刻"


def test_dsn_settings_namespaces():
    s = bind_dsn_settings(Settings())
    assert "voice" in s.namespaces()
    assert s.namespace("voice").tts_enabled in (True, False)
    assert s.namespace("model").agent_max_steps >= 1


def test_dsn_bundles_registry_and_routes():
    rt = Runtime()
    rt.register("db", object())
    blueprints = {"auth": object(), "heartbeat": object(), "maintenance": None}

    bundles = make_dsn_bundles(blueprints)
    names = [b.name for b in bundles]
    assert names == ["core", "companion", "voice", "personal",
                     "media", "vision", "tracking", "agent_api", "maintenance"]

    registry = AppBundleRegistry(rt)
    for b in bundles:
        registry.add(b)
    registry.install_all()

    core = next(b for b in bundles if b.name == "core")
    assert core.blueprints == [blueprints["auth"]]
    voice = next(b for b in bundles if b.name == "voice")
    assert voice.blueprints == [blueprints["heartbeat"]]
    assert "db" in rt.keys()


def test_dsn_bundle_settings_namespaces_declared():
    from apps.dsn.bundles import VoiceBundle, CompanionBundle
    assert "voice" in VoiceBundle.settings_namespaces
    assert "companion" in CompanionBundle.settings_namespaces
