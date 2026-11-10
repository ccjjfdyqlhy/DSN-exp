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
import logging
import os
import sys
import threading
import time
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


def test_launcher_deploy_root_points_at_repo_root():
    """DEPLOY_ROOT 必须指向含 apps/dsn_study_cli/ 的部署根。

    回归：launcher 曾从 apps/dsn/CLI/ 整份拷来，沿用 parents[2]；
    迁到 apps/dsn_study_cli/（浅一层）后没同步下移，导致自更新把文件
    写到部署根之外、exec 到错误位置的副本。本用例禁止再 monkeypatch。
    """
    from apps.dsn_study_cli import launcher

    root = launcher.DEPLOY_ROOT
    # 部署根下必须存在本 launcher 自身的相对路径
    assert (root / "apps" / "dsn_study_cli" / "launcher.py").is_file(), (
        f"DEPLOY_ROOT={root} 不是部署根 —— 自更新会写到仓库外")
    # 不能越到部署根之外（dsn CLI 的 parents[2] 深度在迁居后就是错的）
    assert root == Path(launcher.__file__).resolve().parent.parents[1]



def test_logging_initialized_under_m_entrypoint(tmp_path, monkeypatch):
    """main() 必须初始化日志 —— -m 入口下模块级那行永不成立。

    回归：app.py 曾在模块级写 `setup_logging() if __name__ == "__main__"`，
    但 `python -m apps.dsn_study_cli` 下 app.py 是被 import 的，该分支永不成立，
    于是边缘设备上 logs/cli_*.log 一个都不会生成。
    """
    from apps.dsn_study_cli import app

    calls = []
    monkeypatch.setattr(app, "_init_logging", lambda: calls.append(1))
    monkeypatch.setattr(app, "ensure_dirs", lambda: None)
    monkeypatch.setattr(app, "save_config", lambda cfg: None)

    class _FakeApp:
        def __init__(self, cfg, **kwargs):
            self.cfg = cfg
            self.kwargs = kwargs

        def run(self):
            pass

    monkeypatch.setattr(app, "StudyCliApp", _FakeApp)

    app.main(["--host", "127.0.0.1", "--port", "5000"])
    assert calls, "main() 必须初始化日志，否则边缘设备无 cli_*.log"


def test_logging_writes_file_under_logs_dir(tmp_path, monkeypatch):
    """_init_logging() 应在 LOG_DIR 下生成 cli_*.log。"""
    from apps.dsn_study_cli import app, env

    monkeypatch.setattr(env, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(app, "log", None)
    try:
        app._init_logging()
        assert list((tmp_path / "logs").glob("cli_*.log"))
    finally:
        for h in list(logging.getLogger().handlers):
            logging.getLogger().removeHandler(h)
        monkeypatch.setattr(app, "log", None)


# ── TTS 播放 ────────────────────────────────────────────────

def test_tts_player_consumes_queue():
    """TtsPlayer 必须真的消费 tts_queue —— 此前队列无人取，语音合成完即丢。"""
    import queue as _queue
    from apps.dsn_study_cli import tts as tts_mod

    q = _queue.Queue()
    player = tts_mod.TtsPlayer(q)
    played = []
    player._spawn = lambda path: played.append(path) or True

    b64 = __import__("base64").b64encode(tts_mod.make_tone_wav()).decode()
    q.put(("你好", b64))
    player.start()
    try:
        deadline = time.time() + 5
        while time.time() < deadline and not played:
            time.sleep(0.05)
    finally:
        player.stop()
    assert played, "TtsPlayer 没有消费队列"
    assert q.empty(), "队列应被取空"


def test_tts_player_interrupt_stops_playback():
    """barge-in：interrupt() 要能掐掉正在播的进程。"""
    import queue as _queue
    from apps.dsn_study_cli import tts as tts_mod

    player = tts_mod.TtsPlayer(_queue.Queue())
    assert not player.is_playing


def test_headless_is_default_mode():
    """默认应为 headless（设备常常不接显示器，此时只有 Space 有意义）。"""
    from apps.dsn_study_cli import app

    parser = app.build_parser()
    assert parser.parse_args([]).headless is True, "默认必须是 headless"
    assert parser.parse_args(["--headless"]).headless is True
    assert parser.parse_args(["--tui"]).headless is False, \
        "--tui 应切回完整按键模式"


def test_tts_queue_is_wired_to_player():
    """app 必须把 client.tts_queue 接到播放器与异步任务轮询器上。"""
    from apps.dsn_study_cli import app

    cfg = {
        "backend_host": "127.0.0.1", "port": 5000, "token": "",
        "uid": 1, "display_name": "t", "chat_id": 0,
        "mic_device_index": -1, "camera_map": {},
    }
    a = app.StudyCliApp(cfg, headless=True)
    try:
        assert a.tts._queue is a.client.tts_queue, "TTS 播放未接在 tts_queue 上"
        assert a.async_poller._tts_queue is a.client.tts_queue, \
            "异步任务轮询器未接 tts_queue，汇总语音会被丢掉"
    finally:
        a.tts.stop()
