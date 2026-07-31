# tests/test_multi_camera.py
# 多摄像头系统测试 — 客户端枚举/解析 + 后端协调器多帧 + 备注

import os
import sys
import threading
import time
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psychoscope.minimal as m
from api.vision import VisionCoordinator


class _FakeCap:
    def __init__(self, idx, opened=None):
        self._idx = idx
        self._opened = idx in (0, 2) if opened is None else opened

    def isOpened(self):
        return self._opened

    def release(self):
        pass


class _FakeCv:
    def __init__(self, open_indices=(0, 2)):
        self._open = set(open_indices)

    def VideoCapture(self, idx, backend=0):
        return _FakeCap(idx, idx in self._open)


def test_enumerate_with_env_map():
    print("=== 客户端枚举 + env 映射 ===")
    m._CAMERA_SCAN_DONE = False
    m.HAS_CAMERA = True
    orig = m.cv2
    m.cv2 = _FakeCv()
    try:
        os.environ["DSN_CAMERA_MAP"] = "front=0,usb=2"
        cams = m._enumerate_cameras()
        assert [c["logical_name"] for c in cams] == ["front", "usb"], cams
        assert m._resolve_camera("front") == 0
        assert m._resolve_camera("usb") == 2
        assert m._resolve_camera("") == m.CAMERA_DEVICE_ID
    finally:
        os.environ.pop("DSN_CAMERA_MAP", None)
        m.cv2 = orig
        m._CAMERA_SCAN_DONE = False
    print("  PASSED")


def test_enumerate_auto_names():
    print("=== 客户端自动命名 ===")
    m._CAMERA_SCAN_DONE = False
    m.HAS_CAMERA = True
    orig = m.cv2
    m.cv2 = _FakeCv()
    try:
        os.environ.pop("DSN_CAMERA_MAP", None)
        cams = m._enumerate_cameras()
        assert [c["logical_name"] for c in cams] == ["cam0", "cam1"], cams
    finally:
        m.cv2 = orig
        m._CAMERA_SCAN_DONE = False
    print("  PASSED")


def test_coordinator_multi_frame():
    print("=== 协调器多帧 + 单帧 + 备注 ===")
    coord = VisionCoordinator()
    coord.register_cameras([
        {"logical_name": "cam0", "index": 0},
        {"logical_name": "cam1", "index": 2},
    ])
    assert len(coord.list_cameras()) == 2
    coord.set_camera_note("cam0", "桌面主摄像头")
    assert coord.list_cameras_note("cam0") == "桌面主摄像头"

    # 多摄像头请求
    holder = {}
    def _req():
        rid = coord.create_request(focus="user", uid=0, camera="all")
        holder["frames"] = coord.wait(rid)
    t = threading.Thread(target=_req)
    t.start()
    time.sleep(0.05)
    pending = coord.pending_for_uid(0)
    assert pending and pending["camera"] == "all"
    coord.submit_frame(pending["request_id"], {"cam0": "f0", "cam1": "f1"})
    t.join(timeout=2)
    assert holder["frames"] == {"cam0": "f0", "cam1": "f1"}

    # 单摄像头请求
    rid2 = coord.create_request(camera="cam1")
    p2 = coord.pending_for_uid(0)
    assert p2["camera"] == "cam1"
    coord.submit_frame(rid2, {"cam1": "frame1"})
    assert coord.wait(rid2) == {"cam1": "frame1"}
    print("  PASSED")


def test_frame_submit_formats():
    print("=== 多帧 submit_frame 格式 ===")
    coord = VisionCoordinator()
    rid = coord.create_request(camera="all")
    frames_in = {"cam0": "f0", "cam1": "f1"}
    coord.submit_frame(rid, frames_in)
    assert coord.wait(rid) == frames_in

    # 单帧（旧行为兼容）
    rid2 = coord.create_request(camera="")
    coord.submit_frame(rid2, {"default": "single"})
    assert coord.wait(rid2) == {"default": "single"}
    print("  PASSED")


def test_look_around_multi_camera():
    print("=== look_around 多摄像头端到端 ===")
    from skills.builtin.visual_perception.tools.perception import VisualPerceptionTool

    class _FakeCoord:
        def __init__(self):
            self._notes = {}
            self.called_camera = ""

        def create_request(self, focus="", uid=0, camera=""):
            self.called_camera = camera
            return "req_1"

        def wait(self, rid):
            return {"cam0": "f0", "cam1": "f1"} if self.called_camera == "all" \
                else {self.called_camera: "f"}

        def list_cameras_note(self, name):
            return self._notes.get(name, "")

        def set_camera_note(self, name, note):
            self._notes[name] = note
            return True

        def list_cameras(self):
            return [{"logical_name": k, "note": v} for k, v in self._notes.items()]

    class _FakeVM:
        def ask(self, data_url, prompt, max_tokens, temperature):
            return "看到一个用户在打字"

    fc = _FakeCoord()
    VisualPerceptionTool._ctx = {"coordinator": fc, "vision_model": _FakeVM()}
    tool = VisualPerceptionTool()

    # 首次：全摄像头
    r = tool.look_around(focus="user")
    assert fc.called_camera == "all"
    assert len(r["cameras"]) == 2
    assert "cam0" in r["visual_prompt"]
    assert "cam1" in r["visual_prompt"]

    # 单独调用某台
    r2 = tool.look_around(camera="cam1")
    assert fc.called_camera == "cam1"
    assert len(r2["cameras"]) == 1
    assert r2["description"] == r2["cameras"][0]["description"]

    # 写备注 + 列摄像头
    assert tool.set_camera_note("cam1", "门口摄像头")["success"]
    assert fc._notes["cam1"] == "门口摄像头"
    assert len(tool.list_cameras()["cameras"]) == 1
    print("  PASSED")


def test_enumerate_timeout_guard():
    print("=== 枚举超时保护（cv2 阻塞不卡死） ===")
    m._CAMERA_SCAN_DONE = False
    m.HAS_CAMERA = True
    orig = m.cv2

    def _blocking_capture(idx):
        time.sleep(100)
        return _FakeCap(idx)

    class _BlockingCv:
        def VideoCapture(self, idx):
            return _blocking_capture(idx)

    m.cv2 = _BlockingCv()
    try:
        t0 = time.time()
        cams = m._enumerate_cameras()
        dt = time.time() - t0
        assert dt < 10.0, f"超时保护失效: {dt:.1f}s"
        assert cams == []
    finally:
        m.cv2 = orig
        m._CAMERA_SCAN_DONE = False
    print("  PASSED")


def test_print_cameras_button():
    print("=== [v] 列出摄像头按钮 ===")
    from unittest import mock
    m._CAMERA_SCAN_DONE = False
    m.HAS_CAMERA = True
    orig = m.cv2
    m.cv2 = _FakeCv()
    os.environ.pop("DSN_CAMERA_MAP", None)
    try:
        with mock.patch("builtins.print") as mp:
            m.print_cameras(None)
        texts = [str(c.args[0]) for c in mp.call_args_list]
        joined = "\n".join(texts)
        assert "cam0" in joined and "cam1" in joined, texts
        assert "主摄像头" in joined  # cam0 是主摄像头 (CAMERA_DEVICE_ID=0)

        # 带备注的后端
        class _FakeClient:
            def _http_get(self, path, timeout=10):
                class _R:
                    status_code = 200
                    def json(self):
                        return {"cameras": [{"logical_name": "cam1", "note": "门口摄像头"}]}
                return _R()
        with mock.patch("builtins.print") as mp:
            m.print_cameras(_FakeClient())
        texts2 = [str(c.args[0]) for c in mp.call_args_list]
        assert any("门口摄像头" in t for t in texts2), texts2
    finally:
        m.cv2 = orig
        m._CAMERA_SCAN_DONE = False
    print("  PASSED")


def test_capture_save_to_temp():
    print("=== 按 v 逐台拍照保存到 temp ===")
    import numpy as np
    from pathlib import Path
    from unittest import mock

    class _SaveCap(_FakeCap):
        def read(self):
            return (True, np.zeros((240, 320, 3), dtype=np.uint8))

    class _SaveCv(_FakeCv):
        IMWRITE_JPEG_QUALITY = 90

        def VideoCapture(self, idx, backend=0):
            return _SaveCap(idx, idx in self._open)

        def imwrite(self, path, frame, params=None):
            Path(path).write_bytes(b"JPEGDATA")
            return True

    m._CAMERA_SCAN_DONE = False
    m.HAS_CAMERA = True
    orig = m.cv2
    m.cv2 = _SaveCv()
    os.environ.pop("DSN_CAMERA_MAP", None)
    tmp = Path(tempfile.mkdtemp())
    m.TTS_DIR = tmp
    try:
        with mock.patch("builtins.print") as mp:
            m.print_cameras(None)
        texts = [str(c.args[0]) for c in mp.call_args_list]
        files = sorted(tmp.glob("camera_*.jpg"))
        assert len(files) == 2, files  # cam0 / cam1 各一张
        assert any("✓ cam0" in t for t in texts), texts
        assert any("✓ cam1" in t for t in texts), texts
        assert all(f.suffix == ".jpg" for f in files)
    finally:
        m.cv2 = orig
        m._CAMERA_SCAN_DONE = False
    print("  PASSED")


def test_backend_consistency():
    print("=== 枚举与抓帧后端一致性 (Windows DSHOW/MSMF) ===")
    import numpy as np
    import io

    class _BCap:
        def __init__(self, idx, backend=0):
            self._opened = ((idx == 0 and backend == 700)
                            or (idx == 2 and backend == 1400)
                            or (idx == 3 and backend == 0))

        def isOpened(self):
            return self._opened

        def read(self):
            return (True, np.zeros((10, 10, 3), dtype=np.uint8))

        def release(self):
            pass

    class _BCv:
        CAP_DSHOW = 700
        CAP_MSMF = 1400

        def __init__(self):
            self.calls = []

        def VideoCapture(self, idx, backend=0):
            self.calls.append((idx, backend))
            return _BCap(idx, backend)

        def setLogLevel(self, lv):
            pass

        def imencode(self, *a, **k):
            return (True, io.BytesIO(b"JPG"))

    orig = m.cv2
    fc = _BCv()
    m.cv2 = fc
    m.HAS_CAMERA = True
    m._CAMERA_SCAN_DONE = False
    os.environ.pop("DSN_CAMERA_MAP", None)
    try:
        # Windows 风格后端：DSHOW(700) / MSMF(1400) / 默认(0)
        cams = m._scan_devices(6, backends=[700, 1400, 0])
        bmap = {c["index"]: c.get("backend") for c in cams}
        assert bmap[0] == 700, bmap
        assert bmap[2] == 1400, bmap
        assert bmap[3] == 0, bmap

        m._CAMERA_BACKEND.clear()
        for dev in cams:
            m._CAMERA_BACKEND[dev["index"]] = dev.get("backend")
        m._CAMERA_SCAN_DONE = True
        assert m._camera_backend_for(0) == 700
        assert m._camera_backend_for(2) == 1400

        # 抓帧复用同一后端
        fc.calls.clear()
        m._capture_camera_frame(0)
        assert fc.calls[-1] == (0, 700), fc.calls[-1]
        m._capture_camera_frame(2)
        assert fc.calls[-1] == (2, 1400), fc.calls[-1]
    finally:
        m.cv2 = orig
        m._CAMERA_SCAN_DONE = False
        m._CAMERA_BACKEND.clear()
    print("  PASSED")


if __name__ == "__main__":
    test_enumerate_with_env_map()
    test_enumerate_auto_names()
    test_enumerate_timeout_guard()
    test_coordinator_multi_frame()
    test_frame_submit_formats()
    test_look_around_multi_camera()
    test_print_cameras_button()
    test_capture_save_to_temp()
    test_backend_consistency()
    print("\nALL MULTI CAMERA TESTS PASSED")
