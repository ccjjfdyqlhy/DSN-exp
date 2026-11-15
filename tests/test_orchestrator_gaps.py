# tests/test_orchestrator_gaps.py
# Gaps filled for the coding superset pack: effort dial, stream-creation
# retry, request passthroughs, and infra.net proxy helpers.

from __future__ import annotations

import asyncio
import importlib.util
import sys
from types import SimpleNamespace

import pytest

from infra import net
from infra.orchestrator.anthropic import AnthropicCompatClient, effort_thinking_budget
from infra.orchestrator.base import resolve_effort, retrying_stream
from infra.orchestrator.openai import OpenAICompatClient


# ── resolve_effort ───────────────────────────────────────────────────

def test_resolve_effort_exact_and_case():
    assert resolve_effort('high', ['low', 'high']) == 'high'
    assert resolve_effort('HIGH', ['high', 'low']) == 'high'


def test_resolve_effort_alias_walks_down():
    assert resolve_effort('ultra', ['low', 'medium', 'high']) == 'high'
    assert resolve_effort('xhigh', ['low', 'medium', 'max']) == 'max'


def test_resolve_effort_nearest_rank():
    assert resolve_effort('ultra', ['low', 'medium']) == 'medium'
    assert resolve_effort('low', ['high', 'ultra']) == 'high'


def test_resolve_effort_no_options_returns_configured():
    assert resolve_effort('medium', []) == 'medium'
    assert resolve_effort('medium', None) == 'medium'


# ── retrying_stream ──────────────────────────────────────────────────

class _Fail(Exception):
    def __init__(self, status: int = 0):
        super().__init__('boom')
        self.status_code = status


def _agen(items, fail_after=None, error=None):
    async def gen():
        produced = 0
        for item in items:
            if fail_after is not None and produced >= fail_after:
                raise error or _Fail()
            produced += 1
            yield item
        if fail_after is not None and error is not None:
            raise error
    return gen()


class FlakyClient:
    """Stream factory scripted per call: ('ok', items) / ('create_fail', status) / ('midstream', items)."""

    model = 'stub'

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def stream(self, messages, tools=None, **kwargs):
        behavior = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        kind = behavior[0]
        if kind == 'create_fail':
            return _agen([], fail_after=0, error=_Fail(behavior[1] if len(behavior) > 1 else 0))
        if kind == 'midstream':
            return _agen(list(behavior[1]), fail_after=len(behavior[1]), error=_Fail())
        return _agen(list(behavior[1]))


def _run(collect):
    async def runner():
        out = []
        async for item in collect:
            out.append(item)
        return out
    return asyncio.run(runner())


def test_retrying_stream_recovers_after_creation_failures():
    waits = []

    async def fake_sleep(seconds):
        waits.append(seconds)

    client = FlakyClient([('create_fail', 503), ('create_fail', 503), ('ok', ['a', 'b'])])
    events = _run(retrying_stream(client, [], sleep=fake_sleep))
    assert client.calls == 3
    retries = [e['retry'] for e in events if isinstance(e, dict) and 'retry' in e]
    assert [r['attempt'] for r in retries] == [1, 2]
    assert waits == [1, 2]
    assert [e for e in events if e == 'a' or e == 'b'] == ['a', 'b']


def test_retrying_stream_skips_400():
    client = FlakyClient([('create_fail', 400), ('ok', ['a'])])
    with pytest.raises(_Fail):
        _run(retrying_stream(client, []))
    assert client.calls == 1


def test_retrying_stream_never_replays_after_emission():
    client = FlakyClient([('midstream', ['a'])])
    with pytest.raises(_Fail):
        _run(retrying_stream(client, []))
    assert client.calls == 1


def test_retrying_stream_raises_when_exhausted():
    client = FlakyClient([('create_fail', 503)])
    with pytest.raises(_Fail):
        _run(retrying_stream(client, [], attempts=3))
    assert client.calls == 3


def test_retrying_stream_custom_predicate():
    client = FlakyClient([('create_fail', 429), ('ok', ['a'])])
    with pytest.raises(_Fail):
        _run(retrying_stream(client, [], retryable=lambda error: False))
    assert client.calls == 1


# ── OpenAICompatClient passthroughs ──────────────────────────────────

def _capture_agen(capture, key):
    async def create(**params):
        capture[key] = params
        async def gen():
            if False:
                yield ''    # make it an async generator without emitting
        return gen()
    return create


def test_openai_stream_passes_reasoning_effort():
    client = OpenAICompatClient(api_key='k')
    capture: dict = {}
    client._async_client.chat.completions = SimpleNamespace(
        create=_capture_agen(capture, 'chat'))
    _run(client.stream([{'role': 'user', 'content': 'hi'}], None,
                       reasoning_effort='high', temperature=0.2))
    assert capture['chat']['reasoning_effort'] == 'high'
    assert capture['chat']['temperature'] == 0.2


def test_openai_stream_omits_reasoning_effort_when_not_given():
    client = OpenAICompatClient(api_key='k')
    capture: dict = {}
    client._async_client.chat.completions = SimpleNamespace(
        create=_capture_agen(capture, 'chat'))
    _run(client.stream([{'role': 'user', 'content': 'hi'}], None))
    assert 'reasoning_effort' not in capture['chat']


def test_openai_stream_emits_finish_event():
    client = OpenAICompatClient(api_key='k')

    class FakeCompletions:
        async def create(self, **params):
            async def gen():
                yield SimpleNamespace(choices=[], usage=None)
                yield SimpleNamespace(
                    choices=[SimpleNamespace(
                        finish_reason='stop',
                        delta=SimpleNamespace(content='hi', reasoning_content=None,
                                              tool_calls=None))],
                    usage=None)
            return gen()

    client._async_client.chat.completions = FakeCompletions()
    events = _run(client.stream([{'role': 'user', 'content': 'hi'}], None))
    assert events[-1] == {'finish': 'stop'}
    assert 'hi' in [e for e in events if isinstance(e, str)]


def test_openai_responses_finish_maps_incomplete_details():
    client = OpenAICompatClient(api_key='k', protocol='responses')

    class FakeResponses:
        def stream(self, **params):
            class CM:
                async def __aenter__(self):
                    async def gen():
                        yield SimpleNamespace(
                            type='response.completed',
                            response=SimpleNamespace(
                                usage=None, status='incomplete',
                                incomplete_details=SimpleNamespace(
                                    reason='max_output_tokens')))
                    return gen()
                async def __aexit__(self, *a):
                    return False
            return CM()

    client._async_client.responses = FakeResponses()
    events = _run(client.stream([{'role': 'user', 'content': 'hi'}], None))
    assert events[-1] == {'finish': 'length'}


def test_chat_message_from_dict_roundtrip():
    from infra.models.base import ChatMessage
    raw = {'role': 'assistant', 'content': None, 'reasoning_content': 'r',
           'tool_calls': [{'id': 'c1', 'type': 'function',
                           'function': {'name': 'f', 'arguments': '{}'}}]}
    message = ChatMessage.from_dict(raw)
    assert isinstance(message, ChatMessage)
    assert message.to_dict() == raw


def test_openai_responses_passes_reasoning_and_cache_key():
    client = OpenAICompatClient(api_key='k', protocol='responses')
    capture: dict = {}

    class FakeResponses:
        def stream(self, **params):
            capture['responses'] = params

            class CM:
                async def __aenter__(self):
                    async def gen():
                        if False:
                            yield ''
                    return gen()
                async def __aexit__(self, *a):
                    return False
            return CM()

    client._async_client.responses = FakeResponses()
    _run(client.stream([{'role': 'user', 'content': 'hi'}], None,
                       reasoning={'effort': 'high', 'summary': 'auto'},
                       prompt_cache_key='sha256:abc'))
    assert capture['responses']['reasoning'] == {'effort': 'high', 'summary': 'auto'}
    assert capture['responses']['prompt_cache_key'] == 'sha256:abc'


def test_openai_client_accepts_http_client():
    import httpx
    sync_injected = httpx.Client()
    async_injected = httpx.AsyncClient()
    client = OpenAICompatClient(api_key='k', http_client=sync_injected,
                                async_http_client=async_injected)
    # the SDK wires the injected transports through on both sides
    assert client._client._client is sync_injected
    assert client._async_client._client is async_injected
    sync_injected.close()
    asyncio.run(async_injected.aclose())


# ── anthropic effort budget ──────────────────────────────────────────

def test_effort_thinking_budget_table():
    assert effort_thinking_budget('low', 8192) == {'type': 'enabled', 'budget_tokens': 2048}
    assert effort_thinking_budget('ultra', 24576) == {'type': 'enabled', 'budget_tokens': 24575}
    assert effort_thinking_budget('unknown', 8192)['budget_tokens'] == 4096


def test_effort_thinking_budget_clamps_to_window():
    # budget must stay in [1024, max_tokens)
    assert effort_thinking_budget('ultra', 4096) == {'type': 'enabled', 'budget_tokens': 4095}
    assert effort_thinking_budget('medium', 1000) is None
    assert effort_thinking_budget(None, 8192) is None
    assert effort_thinking_budget('high', None) is None


class _FakeAnthropic:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.captured: dict = {}
        self.messages = self
        _FakeAnthropic.instances.append(self)

    def create(self, **params):
        self.captured = params
        return SimpleNamespace(content=[], usage=None, stop_reason=None, model='m')


def test_anthropic_client_applies_thinking_and_tool_choice(monkeypatch):
    monkeypatch.setitem(sys.modules, 'anthropic',
                        SimpleNamespace(Anthropic=_FakeAnthropic,
                                        AsyncAnthropic=_FakeAnthropic))
    _FakeAnthropic.instances = []
    client = AnthropicCompatClient(api_key='k', effort='ultra', max_tokens=4096,
                                   tool_choice='auto')
    client.invoke([{'role': 'user', 'content': 'hi'}],
                  tools=[{'name': 'f', 'description': 'd', 'parameters': {}}],
                  max_tokens=4096)
    sync_client = _FakeAnthropic.instances[0]
    assert sync_client.captured['thinking'] == {'type': 'enabled', 'budget_tokens': 4095}
    assert sync_client.captured['tool_choice'] == 'auto'


def test_anthropic_client_defaults_leave_request_untouched(monkeypatch):
    monkeypatch.setitem(sys.modules, 'anthropic',
                        SimpleNamespace(Anthropic=_FakeAnthropic,
                                        AsyncAnthropic=_FakeAnthropic))
    _FakeAnthropic.instances = []
    client = AnthropicCompatClient(api_key='k')
    client.invoke([{'role': 'user', 'content': 'hi'}], max_tokens=4096)
    params = _FakeAnthropic.instances[0].captured
    assert 'thinking' not in params
    assert 'tool_choice' not in params


# ── infra.net ────────────────────────────────────────────────────────

_PROXY_VARS = ('https_proxy', 'HTTPS_PROXY', 'http_proxy', 'HTTP_PROXY',
               'all_proxy', 'ALL_PROXY')


def test_normalize_proxy_url():
    assert net.normalize_proxy_url('socks://host:1080') == 'socks5://host:1080'
    assert net.normalize_proxy_url('http://host:8080') == 'http://host:8080'
    assert net.normalize_proxy_url('host:1080') == 'http://host:1080'
    assert net.normalize_proxy_url('') == ''
    with pytest.raises(net.ProxyError):
        net.normalize_proxy_url('socks4://host:1080')


def test_has_socks_proxy(monkeypatch):
    for var in _PROXY_VARS:
        monkeypatch.delenv(var, raising=False)
    assert net.has_socks_proxy() is False
    monkeypatch.setenv('ALL_PROXY', 'socks5h://127.0.0.1:10808')
    assert net.has_socks_proxy() is True
    monkeypatch.setenv('ALL_PROXY', 'http://127.0.0.1:10808')
    assert net.has_socks_proxy() is False


def test_build_http_client_without_proxy(monkeypatch):
    for var in _PROXY_VARS:
        monkeypatch.delenv(var, raising=False)
    client = net.build_http_client(timeout=5.0)
    assert client.timeout.read == 5.0
    client.close()


@pytest.mark.skipif(importlib.util.find_spec('socksio') is not None,
                    reason='socksio installed: the SOCKS transport would build')
def test_build_http_client_raises_without_socksio(monkeypatch):
    monkeypatch.setattr(net, 'environment_proxies',
                        lambda: {'all://': 'socks5://127.0.0.1:10808'})
    with pytest.raises(net.ProxyError):
        net.build_http_client()
