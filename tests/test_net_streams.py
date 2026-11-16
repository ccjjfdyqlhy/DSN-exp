# tests/test_net_streams.py
# The streaming and async-client helpers of infra.net: a SOCKS proxy must
# reach them exactly like the sync client, and the shared-client cache must
# not freeze a proxy that appears (or changes) after the first request.

from __future__ import annotations

import asyncio
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from infra import net


class _EchoHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == '/missing':
            self.send_response(404)
            self.end_headers()
            return
        if self.path == '/events':
            body = b'event: hello\ndata: {"ok": true}\n\n'
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('X-Test-Session', 'abc')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = b'first\nsecond\nthird\n'
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        length = int(self.headers.get('Content-Length') or 0)
        self.rfile.read(length)
        body = b'event: hello\ndata: {"ok": true}\n\n'
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('X-Test-Session', 'abc')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


@pytest.fixture()
def http_server():
    server = ThreadingHTTPServer(('127.0.0.1', 0), _EchoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_address[1]}'
    server.shutdown()
    server.server_close()


def test_stream_lines_yields_the_body(http_server):
    request = urllib.request.Request(http_server + '/line')
    lines = list(net.stream_lines(request, timeout=5))
    assert lines == ['first', 'second', 'third']


def test_stream_lines_reports_the_open_response(http_server):
    seen = {}
    request = urllib.request.Request(http_server + '/events')
    list(net.stream_lines(request, timeout=5,
                          on_open=lambda response: seen.update(response=response)))
    assert seen['response'].headers.get('x-test-session') == 'abc'


def test_stream_lines_raises_on_status(http_server):
    request = urllib.request.Request(http_server + '/missing')
    with pytest.raises(urllib.error.HTTPError):
        list(net.stream_lines(request, timeout=5))


def test_build_async_http_client_returns_a_usable_client(http_server):
    client = net.build_async_http_client(timeout=5)

    async def call() -> int:
        response = await client.get(http_server + '/line')
        return response.status_code

    try:
        assert asyncio.run(call()) == 200
    finally:
        asyncio.run(client.aclose())


def test_the_shared_client_cache_follows_a_late_socks_proxy(monkeypatch):
    monkeypatch.delenv('ALL_PROXY', raising=False)
    monkeypatch.delenv('all_proxy', raising=False)
    monkeypatch.delenv('HTTP_PROXY', raising=False)
    monkeypatch.delenv('http_proxy', raising=False)
    monkeypatch.delenv('HTTPS_PROXY', raising=False)
    monkeypatch.delenv('https_proxy', raising=False)
    monkeypatch.setattr(net, '_http_client', None)
    plain = net.http_client()
    assert plain is net.http_client()

    monkeypatch.setenv('ALL_PROXY', 'socks5://127.0.0.1:1080')
    try:
        # A SOCKS proxy in the environment must not be served the client
        # that was built before the variable existed: it would bypass the
        # proxy for the life of the process.
        assert net.http_client() is not plain
    finally:
        monkeypatch.setattr(net, '_http_client', None)
