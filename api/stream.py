# api/stream.py
# VisionStreamingService — 服务器端实时监控影像流服务（MJPEG over HTTP）。
#
# 为 webUI 的「监控」页提供所有摄像头的实时画面：
#   - 远程 webcam：后端直接 cv2 抓帧（网络可达，帧间隔 ~0.3s）
#   - 本地物理摄像头：minimal.py 客户端主动推帧（StreamPusher）。webUI 有本地流
#     订阅时，后端心跳下发 streams 配置 → minimal.py 周期抓帧 POST 到
#     /api/vision/stream-frame → 写入对应会话。与 on-demand 视觉请求（look_around）
#     完全隔离，不占用请求-响应通道。
#
# 对外形态：每个摄像头一个 MJPEG 流（multipart/x-mixed-replace），
# webUI 用 <img src="/api/admin/vision/stream/<logical_name>"> 直接显示。
#
# 生命周期：按订阅者计数（延迟回收）；本地流由订阅状态驱动客户端推送，
# 无人观看时心跳下发 enabled=false，客户端停止推帧。

from __future__ import annotations

import base64
import logging
import threading
import time
from typing import Optional

logger = logging.getLogger("VisionStream")

# 抓帧间隔（秒）
WEBCAM_FRAME_INTERVAL = 0.3        # 远程 webcam：后端直抓
LOCAL_FRAME_INTERVAL = 2.0         # 本地摄像头流：心跳下发给 minimal.py 的推送间隔
NO_FRAME_TIMEOUT = 15.0            # 首次连接等待首帧的超时；若此后曾出过帧则流保活不断开
GRACE_SECONDS = 5.0                # 订阅者归零后延迟停止抓帧（避免频繁启停）


def _jpeg_from_data_url(data_url: str) -> Optional[bytes]:
    """从 base64 data URL 提取 JPEG 原始字节。"""
    try:
        header, _, b64 = data_url.partition(",")
        if not b64 and ";" not in header:
            return None
        raw = base64.b64decode(b64 or data_url)
        return raw if raw else None
    except Exception:
        return None


class StreamSession:
    """单台摄像头的流会话：抓帧线程写入最新帧，消费端（HTTP generator）等待新帧。"""

    def __init__(self, name: str, kind: str):
        self.name = name
        self.kind = kind                    # "webcam" | "local"
        self._cv = threading.Condition()
        self._latest: Optional[bytes] = None
        self._version = 0
        self._subscribers = 0
        self.last_frame_at = 0.0            # 最近一次收到帧的时间（在线判定用）

    # ── 抓帧线程写入 ──
    def set_frame(self, jpeg: bytes) -> None:
        with self._cv:
            self._latest = jpeg
            self._version += 1
            self.last_frame_at = time.time()
            self._cv.notify_all()

    # ── 消费端等待（每个连接维护自己的 since）──
    def wait_frame(self, since: int, timeout: float = NO_FRAME_TIMEOUT):
        """等待比 since 更新的帧。

        返回 (version, jpeg, is_new)：
        - 有新帧：version 递增，is_new=True
        - 超时无新帧、但曾出过帧：重发最后已知帧（保活，画面冻结），
          version 不变，is_new=False —— 防止瞬时推帧延迟导致流被断开
        - 超时且从未出过帧：返回 (since, None, False)（摄像头真离线）
        """
        with self._cv:
            while self._version <= since:
                if not self._cv.wait(timeout):
                    if self._latest is not None:
                        return self._version, self._latest, False   # 保活重发
                    return since, None, False
            return self._version, self._latest, True

    # ── 订阅计数 ──
    def acquire(self) -> int:
        with self._cv:
            self._subscribers += 1
            return self._subscribers

    def release(self) -> int:
        with self._cv:
            self._subscribers = max(0, self._subscribers - 1)
            return self._subscribers

    @property
    def subscribers(self) -> int:
        with self._cv:
            return self._subscribers


class VisionStreamingService:
    """统一管理所有摄像头的 MJPEG 流。

    - webcam 帧：后端直抓（后台线程，仅在有订阅者时抓帧）
    - 本地帧：minimal.py 客户端推送（POST /api/vision/stream-frame → ingest_frames）
    """

    def __init__(self, coordinator=None):
        self._coordinator = coordinator
        self._lock = threading.Lock()
        self._sessions: dict[str, StreamSession] = {}
        self._running = False

    # ── 协调器（懒读取，适配初始化时序）──
    def _coord(self):
        if self._coordinator is not None:
            return self._coordinator
        try:
            from api.vision import coordinator as _c
            return _c
        except Exception:
            return None

    def _kind_of(self, name: str) -> str:
        """判断摄像头归属：webcam / local。未登记名字按 local 兜底。"""
        coord = self._coord()
        if coord is not None and coord.webcam_manager is not None \
                and coord.webcam_manager.is_webcam(name):
            return "webcam"
        return "local"

    # ── 启动/停止抓帧线程 ──
    def start(self):
        with self._lock:
            if self._running:
                return
            self._running = True
        threading.Thread(target=self._webcam_loop, daemon=True,
                         name="stream-webcam").start()
        logger.info("VisionStreamingService 已启动")

    def stop(self):
        with self._lock:
            self._running = False

    # ── 本地流状态（供 heartbeat 判断是否需要下发推送配置）──
    def has_local_subscribers(self) -> bool:
        """是否存在有人正在观看的本地物理摄像头流。"""
        with self._lock:
            return any(s.kind == "local" and s.subscribers > 0
                       for s in self._sessions.values())

    def camera_online(self, name: str, max_age: float = 15.0) -> bool:
        """本地摄像头是否在线：以最近收到推帧的时间为准。

        避免依赖客户端启动上报的 last_seen（30s 后即过期，导致永远显示离线）。
        """
        with self._lock:
            sess = self._sessions.get(name)
            if sess is None or sess.kind != "local":
                return False
            return bool(sess.last_frame_at and (time.time() - sess.last_frame_at) < max_age)

    def ingest_frames(self, frames: list[dict]) -> int:
        """接收 minimal.py 推送的本地摄像头帧，写入对应会话。

        :param frames: [{logical_name, index, image_data}, ...]
        :return: 实际写入的帧数
        """
        n = 0
        for f in frames or []:
            name = f.get("logical_name", "")
            img = f.get("image_data", "")
            if not name or not img:
                continue
            sess = self._sessions.get(name)
            if sess is None or sess.kind != "local":
                continue
            jpeg = _jpeg_from_data_url(img)
            if jpeg:
                sess.set_frame(jpeg)
                n += 1
        return n

    # ── 会话管理 ──
    def _ensure_session(self, name: str, kind: str) -> StreamSession:
        with self._lock:
            sess = self._sessions.get(name)
            if sess is None:
                sess = StreamSession(name, kind)
                self._sessions[name] = sess
            sess.acquire()
            return sess

    def _release_session(self, name: str) -> None:
        with self._lock:
            sess = self._sessions.get(name)
            if not sess:
                return
            if sess.release() > 0:
                return
        # 延迟回收：给浏览器重连留出时间
        def _delayed():
            time.sleep(GRACE_SECONDS)
            with self._lock:
                sess2 = self._sessions.get(name)
                if sess2 is not None and sess2.subscribers <= 0:
                    self._sessions.pop(name, None)
                    logger.info("流会话已回收: %s", name)
        threading.Thread(target=_delayed, daemon=True,
                         name="stream-gc").start()

    # ── 对外：MJPEG 生成器 ──
    def serve(self, name: str):
        """返回 MJPEG generator；摄像头不存在返回 None。"""
        coord = self._coord()
        if coord is None:
            return None
        # 只允许已注册的摄像头（本地客户端枚举上报 或 远程 webcam）
        known = {c["logical_name"] for c in coord.list_cameras()}
        if name not in known:
            return None
        kind = self._kind_of(name)
        sess = self._ensure_session(name, kind)
        if not self._running:
            self.start()

        def gen():
            since = 0
            try:
                while True:
                    ver, jpeg, _is_new = sess.wait_frame(since)
                    if jpeg is None:
                        break                       # 从未出过帧 → 断开（真离线）
                    since = ver
                    yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                           + jpeg + b"\r\n")
            finally:
                self._release_session(name)

        return gen()

    # ── 后台抓帧线程 ──
    def _active_names(self, kind: str) -> list[str]:
        with self._lock:
            return [n for n, s in self._sessions.items() if s.kind == kind]

    def _webcam_loop(self):
        while True:
            with self._lock:
                if not self._running:
                    return
            names = self._active_names("webcam")
            coord = self._coord()
            if not names or coord is None or coord.webcam_manager is None:
                time.sleep(1.0)
                continue
            mgr = coord.webcam_manager
            try:
                frames, _failed = mgr.capture_frames(names)
                for n, data_url in frames.items():
                    sess = self._sessions.get(n)
                    jpeg = _jpeg_from_data_url(data_url)
                    if sess is not None and jpeg:
                        sess.set_frame(jpeg)
            except Exception as e:
                logger.warning("webcam 流抓帧失败: %s", e)
            time.sleep(WEBCAM_FRAME_INTERVAL)
