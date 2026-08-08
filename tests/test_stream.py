# tests/test_stream.py
# 实时监控影像流测试：
#   _jpeg_from_data_url 提取 + StreamSession 版本化帧缓冲 +
#   VisionStreamingService webcam 流端到端 + 订阅者回收

import io
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _FakeFrame:
    shape = (8, 8, 3)


class _FakeCap:
    def __init__(self, url, opened=True):
        self._opened = opened

    def isOpened(self):
        return self._opened

    def set(self, *a):
        return True

    def read(self):
        return (True, _FakeFrame())

    def release(self):
        pass


class _FakeCv:
    CAP_PROP_OPEN_TIMEOUT_MSEC = 1
    CAP_PROP_READ_TIMEOUT_MSEC = 2
    IMWRITE_JPEG_QUALITY = 90

    def VideoCapture(self, url, *a):
        return _FakeCap(url)

    def imencode(self, ext, frame, params=None):
        return (True, memoryview(b"JPEGDATA"))


def _install_fake_cv():
    sys.modules["cv2"] = _FakeCv()


def _make_webcam_coord():
    from api.vision import VisionCoordinator
    from tracking.webcam import WebCamManager
    _install_fake_cv()
    cfg = Path(tempfile.mkdtemp()) / "webcams.json"
    mgr = WebCamManager(path=str(cfg))
    assert mgr.add("rtsp://10.0.0.2:554/1", name="camA", note="客厅", test=True)["ok"]
    coord = VisionCoordinator()
    coord.register_webcam_manager(mgr)
    return coord, mgr


# ═══════════════════════════════════════

def test_jpeg_extract():
    print("=== _jpeg_from_data_url 提取 ===")
    import base64
    from api.stream import _jpeg_from_data_url
    b64 = base64.b64encode(b"JPEGDATA").decode()
    assert _jpeg_from_data_url("data:image/jpeg;base64," + b64) == b"JPEGDATA"
    assert _jpeg_from_data_url("") is None
    assert _jpeg_from_data_url("not-a-data-url") is None
    assert _jpeg_from_data_url("data:image/jpeg;base64,!!!badbase64!!!") is None
    print("  PASSED")


def test_session_flow():
    print("=== StreamSession 版本化帧缓冲 ===")
    from api.stream import StreamSession
    s = StreamSession("camA", "webcam")

    # 无帧时超时返回（从未出帧 → None，真离线）
    v, f, is_new = s.wait_frame(0, timeout=0.2)
    assert v == 0 and f is None and is_new is False

    # 新帧到达
    s.set_frame(b"jpeg1")
    v, f, is_new = s.wait_frame(0, timeout=1)
    assert v == 1 and f == b"jpeg1" and is_new is True

    # 同版本不重复返回
    s.set_frame(b"jpeg2")
    v, f, is_new = s.wait_frame(1, timeout=1)
    assert v == 2 and f == b"jpeg2" and is_new is True

    # 订阅计数
    assert s.acquire() == 1
    assert s.acquire() == 2
    assert s.release() == 1
    assert s.release() == 0
    assert s.release() == 0
    print("  PASSED")


def test_session_keepalive():
    print("=== 流保活：无新帧时重发最后帧，不断开 ===")
    from api.stream import StreamSession
    s = StreamSession("camA", "webcam")

    # 无任何帧 → 超时返回 None（断开）
    v, f, is_new = s.wait_frame(0, timeout=0.3)
    assert f is None

    # 出过一帧后，无新帧超时 → 重发最后帧保活（画面冻结，连接保持）
    s.set_frame(b"frozen")
    v, f, is_new = s.wait_frame(0, timeout=0.3)
    assert v == 1 and f == b"frozen" and is_new is True

    v2, f2, is_new2 = s.wait_frame(1, timeout=0.3)
    assert f2 == b"frozen" and is_new2 is False, "应重发最后帧保活"
    assert v2 == 1

    # 多轮保活不中断
    v3, f3, is_new3 = s.wait_frame(1, timeout=0.3)
    assert f3 == b"frozen" and is_new3 is False

    # 新帧到来 → 恢复实时推送
    s.set_frame(b"fresh")
    v4, f4, is_new4 = s.wait_frame(1, timeout=1)
    assert f4 == b"fresh" and is_new4 is True and v4 == 2
    print("  PASSED")


def test_stream_webcam_end_to_end():
    print("=== VisionStreamingService webcam 流端到端 ===")
    import api.stream as _st
    _st.GRACE_SECONDS = 1   # 缩短回收等待，加速测试
    from api.stream import VisionStreamingService
    coord, mgr = _make_webcam_coord()
    svc = VisionStreamingService(coord)
    svc.start()

    gen = svc.serve("camA")
    assert gen is not None
    assert "camA" in svc._sessions

    # 消费 3 帧（MJPEG 分块）
    frames = []
    for _ in range(3):
        chunk = next(gen)
        frames.append(chunk)
        assert b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" in chunk, chunk[:50]
        assert b"JPEGDATA" in chunk
        assert chunk.endswith(b"\r\n")
    assert len(frames) == 3

    # 未知名字 → None
    assert svc.serve("nope_unknown") is None

    # 关闭 generator（模拟浏览器断开）→ 订阅释放 + 延迟回收
    gen.close()
    time.sleep(2.5)  # 覆盖后的 GRACE_SECONDS=1 + 余量
    assert "camA" not in svc._sessions, "订阅者归零后应回收会话"

    svc.stop()
    print("  PASSED")


def test_stream_kind_and_multi_subscriber():
    print("=== 摄像头分类 + 多订阅者 ===")
    from api.stream import VisionStreamingService
    coord, mgr = _make_webcam_coord()
    svc = VisionStreamingService(coord)

    # webcam 识别
    assert svc._kind_of("camA") == "webcam"
    assert svc._kind_of("cam0") == "local"   # 未登记名兜底为本地

    # 两个订阅者共享同一会话
    g1 = svc.serve("camA")
    g2 = svc.serve("camA")
    assert svc._sessions["camA"].subscribers == 2
    next(g1)
    next(g2)
    assert svc._sessions["camA"].subscribers == 2
    g1.close()
    assert svc._sessions["camA"].subscribers == 1
    g2.close()
    svc.stop()
    print("  PASSED")


def test_stream_local_push_end_to_end():
    print("=== 本地摄像头流端到端：订阅 → 客户端推送 → 出帧 ===")
    import base64
    import api.stream as _st
    _st.GRACE_SECONDS = 1
    from api.stream import VisionStreamingService
    from api.vision import VisionCoordinator

    # 后端已注册本地摄像头 cam0（minimal.py 上报）
    coord = VisionCoordinator()
    coord.register_cameras([{"logical_name": "cam0", "index": 0}])
    svc = VisionStreamingService(coord)
    svc.start()

    # 无人订阅时不应下发推送配置
    assert not svc.has_local_subscribers()

    # webUI 订阅 cam0 流
    gen = svc.serve("cam0")
    assert gen is not None
    assert svc.has_local_subscribers(), "有本地流订阅者时心跳应下发 enabled=true"

    # minimal.py StreamPusher 推送帧 → ingest_frames 写入会话
    b64 = base64.b64encode(b"LOCALJPEG").decode()
    n = svc.ingest_frames([{"logical_name": "cam0", "index": 0,
                            "image_data": "data:image/jpeg;base64," + b64}])
    assert n == 1, "应写入 1 帧"

    # 无订阅会话的帧被忽略（例如 webcam 会话不存在时）
    n2 = svc.ingest_frames([{"logical_name": "no_such", "image_data": "x"}])
    assert n2 == 0

    chunk = next(gen)
    assert b"LOCALJPEG" in chunk
    assert chunk.endswith(b"\r\n")

    # 断开 → 订阅清零 → 心跳不再下发推送配置
    gen.close()
    time.sleep(2.5)
    assert not svc.has_local_subscribers(), "订阅者归零后不应再要求客户端推送"
    svc.stop()
    print("  PASSED")


def test_stream_serve_rejects_unknown():
    print("=== serve 拒绝未知摄像头 ===")
    from api.stream import VisionStreamingService
    from api.vision import VisionCoordinator
    coord = VisionCoordinator()   # 空，无任何摄像头
    svc = VisionStreamingService(coord)
    assert svc.serve("ghost") is None
    assert not svc.has_local_subscribers()
    svc.stop()
    print("  PASSED")


def test_camera_online_by_push():
    print("=== 本地摄像头在线判定：基于最近推帧而非启动上报 ===")
    import base64
    from api.stream import VisionStreamingService
    from api.vision import VisionCoordinator
    coord = VisionCoordinator()
    coord.register_cameras([{"logical_name": "cam0", "index": 0}])
    svc = VisionStreamingService(coord)

    # 未推帧 → 离线
    assert not svc.camera_online("cam0")

    # 订阅后推送一帧 → 在线
    gen = svc.serve("cam0")
    b64 = base64.b64encode(b"X").decode()
    svc.ingest_frames([{"logical_name": "cam0",
                        "image_data": "data:image/jpeg;base64," + b64}])
    assert svc.camera_online("cam0")

    # 未注册摄像头 → 离线
    assert not svc.camera_online("ghost")

    gen.close()
    svc.stop()
    print("  PASSED")


if __name__ == "__main__":
    test_jpeg_extract()
    test_session_flow()
    test_session_keepalive()
    test_stream_webcam_end_to_end()
    test_stream_kind_and_multi_subscriber()
    test_stream_local_push_end_to_end()
    test_stream_serve_rejects_unknown()
    test_camera_online_by_push()
    print("\nALL STREAM TESTS PASSED")
