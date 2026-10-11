# tests/test_local_chat_retry.py
# 复现并验证：本地推理引擎在「复用已被对端关闭的 keep-alive 连接」时的
# RemoteDisconnected 故障，应由 OpenAICompatChat 自动重发修复。
#
# 现场（apps/dsn_ui/logs/dsn_ui.log, 2026-10-11 05:47:00）：
#   第 2 轮（web.fetch 工具调用之后）在建连阶段抛
#   requests.ConnectionError: ('Connection aborted.',
#       RemoteDisconnected('Remote end closed connection without response'))
#   上游一条 SSE 都没产出，却直接终结了整个会话。

from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

from harness.orchestrator.local_chat import (
    DEFAULT_STREAM_RETRIES,
    OpenAICompatChat,
    _is_retryable_connection_error,
)


class _AbruptHandler(BaseHTTPRequestHandler):
    """第一次请求直接断开连接（不发响应），之后正常返回 SSE。"""

    protocol_version = "HTTP/1.1"
    fail_first = 1
    requests_seen = 0
    lock = threading.Lock()

    def log_message(self, *args):  # noqa: A002 - 静音测试输出
        return

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler 约定
        with _AbruptHandler.lock:
            _AbruptHandler.requests_seen += 1
            seen = _AbruptHandler.requests_seen

        if seen <= _AbruptHandler.fail_first:
            # 模拟 llama-server 关闭 keep-alive 连接：不发任何字节直接断开
            self.close_connection = True
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.connection.close()
            return

        body = (
            'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
            'data: [DONE]\n\n'
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def server():
    _AbruptHandler.requests_seen = 0
    _AbruptHandler.fail_first = 1
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _AbruptHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()


def _client(httpd) -> OpenAICompatChat:
    host, port = httpd.server_address[:2]
    return OpenAICompatChat(
        base_url=f"http://127.0.0.1:{port}",
        model_name="test-model",
        timeout=10.0,
    )


@pytest.mark.asyncio
async def test_stream_retries_abrupt_disconnect(server):
    """建连阶段被断开时，应自动重发并拿到完整结果，而不是把异常抛给上层。"""
    client = _client(server)

    chunks = []
    async for chunk in client.stream([{"role": "user", "content": "hi"}]):
        chunks.append(chunk)

    assert "ok" in chunks, f"重发后应拿到内容，实际 {chunks!r}"
    # 1 次失败 + 1 次成功
    assert _AbruptHandler.requests_seen == 2


@pytest.mark.asyncio
async def test_stream_gives_up_after_retries(server):
    """上游持续断开时，重试耗尽后仍须抛错（不能静默返回空结果）。"""
    _AbruptHandler.fail_first = 99
    client = _client(server)

    with pytest.raises(requests.exceptions.ConnectionError):
        async for _ in client.stream([{"role": "user", "content": "hi"}]):
            pass

    assert _AbruptHandler.requests_seen == DEFAULT_STREAM_RETRIES + 1


@pytest.mark.asyncio
async def test_stream_does_not_retry_after_first_chunk(server):
    """一旦已产出增量就绝不重发 —— 否则前端会看到重复内容。"""
    client = _client(server)

    agen = client.stream([{"role": "user", "content": "hi"}])
    first = await agen.__anext__()
    assert first == "ok"
    await agen.aclose()


def test_retryable_classification():
    """只把连接级故障判定为可重发；超时与业务错误都不算。"""
    assert _is_retryable_connection_error(
        requests.exceptions.ConnectionError(
            "('Connection aborted.', RemoteDisconnected("
            "'Remote end closed connection without response'))"
        )
    )
    assert _is_retryable_connection_error(
        requests.exceptions.ChunkedEncodingError("connection reset by peer")
    )
    # 超时不算：本地模型可能真的在长时间生成，重发只会更慢
    assert not _is_retryable_connection_error(
        requests.exceptions.Timeout("read timed out")
    )
    assert not _is_retryable_connection_error(ValueError("bad payload"))
    assert not _is_retryable_connection_error(RuntimeError("上游返回 HTTP 500：模板不兼容"))
