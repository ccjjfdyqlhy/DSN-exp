# apps/dsn/CLI/pollers.py
# 后台轮询组件：HeartbeatPoller（提醒/闹钟/视觉/感知配置下发通道）+ AsyncTaskPoller。
#
# 从原 psychoscope/minimal.py 抽出（1339-1440, 1613-1808）。
# 调整一：心跳失败指数退避——后端不可达时间歇从 2s 逐次翻倍至 60s 封顶，
#         成功立即恢复原间隔（_beat 返回 bool 标记成败，仅影响失败路径）。

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from typing import Optional

import requests

from .audio import _play_beep
from .camera import _cached_camera_frame, _capture_all_cameras, _capture_camera_frame
from .env import HAS_AUDIO, log


class AsyncTaskPoller:
    ASYNC_POLL_INTERVAL = 8
    ASYNC_POLL_TIMEOUT = 600

    def __init__(self, client, tts_queue):
        self._client = client
        self._tts_queue = tts_queue
        self._tasks: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._wake_event = threading.Event()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log.info("AsyncTaskPoller 已启动 (interval=%ds)", self.ASYNC_POLL_INTERVAL)

    def stop(self):
        self._running = False
        self._wake_event.set()
        if self._thread:
            self._thread.join(timeout=2)

    def add_task(self, task_id: str):
        with self._lock:
            if task_id not in self._tasks:
                self._tasks[task_id] = {"created": time.time()}
                log.info("AsyncTaskPoller: 开始轮询 %s", task_id)
                print(f"\n  \u23f3 异步任务已创建 ({task_id[:10]}...)，后台执行中...")
        self._wake_event.set()

    def _loop(self):
        while self._running:
            to_remove = []
            with self._lock:
                task_ids = list(self._tasks.keys())
                now = time.time()

            for task_id in task_ids:
                try:
                    resp = self._client._session.get(
                        f"{self._client.base}/api/task/status/{task_id}",
                        headers=self._client._headers(),
                        timeout=10,
                    )
                    if resp.status_code != 200:
                        log.warning("AsyncTaskPoller: %s HTTP %d", task_id, resp.status_code)
                        continue

                    data = resp.json()
                    status = data.get("status", "running")
                    log.info("AsyncTaskPoller: %s \u2192 status=%s", task_id, status)

                    if status == "running":
                        with self._lock:
                            task = self._tasks.get(task_id)
                            if task and now - task.get("created", 0) > self.ASYNC_POLL_TIMEOUT:
                                print(f"\n  \u26a0\ufe0f 异步任务超时 ({task_id[:10]}...)")
                                to_remove.append(task_id)
                        continue

                    reply = data.get("reply", "")
                    audio_b64 = data.get("audio_b64", "")
                    error = data.get("error", "")

                    if status == "done":
                        _play_beep(self._client, 660)
                        if reply:
                            print(f"\n  \U0001f4ac {reply}")
                        if audio_b64 and HAS_AUDIO and self._tts_queue is not None:
                            self._tts_queue.put((reply, audio_b64))
                        self._client._set_chat_id(data.get("chat_id"))
                        print(f"  \u2705 异步任务完成 ({task_id[:10]}...)")

                    elif status == "failed":
                        _play_beep(self._client, 220)
                        if error:
                            print(f"\n  \u274c 异步任务失败: {error}")
                        if reply:
                            print(f"  {reply}")

                    to_remove.append(task_id)

                except requests.exceptions.Timeout:
                    log.warning("AsyncTaskPoller: %s 请求超时", task_id)
                except Exception as e:
                    log.warning("AsyncTaskPoller: %s 异常 %s", task_id, e)
                    with self._lock:
                        task = self._tasks.get(task_id)
                        if task and now - task.get("created", 0) > self.ASYNC_POLL_TIMEOUT:
                            to_remove.append(task_id)

            with self._lock:
                for tid in to_remove:
                    self._tasks.pop(tid, None)

            self._wake_event.clear()
            self._wake_event.wait(timeout=self.ASYNC_POLL_INTERVAL)


# ════════════════════════════════════════════════════════════════
# HeartbeatPoller — 心跳轮询（提醒/闹钟/主动视觉/感知/监控流 配置下发通道）
# ════════════════════════════════════════════════════════════════

class HeartbeatPoller:
    HEARTBEAT_INTERVAL = int(os.environ.get("DSN_HEARTBEAT_INTERVAL", "2"))
    HEARTBEAT_TIMEOUT = 30
    HEARTBEAT_BACKOFF_MAX = 60  # 断线退避封顶（秒）

    def __init__(self, client, tts_queue,
                 vision_observer=None,
                 sensing_monitor=None,
                 stream_pusher=None):
        self._client = client
        self._tts_queue = tts_queue
        self._vision_observer = vision_observer
        self._sensing_monitor = sensing_monitor
        self._stream_pusher = stream_pusher
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_triggered: dict[str, dict] = {}
        self._last_notification_id: Optional[int] = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log.info("HeartbeatPoller 已启动 (interval=%ds)", self.HEARTBEAT_INTERVAL)

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def sync_now(self):
        self._beat()

    def skip_latest(self) -> bool:
        if not self._last_triggered:
            return False
        task_id = list(self._last_triggered.keys())[-1]
        info = self._last_triggered.get(task_id, {})
        try:
            resp = self._client._session.post(
                f"{self._client.base}/api/reminder/skip",
                json={"task_id": task_id},
                headers=self._client._headers(),
                timeout=10,
            )
            if resp.status_code == 200 and resp.json().get("success"):
                print(f"\n  \u23ed 已跳过: {info.get('text', task_id[:8])}")
                return True
        except Exception:
            logging.getLogger(__name__).warning("Operation failed", exc_info=True)
        return False

    def _loop(self):
        time.sleep(2)
        backoff = 0  # 连续失败退避秒数；0 = 正常节奏
        while self._running:
            ok = False
            try:
                ok = self._beat()
            except Exception as e:
                log.warning("HeartbeatPoller 心跳异常: %s", e)
            if ok:
                if backoff:
                    log.info("HeartbeatPoller 心跳恢复，退出退避节奏")
                backoff = 0
            else:
                # 指数退避：2 → 4 → 8 → ... → 60s 封顶；成功后立即恢复原间隔
                backoff = min(max(backoff * 2, self.HEARTBEAT_INTERVAL * 2),
                              self.HEARTBEAT_BACKOFF_MAX)
                log.debug("HeartbeatPoller 进入退避: %ds", backoff)
            wait = self.HEARTBEAT_INTERVAL if not backoff else backoff
            for _ in range(wait):
                if not self._running:
                    break
                time.sleep(1)

    def _beat(self) -> bool:
        """执行一次心跳。返回 True 表示请求到达后端（200 且 JSON 可解析）。"""
        try:
            resp = self._client._session.get(
                f"{self._client.base}/api/heartbeat",
                headers=self._client._headers(),
                timeout=self.HEARTBEAT_TIMEOUT,
            )
        except requests.exceptions.RequestException as e:
            log.debug("心跳请求失败: %s", e)
            return False

        if resp.status_code != 200:
            log.debug("心跳 HTTP %d", resp.status_code)
            return False

        try:
            data = resp.json()
        except Exception:
            return False

        # ── 主动视觉：用 heartbeat 下发的配置自配置 VisionObserver ──
        av = data.get("active_vision")
        if av and self._vision_observer is not None:
            if self._vision_observer.configure(
                    av.get("enabled", False), av.get("interval", 300),
                    av.get("camera", "")):
                log.info("VisionObserver 配置更新: enabled=%s interval=%s camera=%s",
                         av.get("enabled"), av.get("interval"), av.get("camera", ""))
                self._vision_observer.start()  # 已 start 则 no-op

        # ── 闲置时感知（聆听）：用 heartbeat 下发的 tracking/sensing 配置自配置 ──
        # 聆听能力现由 tracking 子系统（用户跟踪系统 infra）提供，优先用 tracking 配置。
        se = data.get("tracking") or data.get("sensing")
        if se and self._sensing_monitor is not None:
            if self._sensing_monitor.configure(
                    se.get("enabled", False), se.get("cooldown", 60),
                    se.get("max_record_secs", 6.0)):
                log.info("IdleSensingMonitor 配置更新: enabled=%s cooldown=%s max_record=%s",
                         se.get("enabled"), se.get("cooldown"), se.get("max_record_secs"))
                self._sensing_monitor.start()  # 已 start 则 no-op

        # ── 实时监控流推送：webUI 有本地摄像头流订阅时周期推帧到后端 ──
        st = data.get("streams")
        if st and self._stream_pusher is not None:
            if self._stream_pusher.configure(
                    st.get("enabled", False), st.get("interval", 2.0)):
                log.info("StreamPusher 配置更新: enabled=%s interval=%s",
                         st.get("enabled"), st.get("interval"))
                if st.get("enabled"):
                    self._stream_pusher.start()
                else:
                    self._stream_pusher.stop()

        # ── 按需视觉请求：抓一帧/多帧回传后端，唤醒阻塞中的 look_around ──
        vr = data.get("vision_request")
        if vr:
            rid = vr.get("request_id", "")
            cam = vr.get("camera", "") or ""
            if rid:
                log.info("收到 on-demand 视觉请求: %s camera=%r", rid, cam)
                if cam in ("all", "all_cameras"):
                    frames = _capture_all_cameras()
                else:
                    logical = cam or "default"
                    # 优先复用新鲜缓存帧（避免重新打开摄像头），否则现场抓帧
                    img = _cached_camera_frame(cam)
                    if img is None:
                        img = _capture_camera_frame(cam)
                    frames = [{"logical_name": logical, "image_data": img}] if img else []
                try:
                    payload = {"request_id": rid}
                    if frames:
                        payload["frames"] = frames
                    else:
                        payload["frames"] = []
                        payload["error"] = "未检测到可用摄像头或抓帧失败"
                    self._client._http_post("/api/vision/frame", json=payload, timeout=60)
                    if frames:
                        log.info("视觉帧已回传: %s (%d 张, 缓存命中)", rid, len(frames))
                    else:
                        log.warning("无法抓帧，已告知后端: %s", rid)
                except Exception:
                    log.warning("视觉帧回传失败: %s", rid, exc_info=True)

        if not data.get("has_notification"):
            return True

        reply = data.get("reply", "") or ""
        audio_b64 = data.get("audio_b64", "") or ""
        task_id = data.get("task_id", "")
        notification_id = data.get("notification_id")
        task_type = data.get("task_type", "reminder")
        chat_id = data.get("chat_id")
        tts_error = data.get("tts_error", "")

        tlabel = self._type_label(task_type)

        if chat_id:
            self._client._set_chat_id(chat_id)

        if reply:
            print(f"\n  \u23f0 [{tlabel}] {reply}")

        _play_beep(self._client, 880)

        if audio_b64 and HAS_AUDIO and self._tts_queue is not None:
            self._tts_queue.put((reply, audio_b64))
        elif tts_error:
            print(f"  (TTS 不可用: {tts_error})")

        if task_id:
            self._last_triggered[task_id] = {
                "text": reply,
                "type": tlabel,
                "notification_id": notification_id,
            }
        if notification_id is not None:
            self._last_notification_id = notification_id

        log.info("心跳收到提醒: task=%s reply=%d chars audio=%d chars",
                 task_id, len(reply), len(audio_b64))
        return True

    @staticmethod
    def _type_label(task_type: str) -> str:
        labels = {
            "reminder": "提醒", "habit": "习惯", "countdown": "倒计时",
            "daily_plan": "每日计划", "periodic": "周期", "alarm": "闹钟",
        }
        return labels.get(task_type, task_type)


# 兼容旧名（部分代码以 ReminderWatcher 引用心跳轮询器）
ReminderWatcher = HeartbeatPoller
