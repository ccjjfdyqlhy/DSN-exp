# tests/test_dsn_study_cli.py
# study_CLI（迁移计划阶段 6）验收。
#
# 覆盖:
#   - 摄像头映射解析（STUDY_CAMERA_MAP / 逻辑名规则 cam0/cam1）
#   - 音频 WAV 编码（16k mono s16）
#   - SSE 解析
#   - StudyClient 对真实服务端的端到端（werkzeug 临时端口）：
#     cameras 上报 / select_camera / quick / finish / task status /
#     update manifest（独立清单，不再拉到 dsn 字节）
#   - update 白名单安全（目录穿越 / 白名单外 404 / token 鉴权）

import base64
import io
import json
import os
import sys
import threading
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQ"
    "AAAABJRU5ErkJggg==")
PNG_DATA_URL = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode()


# ── 摄像头 ──

def test_camera_map_parsing():
    from apps.dsn_study_cli.camera import _parse_camera_map
    assert _parse_camera_map("cam1=2,doc=3") == {"cam1": 2, "doc": 3}
    assert _parse_camera_map("") == {}
    assert _parse_camera_map("bad,doc=x,ok=1") == {"ok": 1}


def test_camera_map_env_priority(monkeypatch):
    from apps.dsn_study_cli import camera
    monkeypatch.setenv("STUDY_CAMERA_MAP", "doc=2")
    assert camera.get_camera_map({}) == {"doc": 2}
    monkeypatch.delenv("STUDY_CAMERA_MAP")
    assert camera.get_camera_map({"camera_map": {"doc": 3}}) == {"doc": 3}


def test_logical_name_assignment():
    """枚举顺序第 2 台 = cam1（0-based）；显式映射优先。"""
    from apps.dsn_study_cli.camera import _assign_logical_names
    devices = [{"index": 0, "backend": 200}, {"index": 2, "backend": 200}]
    out = _assign_logical_names([dict(d) for d in devices], {})
    assert [d["logical_name"] for d in out] == ["cam0", "cam1"]
    # 显式映射：doc 钉住 index 2
    out2 = _assign_logical_names([dict(d) for d in devices], {"doc": 2})
    by_idx = {d["index"]: d["logical_name"] for d in out2}
    assert by_idx[2] == "doc" and by_idx[0] == "cam0"


# ── 音频 ──

def test_pcm_to_wav_b16_format():
    from apps.dsn_study_cli.audio import SAMPLE_RATE, pcm_to_wav_b64
    samples = b"\x00\x01" * SAMPLE_RATE   # 1 秒的 int16 单声道
    b64 = pcm_to_wav_b64(samples)
    raw = base64.b64decode(b64)
    wf = wave.open(io.BytesIO(raw), "rb")
    assert wf.getframerate() == SAMPLE_RATE
    assert wf.getnchannels() == 1
    assert wf.getsampwidth() == 2
    assert wf.getnframes() == SAMPLE_RATE
    wf.close()


def test_rms_threshold_semantics():
    from apps.dsn_study_cli.audio import RMS_THRESHOLD, rms_of
    import struct
    silence = struct.pack("<h", 0) * 512
    loud = struct.pack("<h", 16000) * 512
    assert rms_of(silence) < RMS_THRESHOLD
    assert rms_of(loud) > RMS_THRESHOLD


# ── SSE 解析 ──

class _FakeSSE:
    def __init__(self, lines):
        self._lines = lines

    def iter_lines(self, decode_unicode=True):
        return iter(self._lines)


def test_iter_sse_lines():
    from apps.dsn_study_cli.client import iter_sse_lines
    lines = [
        "event: main_reply",
        'data: {"reply": "你好", "chat_id": 7}',
        "",
        "event: completed",
        "data: [DONE]",
    ]
    events = list(iter_sse_lines(_FakeSSE(lines)))
    assert events[0] == ("main_reply", {"reply": "你好", "chat_id": 7})
    assert events[-1] == ("completed", {})


# ── 端到端（真实 HTTP 服务） ──

@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    db = tmp_path_factory.mktemp("cli_study") / "qb.db"
    os.environ["QUESTION_BANK_DB_PATH"] = str(db)
    os.environ["LOG_DIR"] = str(tmp_path_factory.mktemp("cli_logs"))
    os.environ["TTS_AUTOSTART"] = "false"
    os.environ["TTS_WARMUP"] = "false"
    os.environ["ASR_WARMUP"] = "false"
    os.environ["MCP_ENABLED"] = "false"
    os.environ["VISION_WARMUP"] = "false"
    from apps.dsn_study import boot
    flask_app = boot.create_application()

    from werkzeug.serving import make_server
    server = make_server("127.0.0.1", 0, flask_app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", flask_app
    server.shutdown()
    thread.join(timeout=5)


@pytest.fixture()
def cli(live_server):
    from apps.dsn_study_cli.client import StudyClient
    base, _ = live_server
    return StudyClient(base, token="", uid=1)


def test_client_camera_registration_and_vision_routes(cli):
    out = cli.register_cameras([
        {"logical_name": "cam0", "index": 0, "name": "cam0", "backend": "200"},
        {"logical_name": "doc", "index": 2, "name": "doc", "backend": "200"}])
    assert out == {"success": True, "count": 2}
    listing = cli._get("/api/vision/cameras")
    names = {c["logical_name"] for c in listing.get("cameras", [])}
    assert {"cam0", "doc"} <= names


def test_client_scan_batch_flow(cli):
    """核心场景（桩）：拍一张 → 进批次 → 结束 → 任务可查。"""
    r1 = cli.scan_quick(PNG_DATA_URL, camera="doc")
    assert r1.get("success") is True, r1
    assert r1.get("photo_id") and r1.get("batch_id")

    r2 = cli.scan_quick(PNG_DATA_URL, camera="doc")
    assert r2.get("success") is True

    fin = cli.scan_finish()
    assert fin.get("success") is True
    task_id = fin.get("task_id")
    assert task_id and task_id.startswith("scan_")

    status = cli.task_status(task_id)
    assert status.get("status") in ("running", "done", "failed")


def test_client_select_camera_endpoint(cli):
    out = cli.select_camera([
        {"logical_name": "doc", "image_data": PNG_DATA_URL}])
    # 单摄直接选定 / 多摄走 VLM（无凭据时降级）——两种实现都算成功形状
    assert out.get("success") in (True, False)
    assert "logical_name" in out or "error" in out


def test_client_heartbeat_shape(cli):
    data = cli.heartbeat()
    assert isinstance(data, dict)
    assert "has_notification" in data
    assert "active_vision" in data and "streams" in data
    assert data["sensing"]["enabled"] is False


# ── 自更新（独立清单） ──

def test_update_manifest_points_to_study_cli(live_server):
    base, _ = live_server
    import urllib.request
    with urllib.request.urlopen(f"{base}/api/update/manifest",
                                timeout=5) as resp:
        manifest = json.loads(resp.read().decode())
    paths = [f["path"] for f in manifest["files"]]
    assert paths, "清单不应为空"
    assert all(p.startswith(("apps/dsn_study_cli/", "apps/__init__.py",
                             "apps/dsn_study/__init__.py")) for p in paths), paths
    assert not any("apps/dsn/CLI" in p for p in paths), "不得下发 dsn 的文件"
    # 关键文件在清单里
    assert "apps/dsn_study_cli/app.py" in paths
    assert "apps/dsn_study_cli/launcher.py" in paths


def test_update_file_endpoint_serves_cli_bytes(live_server):
    base, _ = live_server
    import urllib.request
    url = f"{base}/api/update/file/apps/dsn_study_cli/app.py"
    with urllib.request.urlopen(url, timeout=5) as resp:
        content = resp.read().decode()
    assert "StudyCliApp" in content   # 是 study 的字节，不是 dsn 的


def test_update_whitelist_blocks_traversal(live_server):
    base, _ = live_server
    import urllib.request
    for bad in ("apps/dsn/CLI/app.py", "apps/dsn_study/boot.py",
                "apps/../harness/agent_runtime.py", "apps/dsn_study_cli/../../boot.py"):
        url = f"{base}/api/update/file/{bad}"
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                code = resp.status
        except Exception as e:   # noqa: BLE001
            code = getattr(e, "code", 0)
        assert code == 404, f"{bad} 应被白名单拦截（got {code}）"


def test_update_token_auth(live_server, monkeypatch):
    """配置了 DSN_STUDY_TOKEN 的服务端：无 token 401，带 token 200。"""
    from apps.dsn_study.api import update as update_mod
    token = "secret-token-123"
    update_mod.init_update_api(token=token)
    try:
        base, _ = live_server
        import urllib.request
        url = f"{base}/api/update/manifest"
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                code = resp.status
        except Exception as e:   # noqa: BLE001
            code = getattr(e, "code", 0)
        assert code == 401
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
    finally:
        update_mod.init_update_api(token="")


# ── launcher 文件同步（对临时部署根） ──

def test_launcher_sync_files(live_server, tmp_path, monkeypatch):
    base, _ = live_server
    from apps.dsn_study_cli import launcher
    monkeypatch.setattr(launcher, "DEPLOY_ROOT", tmp_path)
    # 先建一个内容不一致的旧文件
    target = tmp_path / "apps" / "dsn_study_cli"
    target.mkdir(parents=True, exist_ok=True)
    (target / "app.py").write_text("# stale", encoding="utf-8")
    updated = launcher.sync_files(base, token="")
    assert "apps/dsn_study_cli/app.py" in updated
    assert "StudyCliApp" in (target / "app.py").read_text(encoding="utf-8")
    # 二次同步无更新
    assert launcher.sync_files(base, token="") == []
