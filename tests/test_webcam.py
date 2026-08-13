# tests/test_webcam.py
# 远程摄像头 (webcam) infra 测试：
#   WebCamManager CRUD/持久化/抓帧超时 + VisionCoordinator 路由/完成判定 + look_around 端到端

import io
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── fake cv2（注入 sys.modules，_work 线程内 import cv2 会拿到它）──

class _FakeFrame:
    """只有 shape 属性的假帧，避免测试环境依赖 numpy。"""
    shape = (8, 8, 3)


class _FakeCap:
    def __init__(self, url, opened=True, fail=False, block=0.0):
        self._url, self._opened, self._fail, self._block = url, opened, fail, block

    def isOpened(self):
        return self._opened

    def set(self, *a):
        return True

    def read(self):
        if self._block:
            time.sleep(self._block)          # 模拟 RTSP hang
        if self._fail:
            return (False, None)
        return (True, _FakeFrame())

    def release(self):
        pass


class _FakeCv:
    CAP_PROP_OPEN_TIMEOUT_MSEC = 1
    CAP_PROP_READ_TIMEOUT_MSEC = 2
    IMWRITE_JPEG_QUALITY = 90

    def __init__(self):
        self.calls = []
        self.fail_urls = set()
        self.hang_urls = set()

    def VideoCapture(self, url, *a):
        self.calls.append(url)
        return _FakeCap(
            url,
            opened=url not in self.fail_urls,
            fail=url in self.fail_urls,
            block=100.0 if url in self.hang_urls else 0.0,
        )

    def imencode(self, ext, frame, params=None):
        return (True, memoryview(b"JPEGDATA"))   # memoryview.tobytes() 可用


def _install_fake_cv() -> "_FakeCv":
    fake = _FakeCv()
    sys.modules["cv2"] = fake
    return fake


def _make_manager(path, **kw):
    from apps.dsn.tracking.webcam import WebCamManager
    return WebCamManager(path=str(path), **kw)


# ═══════════════════════════════════════
# WebCamManager
# ═══════════════════════════════════════

def test_manager_crud_persistence():
    print("=== WebCamManager CRUD + 持久化 ===")
    fake = _install_fake_cv()
    cfg = Path(tempfile.mkdtemp()) / "webcams.json"
    mgr = _make_manager(cfg)
    assert mgr.count() == 0

    r = mgr.add("rtsp://192.168.1.50:554/1", name="door", note="门口", test=True)
    assert r["ok"], r
    assert r["logical_name"] == "door"
    assert fake.calls[-1] == "rtsp://192.168.1.50:554/1"

    r2 = mgr.add("rtsp://192.168.1.51:554/1", test=True)
    assert r2["ok"] and r2["logical_name"] == "webcam0"

    assert mgr.count() == 2
    assert mgr.is_webcam("door")
    assert mgr.get("door").note == "门口"

    # 重新加载（持久化生效）
    mgr2 = _make_manager(cfg)
    assert mgr2.count() == 2
    assert mgr2.get("door").note == "门口"

    # 备注更新持久化
    assert mgr.set_note("door", "大门")["ok"]
    assert _make_manager(cfg).get("door").note == "大门"

    # 删除
    assert mgr.remove("door")["ok"]
    assert mgr.count() == 1
    assert _make_manager(cfg).count() == 1

    # 非法逻辑名 / 重复名 / 非法 URL
    assert not mgr.add("http://x/stream", name="bad name!", test=False)["ok"]
    assert not mgr.add("rtsp://y/1", name="webcam0", test=False)["ok"]
    assert not mgr.add("ftp://z/1", name="zz", test=False)["ok"]
    assert not mgr.add("", name="zz", test=False)["ok"]
    print("  PASSED")


def test_manager_test_failure_and_redact():
    print("=== 连通性失败 + URL 凭据打码 ===")
    fake = _install_fake_cv()
    fake.fail_urls.add("http://dead/stream")
    cfg = Path(tempfile.mkdtemp()) / "webcams.json"
    mgr = _make_manager(cfg)

    res = mgr.test("http://dead/stream")
    assert not res.get("ok"), res

    r = mgr.add("http://dead/stream", name="dead", test=True)
    assert not r["ok"], r
    assert "测试失败" in r.get("error", "")

    # 打码
    mgr.add("rtsp://user:pass@10.0.0.1:554/1", name="authcam", test=True)
    items = mgr.list()
    it = [c for c in items if c["logical_name"] == "authcam"][0]
    assert "user:pass@" not in it["redacted_url"]
    assert "user:***@" in it["redacted_url"]
    print("  PASSED")


def test_manager_frame_timeout():
    print("=== 抓帧超时保护（cv2 hang 不卡死）===")
    fake = _install_fake_cv()
    fake.hang_urls.add("http://hang/stream")
    cfg = Path(tempfile.mkdtemp()) / "webcams.json"
    mgr = _make_manager(cfg, frame_timeout=1)

    # 正常设备正常返回（独立实例，避免与后续 hang 测试共享 _grab_guard 锁）
    assert mgr.add("http://ok/stream", name="ok", test=True)["ok"]
    assert mgr.capture_frame("ok") is not None

    # hang 设备：join 超时后返回 None，不卡死调用方
    t0 = time.time()
    f = mgr._grab_from_url("http://hang/stream", timeout=1)
    dt = time.time() - t0
    assert f is None, "hang 设备应返回 None"
    assert dt < 4.0, f"超时保护失效: {dt:.1f}s"
    print("  PASSED")


# ═══════════════════════════════════════
# VisionCoordinator 路由
# ═══════════════════════════════════════

def _make_coord_with_webcams():
    from apps.dsn.api.vision import VisionCoordinator
    fake = _install_fake_cv()
    cfg = Path(tempfile.mkdtemp()) / "webcams.json"
    mgr = _make_manager(cfg)
    assert mgr.add("rtsp://10.0.0.2:554/1", name="camA", note="客厅", test=True)["ok"]
    assert mgr.add("rtsp://10.0.0.3:554/1", name="camB", test=True)["ok"]
    coord = VisionCoordinator()
    coord.register_webcam_manager(mgr)
    return coord, mgr


def test_coordinator_webcam_only():
    print("=== 纯 webcam 请求：后端直抓，不下发客户端 ===")
    coord, mgr = _make_coord_with_webcams()

    rid = coord.create_request(camera="camA")
    assert coord.pending_for_uid(0) is None, "纯 webcam 请求不应下发给 minimal.py"
    frames = coord.wait(rid, timeout=6)
    assert frames and "camA" in frames, frames

    # 单台
    rid2 = coord.create_request(camera="camB")
    assert coord.pending_for_uid(0) is None
    frames2 = coord.wait(rid2, timeout=6)
    assert frames2 and "camB" in frames2 and "camA" not in frames2

    # 列表合并 kind
    cams = coord.list_cameras()
    kinds = {c["logical_name"]: c["kind"] for c in cams}
    assert kinds.get("camA") == "webcam"
    assert kinds.get("camB") == "webcam"

    # 备注转发并持久化到 manager
    assert coord.set_camera_note("camA", "客厅监控")
    assert coord.list_cameras_note("camA") == "客厅监控"
    assert mgr.get("camA").note == "客厅监控"
    print("  PASSED")


def test_coordinator_webcam_all_mixed():
    print("=== camera=all：webcam 后端抓 + 本地客户端回传，双方就绪才完成 ===")
    coord, mgr = _make_coord_with_webcams()

    rid = coord.create_request(camera="all")
    # 混合请求仍需下发给本地客户端（物理摄像头部分）
    pending = coord.pending_for_uid(0)
    assert pending and pending["camera"] == "all"

    # 本地部分回传（模拟 minimal.py）
    assert coord.submit_frame(pending["request_id"], {"cam0": "local-frame"})
    frames = coord.wait(pending["request_id"], timeout=6)
    assert "cam0" in frames, frames            # 本地帧
    assert "camA" in frames and "camB" in frames, frames  # webcam 帧也应在 wait 返回时到齐

    # 本地失败（无摄像头）也能完成，且只拿得到 webcam 帧
    rid2 = coord.create_request(camera="all")
    p2 = coord.pending_for_uid(0)
    assert coord.submit_frame(p2["request_id"], {}, error="本地无摄像头")
    frames2 = coord.wait(rid2, timeout=6)
    assert "camA" in frames2 and "camB" in frames2, frames2
    assert "cam0" not in frames2
    print("  PASSED")


def test_look_around_webcam_end_to_end():
    print("=== look_around 端到端：AI 像调物理摄像头一样调 webcam ===")
    from apps.dsn.skills.builtin.visual_perception.tools.perception import VisualPerceptionTool
    coord, mgr = _make_coord_with_webcams()

    class _FakeVM:
        def ask(self, data_url, prompt, max_tokens, temperature):
            return "看到远程摄像头画面，无人"

    VisualPerceptionTool._ctx = {"coordinator": coord, "vision_model": _FakeVM()}
    tool = VisualPerceptionTool()

    r = tool.look_around(camera="camA")
    assert r["success"], r
    assert r["camera"] == "camA"
    assert r["cameras"] and r["cameras"][0]["logical_name"] == "camA"
    assert "远程摄像头画面" in r["description"]

    # set_camera_note 工具
    assert tool.set_camera_note("camB", "后门")["success"]
    assert mgr.get("camB").note == "后门"
    print("  PASSED")


if __name__ == "__main__":
    test_manager_crud_persistence()
    test_manager_test_failure_and_redact()
    test_manager_frame_timeout()
    test_coordinator_webcam_only()
    test_coordinator_webcam_all_mixed()
    test_look_around_webcam_end_to_end()
    print("\nALL WEBCAM TESTS PASSED")
