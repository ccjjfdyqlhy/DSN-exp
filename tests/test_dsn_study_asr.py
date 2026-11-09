"""dsn_study 语音识别（ASR）接入测试。

覆盖：
  1. ASR HTTP 客户端（mock requests，不触网）
  2. ASRService：识别 / 失败降级 / 音频归一化 / 状态视图
  3. infra 资源池注册（adopt 模式，不拉起 sidecar）+ conda 启动策略
  4. 路由契约与错误码（401 / 403 / 400 / 500）与"空识别返回 JSON"分支
  5. sidecar（asr_server.py）：懒加载 / health / 转写 / 错误兜底
  6. 配置键齐备
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys
import threading
import wave
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 测试期间不拉起真实 sidecar（需 conda 环境 + GPU + 分钟级权重加载）
os.environ.setdefault("ASR_AUTOSTART", "false")
os.environ.setdefault("ASR_WARMUP", "false")


def _wav_bytes(seconds: float = 0.5, rate: int = 16000) -> bytes:
    """构造一段最小合法 WAV（16 kHz / 单声道 / 16bit）。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


# ── 1. 客户端 ──

def test_asr_client_transcribe_and_probe():
    from apps.dsn_study.models import asr_client as mod

    class _Resp:
        status_code = 200
        text = '{"text": "你好", "segments": [[0, 100]]}'

        def json(self):
            return {"text": "你好", "segments": [[0, 100]], "elapsed": 0.1}

    class _Session:
        def __init__(self):
            self.posts = []

        def post(self, url, data=None, headers=None, timeout=None):
            self.posts.append((url, data))
            return _Resp()

        def get(self, url, timeout=None):
            class _R:
                status_code = 200

                def json(self):
                    return {"ready": True, "loaded": True}
            return _R()

    c = mod.ASRClient("http://127.0.0.1:9881")
    c.session = _Session()
    text, segments = c.transcribe(_wav_bytes())
    assert text == "你好"
    assert segments == [[0, 100]]
    assert c.session.posts[0][0].endswith("/asr")
    assert c.probe() is True
    assert c.health().get("ready") is True


def test_asr_client_errors():
    from apps.dsn_study.models.asr_client import ASRClient, ASRRequestError

    c = ASRClient("http://127.0.0.1:9881")
    with pytest.raises(ASRRequestError):
        c.transcribe(b"")           # 空音频
    with pytest.raises(ASRRequestError):
        ASRClient("").transcribe(b"x")  # 未配置 base_url

    class _BadSession:
        def post(self, url, data=None, headers=None, timeout=None):
            class _R:
                status_code = 503
                text = "ASR 模型加载失败"

                def json(self):
                    return {"error": "ASR 模型加载失败"}
            return _R()

    c.session = _BadSession()
    with pytest.raises(ASRRequestError):
        c.transcribe(b"x")


# ── 2. ASRService ──

class _StubASR:
    """替身识别门面（不触真实 sidecar）。"""

    def __init__(self, text="今天复习二次函数", error=""):
        self._text = text
        self._error = error
        self.calls = []

    def transcribe(self, audio_bytes):
        self.calls.append(audio_bytes)
        if self._error:
            return "", []
        return self._text, []

    def transcribe_with_error(self, audio_bytes):
        self.calls.append(audio_bytes)
        if self._error:
            return "", [], self._error
        return self._text, [], ""

    def normalize_audio(self, audio_bytes):
        return audio_bytes


def test_asr_service_transcribe_uses_lease():
    from apps.dsn_study.asr import ASRService
    import contextlib

    leased = []

    class _Pool:
        def lease(self, name):
            leased.append(name)

            @contextlib.contextmanager
            def _cm():
                yield object()
            return _cm()

    class _Client:
        def transcribe(self, audio_bytes):
            return "识别结果", [[0, 1]]

    svc = ASRService(pool=_Pool(), client=_Client())
    assert svc.available
    text, segments = svc.transcribe(_wav_bytes())
    assert text == "识别结果"
    assert segments == [[0, 1]]
    assert leased == ["asr"], "必须经资源池取租约（保证 sidecar 就绪）"


def test_asr_service_degrades_gracefully():
    """sidecar 不可用时必须返回空文本 + 错误，**绝不抛异常**。"""
    from apps.dsn_study.asr import ASRService

    svc = ASRService()
    assert svc.available is False
    text, segments = svc.transcribe(_wav_bytes())
    assert text == "" and segments == []

    # 客户端抛错也要吞掉
    class _Boom:
        def transcribe(self, audio_bytes):
            raise RuntimeError("boom")

    svc2 = ASRService(pool=None, client=_Boom())
    text2, seg2 = svc2.transcribe(_wav_bytes())
    assert text2 == "" and seg2 == []


def test_asr_service_transcribe_b64():
    from apps.dsn_study.asr import ASRService

    class _Pool:
        def lease(self, name):
            import contextlib

            @contextlib.contextmanager
            def _cm():
                yield object()
            return _cm()

    svc = ASRService(pool=_Pool(), client=_StubASR(text="好的"))
    b64 = base64.b64encode(_wav_bytes()).decode("ascii")
    text, err = svc.transcribe_b64(b64)
    assert text == "好的" and err == ""

    # 非法 base64 → 返回错误而非抛异常
    text2, err2 = svc.transcribe_b64("!!!not-base64!!!")
    assert text2 == "" and "base64" in err2.lower()


def test_asr_normalize_audio():
    """归一化：有 ffmpeg 时产出 16k 单声道 WAV；无 ffmpeg 时原样返回。"""
    from apps.dsn_study.asr import ASRService
    import shutil

    raw = _wav_bytes(seconds=0.1, rate=8000)   # 非 16k，模拟设备差异
    out = ASRService.normalize_audio(raw)
    assert out, "归一化不应返回空"
    if shutil.which("ffmpeg"):
        with wave.open(io.BytesIO(out)) as w:
            assert w.getframerate() == 16000
            assert w.getnchannels() == 1
    else:
        assert out == raw, "无 ffmpeg 时应原样返回"

    # 空输入
    assert ASRService.normalize_audio(b"") == b""


def test_asr_service_create_disabled():
    """ASR_ENABLED=false → 不可用实例（不抛错）。"""
    from apps.dsn_study.asr import ASRService
    from apps.dsn_study.config import Config

    old = Config.ASR_ENABLED
    try:
        Config.ASR_ENABLED = False
        svc = ASRService.create()
        assert svc.available is False
        assert svc.disabled_reason
        assert svc.status()["enabled"] is False
    finally:
        Config.ASR_ENABLED = old


# ── 3. 资源池注册 ──

def test_asr_resource_registered_in_pool(monkeypatch):
    """adopt 模式：只注册不拉起（不依赖本机 conda/GPU）。"""
    from apps.dsn_study.config import Config
    from apps.dsn_study.models import resource_setup as rs

    monkeypatch.setattr(Config, "ASR_AUTOSTART", False, raising=False)
    pool = rs.ResourcePool(max_concurrent=1)
    rs._build_asr(pool)  # noqa: SLF001 —— 直接验证注册路径
    spec = pool.get_spec(rs.ASR_RESOURCE)
    assert spec is not None
    assert spec.kind == rs.ResourceKind.ASR
    assert spec.resident is True, "ASR 必须常驻（避免每次识别重拉 sidecar）"
    assert spec.immediate is False
    info = [r for r in pool.list_resources() if r["name"] == rs.ASR_RESOURCE][0]
    assert info.get("adopt") is True


def test_asr_launch_spec_conda_mode(monkeypatch):
    """conda 模式：argv[0] 必须是目标环境的解释器，入口是 asr_server.py。"""
    from apps.dsn_study.config import Config
    from apps.dsn_study.models import resource_setup as rs

    monkeypatch.setattr(Config, "ASR_AUTOSTART", True, raising=False)
    monkeypatch.setattr(Config, "ASR_LAUNCH_MODE", "conda", raising=False)
    monkeypatch.setattr(Config, "ASR_CONDA_ENV", "GPTSoVits", raising=False)
    monkeypatch.setattr(Config, "ASR_PORT", 9881, raising=False)
    spec = rs._asr_launch_spec()  # noqa: SLF001
    assert spec is not None
    assert spec.mode == rs.LaunchMode.CONDA
    assert spec.conda_env == "GPTSoVits"
    assert spec.command[0].endswith("python") or spec.command[0] == "python"
    assert any("asr_server.py" in c for c in spec.command)
    assert "9881" in spec.command


def test_asr_port_follows_base_url(monkeypatch):
    """端口必须由 ASR_BASE_URL 推导：否则资源池会探测一个没人在听的端口。"""
    from apps.dsn_study.config import Config
    from apps.dsn_study.models import resource_setup as rs

    monkeypatch.setattr(Config, "ASR_BASE_URL", "http://127.0.0.1:9881", raising=False)
    assert rs._asr_port() == "9881"  # noqa: SLF001

    monkeypatch.setattr(Config, "ASR_BASE_URL", "http://127.0.0.1:59999", raising=False)
    assert rs._asr_port() == "59999"  # noqa: SLF001

    # URL 没带端口 → 回退 ASR_PORT
    monkeypatch.setattr(Config, "ASR_BASE_URL", "http://127.0.0.1", raising=False)
    monkeypatch.setattr(Config, "ASR_PORT", 9881, raising=False)
    assert rs._asr_port() == "9881"  # noqa: SLF001


def test_asr_device_resolution(monkeypatch):
    """ASR_DEVICE + ASR_GPU_ID → cuda:N。"""
    from apps.dsn_study.config import Config
    from apps.dsn_study.models import resource_setup as rs

    monkeypatch.setattr(Config, "ASR_DEVICE", "cuda", raising=False)
    monkeypatch.setattr(Config, "ASR_GPU_ID", "1", raising=False)
    assert rs._asr_device() == "cuda:1"  # noqa: SLF001

    monkeypatch.setattr(Config, "ASR_GPU_ID", "", raising=False)
    assert rs._asr_device() == "cuda"  # noqa: SLF001


# ── 4. 路由契约 ──

@pytest.fixture(scope="module")
def study_app():
    import tempfile
    os.environ["QUESTION_BANK_DB_PATH"] = tempfile.mkdtemp(prefix="dsn_study_asr_") + "/qb.db"
    from apps.dsn_study.boot import create_application
    return create_application()


def test_asr_routes_registered(study_app):
    rules = {r.rule for r in study_app.url_map.iter_rules()}
    assert "/api/asr/recognize" in rules
    assert "/api/asr/passthrough" in rules


def test_asr_passthrough_missing_audio(study_app):
    client = study_app.test_client()
    rv = client.post("/api/asr/passthrough", json={})
    assert rv.status_code == 400
    assert rv.get_json()["error"] == "Missing audio"


def test_asr_passthrough_invalid_base64(study_app):
    client = study_app.test_client()
    rv = client.post("/api/asr/passthrough", json={"audio_b64": "!!!not-base64!!!"})
    assert rv.status_code == 400
    assert rv.get_json()["error"] == "Invalid base64"


def test_asr_recognize_missing_file(study_app):
    client = study_app.test_client()
    rv = client.post("/api/asr/recognize", data={})
    assert rv.status_code == 400
    assert rv.get_json()["error"] == "Missing audio file"


def test_asr_disabled_returns_403(study_app):
    client = study_app.test_client()
    old = study_app.config.get("ASR_ENABLED")
    study_app.config["ASR_ENABLED"] = False
    try:
        rv = client.post("/api/asr/passthrough", json={"audio_b64": "AAA="})
        assert rv.status_code == 403
        assert rv.get_json()["error"] == "ASR disabled"

        rv2 = client.post("/api/asr/recognize", data={})
        assert rv2.status_code == 403
        assert rv2.get_json()["error"] == "ASR disabled"
    finally:
        study_app.config["ASR_ENABLED"] = old


def test_asr_passthrough_empty_text_returns_json(study_app):
    """识别为空 → 返回 JSON（非 SSE），契约与参考实现一致。"""
    from apps.dsn_study.api import asr as asr_api

    stub = _StubASR(text="")
    old = asr_api._asr  # noqa: SLF001
    asr_api.init_asr_api(stub, study_app.config.get("AUTH_MANAGER"), None)
    try:
        client = study_app.test_client()
        b64 = base64.b64encode(_wav_bytes()).decode("ascii")
        rv = client.post("/api/asr/passthrough",
                         json={"audio_b64": b64, "chat_id": 7})
        assert rv.status_code == 200
        assert rv.mimetype == "application/json"
        body = rv.get_json()
        assert body["reply"] == ""
        assert body["chat_id"] == 7
        assert body["filtered"] is True
    finally:
        asr_api.init_asr_api(old, study_app.config.get("AUTH_MANAGER"), None)


def test_asr_failure_returns_500_not_filtered(study_app):
    """sidecar 挂了 → 500 {"error":"ASR processing failed"}。

    **不能**返回 200 + filtered:true —— 那是"识别成功但没听清"的语义。
    参考实现 apps/dsn/api/app.py:345-352 明确区分这两者。
    """
    from apps.dsn_study.api import asr as asr_api

    stub = _StubASR(error="sidecar 不可达")
    old = asr_api._asr  # noqa: SLF001
    asr_api.init_asr_api(stub, study_app.config.get("AUTH_MANAGER"), None)
    try:
        client = study_app.test_client()
        b64 = base64.b64encode(_wav_bytes()).decode("ascii")
        rv = client.post("/api/asr/passthrough", json={"audio_b64": b64})
        assert rv.status_code == 500
        assert rv.get_json()["error"] == "ASR processing failed"
    finally:
        asr_api.init_asr_api(old, study_app.config.get("AUTH_MANAGER"), None)


def test_asr_service_assembled(study_app):
    """ASRService 应被装配（即使不可用也要有实例，不能是 None）。"""
    svc = study_app.config.get("ASR_SERVICE")
    assert svc is not None, "boot 未装配 ASRService"
    assert hasattr(svc, "available")
    status = svc.status()
    assert "enabled" in status and "resource" in status


# ── 5. sidecar 服务 ──

class _StubModel:
    """替身 FunASR 模型（不加载真权重）。"""

    def __init__(self, text="测试语音"):
        self._text = text
        self.calls = []

    def generate(self, **kw):
        self.calls.append(kw)
        return [{"text": self._text, "timestamp": [[0, 100]]}]


def test_asr_server_model_transcribe():
    from apps.dsn_study import asr_server

    m = asr_server.ASRModel(device="cpu")
    m._model = _StubModel("你好世界")  # noqa: SLF001
    text, segments = m.transcribe(_wav_bytes())
    assert text == "你好世界"
    assert segments == [[0, 100]]
    assert m.loaded is True

    # 空音频 → 空结果，不调模型
    text2, seg2 = m.transcribe(b"")
    assert text2 == "" and seg2 == []


def test_asr_server_model_load_failure_is_graceful():
    """模型加载失败 → 返回 False + 中文原因，绝不抛异常。"""
    from apps.dsn_study import asr_server

    m = asr_server.ASRModel(device="cpu")

    def _boom():
        raise RuntimeError("no torch here")

    # 伪造 funasr 导入失败：把 ensure_loaded 的 loader 换成会抛异常的
    import types
    fake = types.ModuleType("funasr")

    def _auto_model(**kw):
        raise RuntimeError("no torch here")

    fake.AutoModel = _auto_model
    old = sys.modules.get("funasr")
    sys.modules["funasr"] = fake
    try:
        ok = m.ensure_loaded()
        assert ok is False
        assert m.loaded is False
        assert m.load_error, "失败原因必须记录"
        assert "RuntimeError" in m.load_error
    finally:
        if old is None:
            sys.modules.pop("funasr", None)
        else:
            sys.modules["funasr"] = old


def test_asr_server_http_contract():
    """起一个真实的 sidecar 实例，验证 /health 与 /asr 的 HTTP 契约。"""
    from apps.dsn_study import asr_server
    import urllib.request

    handler = asr_server.ASRHandler
    old_model = handler.model
    handler.model = asr_server.ASRModel(device="cpu")
    handler.model._model = _StubModel("HTTP 识别")  # noqa: SLF001

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    httpd.daemon_threads = True
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        # /health
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as r:
            health = json.loads(r.read().decode("utf-8"))
        assert health["ready"] is True
        assert health["model"] == "paraformer-zh"

        # /asr（原始字节）
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/asr", data=_wav_bytes(),
            headers={"Content-Type": "application/octet-stream"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            out = json.loads(r.read().decode("utf-8"))
        assert out["text"] == "HTTP 识别"
        assert out["segments"] == [[0, 100]]
        assert out["elapsed"] >= 0

        # /asr（base64 JSON）
        body = json.dumps({"audio_b64": base64.b64encode(_wav_bytes()).decode()}).encode()
        req2 = urllib.request.Request(
            f"http://127.0.0.1:{port}/asr", data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req2, timeout=10) as r:
            out2 = json.loads(r.read().decode("utf-8"))
        assert out2["text"] == "HTTP 识别"
    finally:
        httpd.shutdown()
        httpd.server_close()
        handler.model = old_model


def test_asr_server_missing_audio_returns_400():
    from apps.dsn_study import asr_server
    import urllib.error
    import urllib.request

    handler = asr_server.ASRHandler
    old_model = handler.model
    handler.model = asr_server.ASRModel(device="cpu")

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    httpd.daemon_threads = True
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(
                urllib.request.Request(f"http://127.0.0.1:{port}/asr", data=b"",
                                       method="POST"), timeout=5)
        assert ei.value.code == 400
        payload = json.loads(ei.value.read().decode("utf-8"))
        assert payload["error"]
    finally:
        httpd.shutdown()
        httpd.server_close()
        handler.model = old_model


# ── 6. 配置 ──

def test_asr_config_keys_present():
    from apps.dsn_study.config import Config
    for key in ("ASR_ENABLED", "ASR_AUTOSTART", "ASR_LAUNCH_MODE", "ASR_CONDA_ENV",
                "ASR_CONDA_EXE", "ASR_SERVER_DIR", "ASR_SERVER_ENTRY", "ASR_PORT",
                "ASR_BASE_URL", "ASR_LOAD_TIMEOUT", "ASR_WARMUP", "ASR_REQUEST_TIMEOUT",
                "ASR_BATCH_SIZE_SECONDS", "ASR_CONVERT_TIMEOUT", "ASR_DEVICE",
                "ASR_GPU_ID"):
        assert hasattr(Config, key), "缺少配置项: %s" % key

    assert os.path.isfile(os.path.join(Config.ASR_SERVER_DIR, Config.ASR_SERVER_ENTRY)), \
        "ASR 入口脚本不存在: %s" % os.path.join(Config.ASR_SERVER_DIR, Config.ASR_SERVER_ENTRY)
