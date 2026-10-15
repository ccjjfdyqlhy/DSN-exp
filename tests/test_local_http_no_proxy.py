# tests/test_local_http_no_proxy.py
# 回归测试：本地引擎（127.0.0.1）的 HTTP 请求必须忽略代理环境变量。
#
# 现场（2026-10-12 06:38~06:41）：
#   ALL_PROXY=socks5h://127.0.0.1:10808 指向一个未运行的代理。requests 默认
#   trust_env=True，会把发往 localhost 的请求也交给代理 → 全部 ConnectionError。
#   LocalServerLauncher.is_ready() 因此**永远**探不到就绪：llama-server 其实
#   已经把 27B 模型加载完成，界面却一直卡在加载中，直到 180s 超时；
#   用户在 06:41:54 放弃并点「终止」，又触发了 NoneType.poll 的竞态。

from __future__ import annotations

import http.server
import threading

import pytest
import requests

from infra.orchestrator.base import local_http_session
from infra.orchestrator.local_engine import LocalServerLauncher


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # noqa: A002 - 静音测试输出
        return

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler 约定
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def local_server():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture()
def dead_proxy(monkeypatch):
    """把代理指向一个确定没有服务在监听的端口。"""
    for var in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy",
                "HTTPS_PROXY", "https_proxy"):
        monkeypatch.setenv(var, "socks5h://127.0.0.1:9")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    return "socks5h://127.0.0.1:9"


def test_local_session_ignores_proxy_env(local_server, dead_proxy):
    """本地会话必须关掉 trust_env，否则会被 ALL_PROXY 接管。"""
    session = local_http_session()

    assert session.trust_env is False

    resp = session.get(f"{local_server}/health", timeout=5)

    assert resp.status_code == 200
    assert resp.text == "ok"


def test_bare_requests_is_hijacked_by_proxy(local_server, dead_proxy):
    """对照实验：裸 requests.get 在同样条件下会失败（证明该环境确实有问题）。"""
    with pytest.raises(requests.exceptions.RequestException):
        requests.get(f"{local_server}/health", timeout=5)


class _ProbeLauncher(LocalServerLauncher):
    engine_label = "ProbeEngine"
    ready_paths = ("/health",)

    def __init__(self, url: str):
        super().__init__()
        self._url = url

    @property
    def base_url(self) -> str:
        return self._url

    def build_command(self) -> list[str]:
        return ["true"]

    def preflight(self) -> None:
        return None


def test_readiness_probe_survives_dead_proxy(local_server, dead_proxy):
    """核心断言：代理不可用时，就绪探针仍能正确判定引擎已就绪。"""
    launcher = _ProbeLauncher(local_server)

    assert launcher.is_ready(timeout=2.0) is True
