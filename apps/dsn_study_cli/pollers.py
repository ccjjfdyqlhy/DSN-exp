# apps/dsn_study_cli/pollers.py
# 两个后台轮询器：心跳（通知 + 视觉下行）与异步任务状态。
#
# 心跳除通知播报外，还处理阶段 5 的下行字段：
#   - vision_request: 服务端 AI 调了 look_around → 抓帧回传 /api/vision/frame
#     （这是「AI 主动说看一下」的唯一通道）
#   - active_vision:  自配置周期观测线程（enabled 时按 interval 推
#     /api/vision/observation）
#   - streams:        自配置实时流推帧（enabled 时按 interval 推
#     /api/vision/stream-frame）

from __future__ import annotations

import logging
import os
import threading
import time

import requests

from apps.dsn_study_cli import camera

logger = logging.getLogger("study_cli.pollers")

HEARTBEAT_INTERVAL = int(os.environ.get("STUDY_HEARTBEAT_INTERVAL", "2"))
HEARTBEAT_BACKOFF_MAX = 60

ASYNC_POLL_INTERVAL = int(os.environ.get("STUDY_ASYNC_POLL_INTERVAL", "8"))
ASYNC_POLL_TIMEOUT = 600


class HeartbeatPoller:
    """心跳轮询：通知 + 视觉请求下行 + 观测/推流自配置。"""

    def __init__(self, client, on_notify=None, cfg=None):
        self._client = client
        self._on_notify = on_notify          # callable(reply_text)
        self._cfg = cfg or {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._backoff = 0
        # 主动观测 / 推流状态（由心跳响应自配置）
        self._active_vision = {"enabled": False, "interval": 300, "camera": ""}
        self._streams = {"enabled": False, "interval": 2.0}
        self._last_observation = 0.0
        self._last_stream = 0.0
        self._last_notified: dict[str, float] = {}

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._loop, daemon=True, name="cli-heartbeat")
            self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._beat()
                self._backoff = 0
            except Exception as e:   # noqa: BLE001
                self._backoff = min(self._backoff * 2 or 2,
                                    HEARTBEAT_BACKOFF_MAX)
                logger.debug("心跳失败（退避 %ds）: %s", self._backoff, e)
            # 1s 步进等待，便于快速 stop
            waited = 0.0
            while waited < HEARTBEAT_INTERVAL and not self._stop.is_set():
                self._stop.wait(0.5)
                waited += 0.5

    def _beat(self):
        data = self._client.heartbeat()
        if not isinstance(data, dict) or data.get("error"):
            return

        # 1) 视觉按需请求：抓帧回传（单台 / 全部）
        vr = data.get("vision_request")
        if vr and vr.get("request_id"):
            self._answer_vision_request(vr)

        # 2) 主动观测 / 推流自配置
        self._active_vision.update(data.get("active_vision") or {})
        self._streams.update(data.get("streams") or {})
        now = time.time()
        av = self._active_vision
        if av.get("enabled") and now - self._last_observation >= max(
                30, float(av.get("interval", 300))):
            self._last_observation = now
            self._push_observation(av.get("camera", ""))
        st = self._streams
        if st.get("enabled") and now - self._last_stream >= max(
                1.0, float(st.get("interval", 2.0))):
            self._last_stream = now
            self._push_stream_frames()

        # 3) 通知播报
        if data.get("has_notification") and data.get("reply"):
            task_id = str(data.get("task_id") or "")
            # 防重：同一 task 10s 内只播一次
            last = self._last_notified.get(task_id, 0)
            if now - last > 10:
                self._last_notified[task_id] = now
                print(f"\n🔔 {data['reply']}")
                if self._on_notify:
                    try:
                        self._on_notify(data["reply"])
                    except Exception:   # noqa: BLE001
                        pass

    def _answer_vision_request(self, vr: dict):
        camera_name = (vr.get("camera") or "").strip()
        if camera_name in ("all", "all_cameras"):
            frames = camera.capture_all_cameras(self._cfg)
        else:
            data_url = camera.capture_frame(camera_name or None, self._cfg)
            # 标签用**真实**逻辑名（默认摄像头可能是 desk，不是 cam0）
            frames = [{"logical_name": camera.resolve_camera_name(
                           camera_name or None, self._cfg),
                       "image_data": data_url or ""}]
        body = {"request_id": vr["request_id"], "frames": frames}
        if not any(f.get("image_data") for f in frames):
            body["error"] = "本地客户端未抓到帧（无摄像头或设备不可用）"
        try:
            r = self._client.session.post(
                f"{self._client.base}/api/vision/frame",
                headers=self._client._headers(), json=body, timeout=60)
            logger.debug("vision frame 回传: %s", r.status_code)
        except Exception:   # noqa: BLE001
            logger.warning("vision frame 回传失败", exc_info=True)

    def _push_observation(self, camera_name: str):
        data_url = camera.capture_frame(camera_name or None, self._cfg)
        if not data_url:
            return
        try:
            self._client.session.post(
                f"{self._client.base}/api/vision/observation",
                headers=self._client._headers(),
                json={"image_data": data_url, "camera": camera_name,
                      "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")},
                timeout=30)
        except Exception:   # noqa: BLE001
            logger.debug("observation 推送失败", exc_info=True)

    def _push_stream_frames(self):
        frames = camera.capture_all_cameras(self._cfg)
        if not frames:
            return
        try:
            self._client.session.post(
                f"{self._client.base}/api/vision/stream-frame",
                headers=self._client._headers(), json={"frames": frames},
                timeout=15)
        except Exception:   # noqa: BLE001
            logger.debug("stream-frame 推送失败", exc_info=True)


class AsyncTaskPoller:
    """异步任务轮询（scan_finish 的汇总任务走这里）。"""

    def __init__(self, client, tts_queue=None):
        self._client = client
        self._tts_queue = tts_queue
        self._tasks: dict[str, float] = {}   # task_id -> started_at
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._loop, daemon=True, name="cli-async-poll")
            self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def add_task(self, task_id: str):
        with self._lock:
            self._tasks[task_id] = time.time()
        self._wake.set()

    def _loop(self):
        while not self._stop.is_set():
            self._wake.wait(timeout=ASYNC_POLL_INTERVAL)
            self._wake.clear()
            if self._stop.is_set():
                return
            with self._lock:
                items = list(self._tasks.items())
            for task_id, started in items:
                try:
                    data = self._client.task_status(task_id)
                except Exception:   # noqa: BLE001
                    continue
                status = data.get("status")
                if status == "running":
                    if time.time() - started > ASYNC_POLL_TIMEOUT:
                        with self._lock:
                            self._tasks.pop(task_id, None)
                        print(f"\n（任务 {task_id[:8]} 超时）")
                    continue
                with self._lock:
                    self._tasks.pop(task_id, None)
                if status == "done":
                    reply = data.get("reply") or ""
                    print(f"\n📋 汇总: {reply}")
                    audio = data.get("audio_b64")
                    if audio and self._tts_queue is not None:
                        self._tts_queue.put((reply, audio))
                elif status == "failed":
                    print(f"\n（任务失败: {data.get('error', '?')}）")
                else:
                    print(f"\n（任务 {task_id[:8]}: {status}）")
