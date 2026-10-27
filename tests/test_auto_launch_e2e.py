# tests/test_auto_launch_e2e.py
# 端到端：没有加载模型时发请求 → 后端自动拉起引擎 → 状态同步 → 请求成功。
#
# 用一个真实的子进程"假引擎"（只回 /health 与 /v1/chat/completions）替代
# llama-server，因此这条链路是真的走通了：Popen → 就绪探针 → HTTP → SSE，
# 而不是靠 mock 断言。
#
# 对应现场问题：重试历史消息时后端会自动用上次的模型，但前端不切换加载状态，
# 显存调度页与模型列表里仍然没有可用模型。

from __future__ import annotations

import asyncio
import socket
import sys

import pytest

from infra.orchestrator import LlamaServerConfig, ModelOrchestrator
from infra.orchestrator.local_engine import LocalServerLauncher

#: 极简 OpenAI 兼容"引擎"：/health 返回 200，chat 返回一条 SSE 增量。
_ENGINE_SRC = r'''
import http.server, sys
port = int(sys.argv[1])

class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a):
        pass
    def do_GET(self):
        body = b"{}"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        body = (b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
                b'data: [DONE]\n\n')
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

http.server.ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
'''


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _ScriptedLauncher(LocalServerLauncher):
    """用一段内联 Python 脚本充当被托管的引擎进程。"""

    engine_label = "ScriptedEngine"
    ready_paths = ("/health",)

    def __init__(self, port: int):
        super().__init__()
        self._port = port

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._port}"

    def build_command(self) -> list[str]:
        return [sys.executable, "-c", _ENGINE_SRC, str(self._port)]

    def preflight(self) -> None:
        return None


@pytest.fixture(autouse=True)
def clean_orchestrator():
    ModelOrchestrator.reset_instance()
    yield
    ModelOrchestrator.reset_instance()


@pytest.fixture()
def orchestrator_with_scripted_engine():
    port = _free_port()
    orch = ModelOrchestrator.get_instance(max_concurrent_slots=2)
    cfg = LlamaServerConfig(
        binary_path="/mock/bin/llama-server",
        model_path="/mock/model.gguf",
        port=port,
    )
    orch.register_local_llamacpp("m1", cfg, priority=80)

    launcher = _ScriptedLauncher(port)
    spec = orch.get_model_spec("m1")
    spec.launcher = launcher
    spec.base_url = launcher.base_url
    spec.client_instance._launcher = launcher
    spec.client_instance.base_url = launcher.base_url
    spec.client_instance.timeout = 30.0
    # 修复：调度器的 load/unload 钩子绑定的是注册时创建的 launcher
    # （二进制路径为 /mock/bin/llama-server）。测试替换 launcher 后必须
    # 重绑钩子（含状态回调），否则任何经调度器的加载（invoke 的 use() 租约、
    # 流式租约）都会去拉起不存在的 mock 二进制并失败，且前端收不到状态。
    load_fn, unload_fn = launcher.create_scheduler_hooks(
        load_timeout=60, on_status=orch._make_engine_status_cb("m1"))
    orch._scheduler.register("m1", launcher.base_url, load_fn, unload_fn)

    yield orch, launcher
    launcher.stop()


def test_auto_launch_updates_status_and_serves_request(orchestrator_with_scripted_engine):
    """完整链路：未加载 → 发请求 → 自动拉起 → 状态变 loaded → 请求成功。"""
    orch, launcher = orchestrator_with_scripted_engine

    seen: list[str] = []
    orch.add_status_listener(lambda name, status, extra: seen.append(status))

    # 前置：模型未加载，且没有子进程
    assert {m["name"]: m["loaded"] for m in orch.status()["models"]}["m1"] is False
    assert launcher.is_running() is False

    client = orch.get_model_spec("m1").client_instance

    async def _consume():
        chunks = []
        async for chunk in client.stream([{"role": "user", "content": "hi"}]):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(_consume())

    # 1) 请求真的拿到了引擎的响应
    assert "ok" in chunks, f"自动拉起后应能拿到响应，实际 {chunks!r}"

    # 2) 引擎确实是被本进程拉起来的
    assert launcher.is_running() is True

    # 3) 状态被同步（前端模型列表/显存页读的就是它）
    assert seen == ["loading", "loaded"], f"实际 {seen!r}"
    assert {m["name"]: m["loaded"] for m in orch.status()["models"]}["m1"] is True
    assert "m1" not in orch._loading_models


def test_second_request_does_not_relaunch(orchestrator_with_scripted_engine):
    """引擎已就绪时不应重复上报状态（否则每次请求都刷一条）。"""
    orch, launcher = orchestrator_with_scripted_engine
    client = orch.get_model_spec("m1").client_instance

    async def _consume():
        async for _ in client.stream([{"role": "user", "content": "hi"}]):
            pass

    asyncio.run(_consume())

    seen: list[str] = []
    orch.add_status_listener(lambda name, status, extra: seen.append(status))
    asyncio.run(_consume())

    assert seen == [], f"第二次请求不应再上报状态，实际 {seen!r}"
