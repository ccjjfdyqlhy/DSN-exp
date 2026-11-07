# apps/dsn/CLI/vision.py
# 视觉推送组件：VisionObserver（周期主动视觉）+ StreamPusher（实时监控流）。
#
# 从原 psychoscope/minimal.py 抽出（1447-1613）。抓帧统一走 camera 模块；
# 推送经 client 的 keep-alive Session。配置均由 heartbeat 下发自配置（configure→start）。

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Optional

from .camera import _capture_all_cameras, _capture_camera_frame, CAMERA_DEVICE_ID
from .env import HAS_CAMERA, log


# ════════════════════════════════════════════════════════════════
# VisionObserver — 周期性主动视觉：本地 cv2 抓帧 → POST /api/vision/observation
# ════════════════════════════════════════════════════════════════

class VisionObserver:
    """每 interval 秒本地抓帧推送后端（后端跑 VisionModel + 场景变化 + 通知）。

    配置由 heartbeat 响应的 active_vision 字段自配置（configure→start）。
    """

    def __init__(self, client):
        self._client = client
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._enabled = False
        self._interval = 300
        self._camera = ""

    def configure(self, enabled: bool, interval: int, camera: str = "") -> bool:
        """更新配置；返回配置是否发生变化。"""
        enabled = bool(enabled)
        interval = max(30, int(interval or 300))
        camera = camera or ""
        changed = (enabled != self._enabled) or (interval != self._interval) \
            or (camera != self._camera)
        self._enabled = enabled
        self._interval = interval
        self._camera = camera
        return changed

    def start(self):
        if self._running:
            return
        if not self._enabled:
            log.info("VisionObserver 未启用 (active_vision.enabled=false)")
            return
        if not HAS_CAMERA:
            log.warning("VisionObserver: opencv-python 未安装，无法周期抓帧")
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log.info("VisionObserver 已启动 (interval=%ds)", self._interval)

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def _loop(self):
        while self._running:
            # 可被 stop 中断的间隔等待
            for _ in range(self._interval):
                if not self._running:
                    return
                time.sleep(1)
            if not self._running:
                return
            frame = _capture_camera_frame(self._camera or CAMERA_DEVICE_ID)
            if frame is None:
                log.warning("VisionObserver: 抓帧失败，跳过本轮")
                continue
            try:
                self._client._http_post("/api/vision/observation", json={
                    "image_data": frame,
                    "camera": self._camera or "default",
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }, timeout=30)
                log.info("VisionObserver: 帧已推送后端 (camera=%s)", self._camera or "default")
            except Exception:
                log.warning("VisionObserver: 推送后端失败", exc_info=True)


# ════════════════════════════════════════════════════════════════
# StreamPusher — 实时监控流推送：本机摄像头周期推帧 → webUI 实时画面
# ════════════════════════════════════════════════════════════════

class StreamPusher:
    """响应 heartbeat 下发的 streams 配置，周期抓帧推送后端（供 webUI 监控页）。

    与 on-demand（vision_request / look_around）完全隔离：
    - 推送走独立端点 /api/vision/stream-frame，不占用请求-响应通道，
      不会饿死 look_around
    - 仅当后端 webUI 有本地摄像头流订阅时下发 enabled=true，客户端才推帧；
      无人观看时后端下发 enabled=false，客户端停止，零开销
    """

    def __init__(self, client):
        self._client = client
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._enabled = False
        self._interval = 2.0
        self._fail_count = 0
        self._lock = threading.Lock()

    def configure(self, enabled: bool, interval: float = 2.0) -> bool:
        """更新配置；返回配置是否发生变化（供心跳判断是否需要启停）。"""
        enabled = bool(enabled)
        interval = float(interval or 2.0)
        changed = (enabled != self._enabled) or (interval != self._interval)
        self._enabled = enabled
        self._interval = interval
        return changed

    def start(self):
        with self._lock:
            if self._running:
                return
            if not self._enabled:
                log.info("StreamPusher 未启用 (streams.enabled=false)")
                return
            if not HAS_CAMERA:
                log.warning("StreamPusher: opencv-python 未安装，无法推帧")
                return
            self._running = True
            self._fail_count = 0
            self._thread = threading.Thread(target=self._loop, daemon=True,
                                            name="stream-pusher")
            self._thread.start()
        log.info("StreamPusher 已启动 (interval=%.1fs)", self._interval)

    def stop(self):
        with self._lock:
            self._running = False
            t = self._thread
        if t:
            # 线程可能正卡在抓帧/推送中，join 超时后仍让其自愈退出
            # （_loop 会在下一轮检查 _running）；不阻塞心跳线程太久。
            t.join(timeout=3)
            if t.is_alive():
                log.warning("StreamPusher: 线程未及时退出（可能在抓帧中），等待自愈")
            with self._lock:
                if self._thread is t:
                    self._thread = None

    def _loop(self):
        while self._running:
            try:
                frames = _capture_all_cameras()
                if frames:
                    resp = self._client._http_post(
                        "/api/vision/stream-frame",
                        json={"frames": frames}, timeout=20)
                    if resp.status_code == 200:
                        self._fail_count = 0
                        log.debug("StreamPusher: 已推送 %d 帧", len(frames))
                    else:
                        self._fail_count += 1
                        log.debug("StreamPusher: 后端拒绝推送 HTTP %d",
                                  resp.status_code)
                else:
                    self._fail_count = 0   # 无摄像头不视为失败
            except Exception:
                self._fail_count += 1
                log.warning("StreamPusher: 推送失败", exc_info=True)
            # 失败退避：连续失败时指数退避（最多 ~30s），
            # 避免后端维护/网络异常期间高频刷屏；成功或恢复后自动回到正常间隔
            backoff = min(30, (1 << min(self._fail_count, 5)) - 1) if self._fail_count else 0
            # 可被 stop 中断的间隔等待
            for _ in range(max(1, int(self._interval)) + backoff):
                if not self._running:
                    return
                time.sleep(1)
