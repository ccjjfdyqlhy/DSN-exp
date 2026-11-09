# tests/test_dsn_study_vision_perception.py
# dsn_study 视觉感知服务端（迁移计划阶段 5）验收。
#
# 覆盖:
#   - VisionCoordinator 请求生命周期（创建/回传/唤醒/超时/GC）
#   - 摄像头台账持久化（dsn 缺陷 3：重启不丢）
#   - 7 组 /api/vision/* 路由（请求/响应形状与 dsn 对齐）
#   - 心跳下行注入（vision_request / active_vision / streams / sensing）
#   - visual_perception 技能（look_around / set_camera_note / list_cameras，
#     去重缓存按 (uid, camera, focus) 键控 —— dsn 缺陷 2 修复）
#   - 附件通道 + 「看到 → 录入」落盘桥
#   - OCRModel（infra 上提版）
#
# 全部打桩：不联网、不需要真实视觉后端。

import base64
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

# 1x1 PNG data URL（避免真实图片依赖）
PNG_DATA_URL = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
                "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


@pytest.fixture(scope="module")
def study_app(tmp_path_factory):
    db = tmp_path_factory.mktemp("vision_study") / "qb.db"
    os.environ["QUESTION_BANK_DB_PATH"] = str(db)
    os.environ["LOG_DIR"] = str(tmp_path_factory.mktemp("vision_logs"))
    os.environ["TTS_AUTOSTART"] = "false"
    os.environ["TTS_WARMUP"] = "false"
    os.environ["ASR_WARMUP"] = "false"
    os.environ["MCP_ENABLED"] = "false"
    os.environ["VISION_WARMUP"] = "false"
    os.environ["ACTIVE_VISION_ENABLED"] = "false"
    from apps.dsn_study import boot
    # 视觉模块的单例守护（coordinator/stream_hub 非空即复用）会跨测试模块
    # 带旧 db 连接 —— 重置后由本次 create_application 重建。
    from apps.dsn_study.api import vision as _vision_mod
    _vision_mod.coordinator = None
    _vision_mod.stream_hub = None
    boot.create_application()
    return boot.app


@pytest.fixture()
def client(study_app):
    return study_app.test_client()


@pytest.fixture()
def coord(study_app):
    from apps.dsn_study.api import vision as vision_mod
    return vision_mod.coordinator


# ── VisionCoordinator 请求生命周期 ──

def test_coordinator_request_lifecycle(coord):
    rid = coord.create_request(uid=1, camera="cam0")
    assert rid.startswith("vision_req_")
    # heartbeat 侧能看到待响应请求
    vr = coord.pending_for_uid(1)
    assert vr and vr["request_id"] == rid and vr["camera"] == "cam0"
    assert vr["timeout"] == int(coord.REQUEST_TIMEOUT)
    # 回传帧 → wait 唤醒
    assert coord.submit_frame(rid, {"cam0": PNG_DATA_URL}) is True
    frames, error = coord.wait_with_error(rid, timeout=2)
    assert error == "" and frames == {"cam0": PNG_DATA_URL}
    # 请求已消费，不再下发
    assert coord.pending_for_uid(1) is None
    # 重复提交同一请求 → False
    assert coord.submit_frame(rid, {"cam0": PNG_DATA_URL}) is False


def test_coordinator_timeout_returns_error(coord):
    rid = coord.create_request(uid=1, camera="cam0")
    coord.REQUEST_TIMEOUT = 0.2
    try:
        frames, error = coord.wait_with_error(rid, timeout=0.3)
        assert frames is None
        assert "未在超时内响应" in error or "请求不存在" in error
    finally:
        coord.REQUEST_TIMEOUT = 8.0


def test_coordinator_gc_no_zombie_lingering(coord, monkeypatch):
    """dsn 缺陷 1 修复：废弃请求的滞留时间必须与等待超时同量级（≤ timeout+10s）。"""
    rid = coord.create_request(uid=1)
    # 直接把 created_at 拨回 30s 前（远超 8s 超时 + 10s 缓冲）
    with coord._lock:
        coord._pending[rid]["created_at"] = time.time() - 30
        coord._gc()
    assert rid not in coord._pending
    assert coord.pending_count() == 0


def test_coordinator_submit_error_path(coord):
    """客户端抓帧失败（error 非空）→ wait 返回错误信息。"""
    rid = coord.create_request(uid=1)
    assert coord.submit_frame(rid, {}, error="无摄像头") is True
    frames, error = coord.wait_with_error(rid, timeout=1)
    assert frames is None and "无摄像头" in error


# ── 摄像头台账（dsn 缺陷 3 修复：持久化） ──

def test_camera_registry_and_note_persistence(study_app, coord, tmp_path):
    cameras = [{"logical_name": "cam0", "index": 0, "name": "cam0"},
               {"logical_name": "cam1", "index": 2, "name": "cam1"}]
    assert coord.register_cameras(cameras) is None  # 幂等无返回
    listing = coord.list_cameras()
    names = {c["logical_name"] for c in listing}
    assert {"cam0", "cam1"} <= names
    assert all(c["kind"] == "local" for c in listing)

    # 写备注 → 重建协调器（模拟重启）→ 备注仍在
    # 注意：Config 在首次导入时快照环境变量，db 真实路径以 app 装配的
    # db_mgr 为准（读 os.environ 会拿到被后续模块覆盖的假路径）。
    assert coord.set_camera_note("cam1", "文档摄像头") is True
    from apps.dsn_study.api import vision as vision_mod
    real_db = study_app.config["ENGINE"].db_mgr
    fresh = vision_mod.VisionCoordinator(db=real_db)
    assert fresh.get_camera_note("cam1") == "文档摄像头"
    assert any(c["logical_name"] == "cam1" and c["note"] == "文档摄像头"
               for c in fresh.list_cameras())


# ── 路由（形状与 dsn 对齐） ──

def test_routes_cameras_register_and_list(client, coord):
    rv = client.post("/api/vision/cameras", json={
        "cameras": [{"logical_name": "cam0", "index": 0, "name": "cam0",
                     "backend": "V4L2"}]})
    assert rv.status_code == 200
    assert rv.get_json() == {"success": True, "count": 1}

    rv = client.get("/api/vision/cameras")
    body = rv.get_json()
    assert body["success"] is True
    assert any(c["logical_name"] == "cam0" for c in body["cameras"])


def test_routes_note(client, coord):
    rv = client.post("/api/vision/note", json={"logical_name": "cam0",
                                               "note": "书桌正面"})
    assert rv.get_json() == {"success": True}
    rv = client.post("/api/vision/note", json={"note": "缺 logical_name"})
    assert rv.status_code == 400


def test_routes_frame_new_and_legacy_format(client, coord):
    # 新格式：frames 数组
    rid = coord.create_request(uid=1)
    rv = client.post("/api/vision/frame", json={
        "request_id": rid,
        "frames": [{"logical_name": "cam0", "image_data": PNG_DATA_URL}]})
    assert rv.get_json() == {"success": True}
    frames = coord.wait(rid, timeout=1)
    assert frames == {"cam0": PNG_DATA_URL}

    # 旧格式：image_data 单字段
    rid2 = coord.create_request(uid=1)
    rv = client.post("/api/vision/frame", json={
        "request_id": rid2, "image_data": PNG_DATA_URL})
    assert rv.get_json() == {"success": True}
    assert coord.wait(rid2, timeout=1) == {"default": PNG_DATA_URL}

    # 缺 request_id → 400
    rv = client.post("/api/vision/frame", json={"image_data": PNG_DATA_URL})
    assert rv.status_code == 400


def test_routes_frame_explicit_empty_means_no_camera(client, coord):
    """显式空 frames 数组 = 客户端无摄像头，提交为错误而非 400。"""
    rid = coord.create_request(uid=1)
    rv = client.post("/api/vision/frame", json={"request_id": rid, "frames": []})
    assert rv.get_json() == {"success": True}
    frames, error = coord.wait_with_error(rid, timeout=1)
    assert frames is None and "未抓到帧" in error


def test_routes_stream_frame_and_hub(client):
    from apps.dsn_study.api import vision as vision_mod
    hub = vision_mod.stream_hub
    rv = client.post("/api/vision/stream-frame", json={
        "frames": [{"logical_name": "cam0", "image_data": PNG_DATA_URL}]})
    body = rv.get_json()
    assert body["success"] is True and body["accepted"] == 1
    latest = hub.latest_frame("cam0")
    assert latest and latest["image_data"] == PNG_DATA_URL
    # 非数组 → 400
    rv = client.post("/api/vision/stream-frame", json={"frames": "oops"})
    assert rv.status_code == 400


def test_routes_observation_saves_file(client, tmp_path):
    rv = client.post("/api/vision/observation", json={
        "image_data": PNG_DATA_URL, "camera": "cam0", "timestamp": "t1"})
    body = rv.get_json()
    assert body["success"] is True and body["saved"] is True
    assert body["path"] and Path(body["path"]).is_file()
    assert Path(body["path"]).read_bytes()[:4] == b"\x89PNG"

    rv = client.post("/api/vision/observation", json={})
    assert rv.status_code == 400 and rv.get_json()["error"] == "缺少 image_data"


def test_routes_webcams_shape_aligned(client):
    """study 无 WebCamManager：保持 dsn 的 503 响应形状。"""
    rv = client.get("/api/vision/webcams")
    assert rv.status_code == 503
    assert "error" in rv.get_json()
    rv = client.post("/api/vision/webcams/test", json={"url": "http://x"})
    assert rv.status_code == 503


# ── 心跳下行注入（阶段 5.3） ──

def test_heartbeat_injects_vision_fields(client, coord):
    rid = coord.create_request(uid=1)
    try:
        rv = client.get("/api/heartbeat")
        body = rv.get_json()
    finally:
        with coord._lock:
            coord._pending.pop(rid, None)
    # vision_request 下发（这是「AI 主动说看一下」的唯一通道）
    assert body.get("vision_request", {}).get("request_id") == rid
    assert body["vision_request"]["camera"] == ""
    # 其余三块恒存在（形状与 dsn 对齐）
    assert body["active_vision"] == {"enabled": False, "interval": 300, "camera": ""}
    assert set(body["streams"].keys()) == {"enabled", "interval"}
    assert body["sensing"]["enabled"] is False
    assert body["tracking"]["enabled"] is False


def test_heartbeat_without_pending_request_has_no_vision_request(client, coord):
    rv = client.get("/api/heartbeat")
    body = rv.get_json()
    assert "vision_request" not in body
    assert "active_vision" in body and "streams" in body


# ── visual_perception 技能（阶段 5.4） ──

def test_visual_perception_skill_registered(study_app):
    engine = study_app.config["ENGINE"]
    tools = engine.skill_registry.list_active_tools()
    for t in ("visual_perception.look_around",
              "visual_perception.set_camera_note",
              "visual_perception.list_cameras"):
        assert t in tools, f"缺少视觉工具: {t}"
    # 护栏：三个工具都必须可派发（阶段 0 的教训）
    assert not engine.skill_registry.undispatchable_tools()


def test_look_around_flow_with_stub_models(study_app):
    """端到端（桩）：look_around → 协调器 pending → 模拟 CLI 经心跳取请求回帧
    → VLM 描述。"""
    import threading
    from apps.dsn_study.api import vision as vision_mod

    class _StubLLM:
        def describe_image(self, image, prompt):
            assert image == PNG_DATA_URL
            assert "卷子" in prompt   # focus 注入了 prompt
            return "一张数学卷子"

    engine = study_app.config["ENGINE"]
    tool = next(i for i in
                engine.skill_registry.get_tool_instances("visual_perception")
                if hasattr(i, "look_around"))
    tool._models = _StubLLM()
    tool._coordinator = vision_mod.coordinator
    tool._look_cache.clear()
    coord = vision_mod.coordinator

    # 模拟边缘客户端：轮询心跳语义（pending_for_uid）→ POST /api/vision/frame
    def _responder():
        for _ in range(100):
            vr = coord.pending_for_uid(1)
            if vr:
                coord.submit_frame(vr["request_id"],
                                   {"cam0": PNG_DATA_URL})
                return
            time.sleep(0.05)

    t = threading.Thread(target=_responder, daemon=True)
    t.start()
    result = tool.look_around(camera="", focus="桌上的卷子")
    t.join(timeout=2)
    assert result["success"] is True, result
    assert result["observations"][0]["description"] == "一张数学卷子"

    # 去重：窗口内同参数直接复用（带 cached 标记）
    again = tool.look_around(camera="", focus="桌上的卷子")
    assert again.get("cached") is True

    # 不同 focus 不共用缓存
    fresh = tool.look_around(camera="", focus="黑板")
    assert fresh.get("cached") is None or fresh.get("cached") is not True


def test_look_around_per_uid_isolation(study_app):
    """dsn 缺陷 2 修复：不同 uid 不共享去重缓存。"""
    from apps.dsn_study.api import vision as vision_mod
    engine = study_app.config["ENGINE"]
    tool = next(i for i in
                engine.skill_registry.get_tool_instances("visual_perception")
                if hasattr(i, "look_around"))
    orig_uid, orig_coord = tool._uid, tool._coordinator
    try:
        tool._look_cache.clear()
        tool._look_cache[(1, "", "f")] = (time.time(), {"success": True})
        # uid=2 同参数不命中
        tool._uid = 2
        tool._coordinator = None   # 未就绪 → 明确报错而不是返回 uid1 的缓存
        out = tool.look_around(camera="", focus="f")
        assert out["success"] is False
    finally:
        tool._uid, tool._coordinator = orig_uid, orig_coord
        tool._look_cache.clear()


def test_set_camera_note_via_tool(study_app, coord):
    engine = study_app.config["ENGINE"]
    tool = next(i for i in
                engine.skill_registry.get_tool_instances("visual_perception")
                if hasattr(i, "set_camera_note"))
    out = tool.set_camera_note("cam0", "书桌正面")
    assert out["success"] is True
    assert coord.get_camera_note("cam0") == "书桌正面"


# ── 附件通道 + 「看到 → 录入」桥（阶段 5.6/5.7） ──

def test_attachments_bridge_saves_and_injects_path(study_app, tmp_path):
    from harness.pipeline.base import Attachment, Context, HookPoint
    from apps.dsn_study.pipeline.plugins import VisionContextPlugin

    class _StubLLM:
        def describe_image(self, image, prompt):
            return "测试图描述"

    workspace = study_app.config["ENGINE"].workspace
    plugin = VisionContextPlugin(llm=_StubLLM(), workspace=workspace)

    ctx = Context(user_id=1, message="看看这张")
    ctx.attachments.append(Attachment(kind="image", data=PNG_DATA_URL,
                                      mime="image/png", name="t.png"))
    out = plugin.on_hook(HookPoint.PRE_PROCESS, ctx)
    assert "测试图描述" in out.message
    paths = out.extra.get("vision_image_paths")
    assert paths and len(paths) == 1
    p = Path(paths[0])
    assert p.is_file() and p.read_bytes()[:4] == b"\x89PNG"
    assert "vision" in str(p.parent)
    # 上下文里给出录入指引（AI 可拿路径调 import_photo_questions）
    assert "import_photo_questions" in out.message


def test_attachments_takes_priority_over_image_data(study_app):
    from harness.pipeline.base import Attachment, Context, HookPoint
    from apps.dsn_study.pipeline.plugins import VisionContextPlugin

    seen = []

    class _StubLLM:
        def describe_image(self, image, prompt):
            seen.append(image)
            return "d"

    plugin = VisionContextPlugin(llm=_StubLLM())
    ctx = Context(user_id=1, message="x",
                  image_data="data:image/png;base64,OLD")
    ctx.attachments.append(Attachment(kind="image",
                                      data="data:image/png;base64,NEW"))
    plugin.on_hook(HookPoint.PRE_PROCESS, ctx)
    # attachments 优先于 image_data
    assert seen == ["data:image/png;base64,NEW"]


def test_engine_chat_builds_attachment(study_app):
    """StudyEngine.chat(image=...) 应把图片放进 ctx.attachments（管线入参）。"""
    from apps.dsn_study import boot
    engine = boot.engine
    captured = {}

    orig_run = engine.pipeline_runner.run

    def _capture(ctx):
        captured["attachments"] = list(ctx.attachments)
        captured["image_data"] = ctx.image_data
        ctx.reply = "ok"
        return ctx

    engine.pipeline_runner.run = _capture
    try:
        reply = engine.chat("看", user_id=1, session_id="att-test",
                            image=PNG_DATA_URL)
    finally:
        engine.pipeline_runner.run = orig_run
    assert reply == "ok"
    assert len(captured["attachments"]) == 1
    assert captured["attachments"][0].kind == "image"
    assert captured["image_data"] == PNG_DATA_URL   # 兼容来源保留


# ── OCRModel（阶段 5.5 上提） ──

def test_infra_ocr_model_batch_with_stub_session():
    from infra.orchestrator.vision import OCRModel

    class _StubResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "# 题目\n1+1=?"}}]}

    class _StubSession:
        def post(self, url, headers=None, json=None, timeout=None):
            return _StubResp()

    ocr = OCRModel(base_url="http://stub", model_name="deepseek-ocr",
                   auto_load=False, unload_after_use=False)
    ocr._http_session = _StubSession()
    results = ocr.ocr_batch([{"filename": "a.png", "data_url": PNG_DATA_URL}])
    assert results == [{"filename": "a.png", "markdown": "# 题目\n1+1=?"}]
    single = ocr.ocr(PNG_DATA_URL)
    assert "1+1" in single


def test_study_ocr_model_reads_config(study_app):
    from apps.dsn_study.models.clients import OCRModel
    from apps.dsn_study.config import Config
    ocr = OCRModel(auto_load=False)
    assert ocr.base_url == Config.OCR_BASE_URL.rstrip("/")
    assert ocr.model_name == Config.OCR_MODEL
    assert ocr.unload_after_use == bool(getattr(Config, "OCR_UNLOAD_AFTER_USE", True))
