# tests/test_dsn_ui_modality_cache.py
# 回归测试：/models、/v1/models、/props 的模型模态解析不得每次都发阻塞 HTTP 探测。
#
# 现场问题：_input_modalities 此前只在「探测成功」或「配置推断为 True」时写缓存，
# 未加载的模型于是每次列表请求都要重发一次带 2s 超时的 /props 请求。
# 6 个本地模型 = 最坏 12s，前端表现为打开会话 / 加载模型列表 / 同步调度状态变慢。

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import apps.dsn_ui.server as server


class _Launcher:
    def __init__(self, running: bool):
        self._running = running

    def is_running(self) -> bool:
        return self._running


class _SourceType:
    def __init__(self, value: str):
        self.value = value


class _Spec:
    def __init__(self, *, running=None, base_url="http://127.0.0.1:8080", source_type=None):
        self.launcher = None if running is None else _Launcher(running)
        self.base_url = base_url
        self.api_key = None
        self.llama_config = None
        self.source_type = _SourceType(source_type) if source_type else None
        self.extra_headers = {}
        self.name = "m"
        self.remote_model_name = "remote-m"


class _Orchestrator:
    def __init__(self, spec):
        self._spec = spec

    def get_model_spec(self, name):
        return self._spec


@pytest.fixture(autouse=True)
def _clear_cache():
    server._modality_cache.clear()
    server._endpoint_reachable_cache.clear()
    yield
    server._modality_cache.clear()
    server._endpoint_reachable_cache.clear()


def test_unreachable_endpoint_costs_one_check_for_many_models(monkeypatch):
    """同一 base_url 上的多个模型只应付一次「端口不可达」的代价。

    实测本机 :4501（LMStudio 未启动）不是拒绝连接而是挂住（localhost 先解析
    到 ::1 且无 RST），5 个 lmstudio 模型逐个探测 = 5 × 超时 = 首屏 /models 5s。
    加了可达性门控 + 缓存后：只做一次 TCP connect，且一个 HTTP 探测都不发。
    """
    # 关掉模态缓存，强制 5 个模型各自独立解析，才能验证「只探测一次」
    monkeypatch.setattr(server, "_MODALITY_CACHE_TTL_S", 0.0)

    specs = [_Spec(base_url="http://127.0.0.1:4501", source_type="api_lmstudio") for _ in range(5)]

    class _Multi:
        def get_model_spec(self, name):
            return specs[int(name)]

    with patch.object(
        server.socket, "create_connection", side_effect=OSError("refused")
    ) as mock_conn, patch("infra.orchestrator.base.local_probe_session") as mock_session:
        for i in range(5):
            assert server._input_modalities(str(i), _Multi()) == ["text"]

    # 不可达时根本不该发 HTTP 探测；TCP 可达性检查也只做一次
    assert mock_session.return_value.get.call_count == 0
    assert mock_conn.call_count == 1


def test_endpoint_reachability_is_cached():
    """可达性结果按 TTL 缓存，避免每个模型都去 TCP connect 一次。"""
    with patch.object(server.socket, "create_connection", side_effect=OSError("refused")) as mock_conn:
        assert server._endpoint_reachable("http://127.0.0.1:4501") is False
        assert server._endpoint_reachable("http://127.0.0.1:4501") is False
        assert server._endpoint_reachable("http://127.0.0.1:4501") is False

    assert mock_conn.call_count == 1


def test_endpoint_reachability_detects_listening_port():
    """端口可连接时应判定为可达。"""
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)

    with patch.object(server.socket, "create_connection", return_value=conn):
        assert server._endpoint_reachable("http://127.0.0.1:8080") is True


def test_lmstudio_probe_skipped_when_endpoint_down():
    """LMStudio 不可达时不发 HTTP 请求，直接走配置推断。"""
    spec = _Spec(base_url="http://127.0.0.1:4501")

    with patch.object(server, "_endpoint_reachable", return_value=False), patch(
        "infra.orchestrator.base.local_probe_session"
    ) as mock_session:
        assert server._lmstudio_vision(spec) is None

    assert mock_session.return_value.get.call_count == 0


def test_no_probe_when_engine_not_running():
    """子进程没在跑时不该发任何 HTTP 探测（本地模型共用端口，探测会白等超时）。"""
    spec = _Spec(running=False)
    orch = _Orchestrator(spec)

    with patch("infra.orchestrator.base.local_probe_session") as mock_session:
        for _ in range(5):
            assert server._input_modalities("m", orch) == ["text"]

    assert mock_session.return_value.get.call_count == 0


def test_probe_runs_once_for_running_engine():
    """引擎在运行时才探测，且结果被缓存，重复调用不再发请求。"""
    spec = _Spec(running=True)
    orch = _Orchestrator(spec)

    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"modalities": {"vision": True, "video": False, "audio": False}}

    with patch("infra.orchestrator.base.local_probe_session") as mock_session:
        mock_session.return_value.get.return_value = resp
        assert server._input_modalities("m", orch) == ["text", "vision"]
        assert server._input_modalities("m", orch) == ["text", "vision"]

    assert mock_session.return_value.get.call_count == 1


def test_negative_result_is_cached():
    """配置推断为「无视觉」时也要缓存 —— 这是此前每次列表都变慢的根因。"""
    spec = _Spec(running=None)  # 无 launcher → 不会探测
    orch = _Orchestrator(spec)

    with patch.object(server, "_configured_vision", return_value=False) as mock_vision:
        for _ in range(5):
            assert server._input_modalities("m", orch) == ["text"]

    assert mock_vision.call_count == 1


def test_cache_expires_after_ttl(monkeypatch):
    """TTL 过期后应重新解析，保证模型加载完成后能力能刷新。"""
    monkeypatch.setattr(server, "_MODALITY_CACHE_TTL_S", 0.0)
    spec = _Spec(running=None)
    orch = _Orchestrator(spec)

    with patch.object(server, "_configured_vision", return_value=True) as mock_vision:
        assert server._input_modalities("m", orch) == ["text", "vision"]
        assert server._input_modalities("m", orch) == ["text", "vision"]

    assert mock_vision.call_count == 2


def test_probe_failure_does_not_raise_and_is_cached():
    """探测抛异常时回退到配置推断，且异常结果同样进入缓存。"""
    spec = _Spec(running=True)
    orch = _Orchestrator(spec)

    with patch("infra.orchestrator.base.local_probe_session") as mock_session, patch.object(
        server, "_configured_vision", return_value=False
    ):
        mock_session.return_value.get.side_effect = OSError("connection refused")
        assert server._input_modalities("m", orch) == ["text"]
        assert server._input_modalities("m", orch) == ["text"]

    assert mock_session.return_value.get.call_count == 1
