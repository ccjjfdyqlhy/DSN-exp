from __future__ import annotations

import argparse
import base64
import io
import json
import logging
import os
import queue
import re
import signal
import sys
import threading
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import requests
import pygame

try:
    from pvrecorder import PvRecorder
    HAS_PVRECORDER = True
except ImportError:
    HAS_PVRECORDER = False
    print("[WARN] pvrecorder missing. pip install pvrecorder")

HERE = Path(__file__).resolve().parent
DEFAULT_HOST = os.environ.get("DSN_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("DSN_PORT", 5000))
CONFIG_FILE = HERE / ".dsn_client.json"
TTS_DIR = HERE / "temp"
REMINDER_FILE = TTS_DIR / "reminders.json"
LOG_DIR = HERE / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / f"minimal_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

SAMPLE_RATE = 16000
SILENCE_TIMEOUT = 2.0
MAX_RECORD_SECS = 30
RMS_THRESHOLD = 0.008

def setup_logging():
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname).1s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for h in root.handlers[:]:
        root.removeHandler(h)

    fh = logging.FileHandler(str(LOG_FILE), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)
    root.addHandler(sh)

    return logging.getLogger("minimal")

log = setup_logging()

# ------ 检测 TTS 采样率并初始化 pygame mixer ------
def _detect_tts_sample_rate() -> int:
    """扫描 temp/ 目录，从已有 WAV 文件中检测 TTS 采样率。没有文件则返回默认 32000。"""
    if TTS_DIR.exists():
        for wf_path in sorted(TTS_DIR.glob("*.wav"), reverse=True):
            try:
                with wave.open(str(wf_path), 'rb') as wf:
                    sr = wf.getframerate()
                    if sr > 0:
                        log.info("从 %s 检测到 TTS 采样率: %d Hz", wf_path.name, sr)
                        return sr
            except Exception:
                pass
    log.info("未找到已有 TTS 文件, 使用默认采样率 32000 Hz")
    return 32000

_TTS_SAMPLE_RATE = _detect_tts_sample_rate()

try:
    pygame.init()
    pygame.mixer.init(frequency=_TTS_SAMPLE_RATE, size=-16, channels=1, buffer=512)
    HAS_AUDIO = True
    log.info("pygame mixer 就绪 (sr=%d Hz)", _TTS_SAMPLE_RATE)
except Exception as e:
    HAS_AUDIO = False
    log.warning("pygame mixer 初始化失败: %s", e)


def _play_beep(client: DSNClient, freq: int = 600):
    """通过 pygame 播放短促反馈音。"""
    if not HAS_AUDIO or not client._channel:
        return
    sr = 44100
    dur = 0.06
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    wave = np.sin(2 * np.pi * freq * t) * 0.3
    samples = np.clip(wave * 32767, -32768, 32767).astype(np.int16)
    try:
        snd = pygame.mixer.Sound(buffer=samples.tobytes())
        snd.set_volume(1.0)
        client._channel.play(snd)
    except Exception:
        pass


def raw_pcm_to_wav_b64(samples: np.ndarray, sr: int = SAMPLE_RATE) -> str:
    int_samples = np.clip(samples * 32767, -32768, 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(int_samples.tobytes())
    return base64.b64encode(buf.getvalue()).decode("utf-8")

def iter_sse_lines(response: requests.Response):
    event = ""
    for line in response.iter_lines(decode_unicode=True):
        if line is None:
            continue
        if line.startswith("event: "):
            event = line[7:].strip()
        elif line.startswith("data: "):
            data_str = line[6:]
            if data_str == "[DONE]":
                yield event, {}
                continue
            try:
                yield event, json.loads(data_str)
            except json.JSONDecodeError:
                yield event, {"raw": data_str}
        elif line == "":
            event = ""

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_config(cfg: dict):
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

class DSNClient:
    def __init__(self, host: str, port: int):
        self.base = f"http://{host}:{port}"
        self.api_key: Optional[str] = None
        self.uid: int = 0
        self.chat_id: Optional[int] = None
        self.display_name: str = ""
        self._tts_queue: queue.Queue[tuple[str, str] | None] = queue.Queue()
        self._channel = pygame.mixer.Channel(0) if HAS_AUDIO else None
        self._volume = 0.5
        self.async_poller = None  # 异步轮询器（main() 中注入）
        if self._channel:
            self._channel.set_volume(self._volume)
        if HAS_AUDIO:
            self._tts_thread = threading.Thread(target=self._tts_worker, daemon=True)
            self._tts_thread.start()

    def _tts_worker(self):
        while True:
            item = self._tts_queue.get()
            if item is None:
                self._tts_queue.task_done()
                continue
            text, b64 = item
            try:
                raw = base64.b64decode(b64)
                sound = pygame.mixer.Sound(file=io.BytesIO(raw))
                while self._channel.get_busy() and self._channel.get_queue() is not None:
                    time.sleep(0.005)
                if not self._channel.get_busy():
                    self._channel.play(sound)
                else:
                    self._channel.queue(sound)
                while self._channel.get_busy():
                    time.sleep(0.005)
            except Exception as e:
                log.error(f"TTS playback error: {e}")
            self._tts_queue.task_done()

    def authenticate(self, code: str = "", name: str = "") -> bool:
        cfg = load_config()
        self.display_name = name or cfg.get("display_name", "")
        self.uid = cfg.get("uid", 0)
        self.chat_id = cfg.get("chat_id")

        api_key = cfg.get("api_key", "")
        if api_key:
            print(f"  Checking local API Key (User: {self.display_name})...")
            self.api_key = api_key
            if self._verify_api_key():
                self.uid = cfg.get("uid", 0)
                self.display_name = cfg.get("display_name", "")
                print(f"  API Key OK (uid={self.uid})")
                return True
            print("  API Key invalid, need re-registration")
            self.api_key = None
            cfg.pop("api_key", None)
            cfg.pop("uid", None)
            save_config(cfg)

        if not code:
            return False

        if not self.display_name:
            self.display_name = input("  Your Name: ").strip() or "minimal"

        has_pairing = False
        try:
            r = requests.get(f"{self.base}/api/auth/pairing/status", timeout=5)
            if r.status_code == 200:
                has_pairing = r.json().get("active", False)
        except Exception:
            pass

        if not has_pairing:
            print("  No active pairing code on server.")
            print("  Type /newbind in server console.")
            return False

        print(f"  Submitting pairing code (code={code}, name={self.display_name})...")
        try:
            resp = requests.post(
                f"{self.base}/api/auth/pairing/verify",
                json={"code": code, "display_name": self.display_name, "is_admin": True},
                timeout=30,
            )
            if resp.status_code != 200:
                print("  Pairing failed")
                return False

            data = resp.json()
            session_id = data["session_id"]
            self.uid = data["uid"]
            self.display_name = data.get("display_name", self.display_name)
        except Exception as e:
            print(f"  Connection error: {e}")
            return False

        print("  Creating API Key...")
        try:
            resp = requests.post(
                f"{self.base}/api/auth/api-key/create",
                headers={"Authorization": f"Session {session_id}"},
                json={"name": "minimal-cli", "scopes": "read write"},
                timeout=30,
            )
            if resp.status_code != 200:
                print("  Failed to create API Key")
                return False

            data = resp.json()
            self.api_key = data["key"]
            cfg["api_key"] = self.api_key
            cfg["uid"] = self.uid
            cfg["display_name"] = self.display_name
            save_config(cfg)
            print(f"  API Key saved to {CONFIG_FILE}")
            return True
        except Exception as e:
            print(f"  Error creating API Key: {e}")
            return False

    def _verify_api_key(self) -> bool:
        if not self.api_key:
            return False
        try:
            resp = requests.get(
                f"{self.base}/api/personality/status",
                headers={"X-DSN-API-Key": self.api_key},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                uid = data.get("uid", 0)
                if uid > 0:
                    self.uid = uid
                    return True
            return False
        except Exception:
            return False

    def _headers(self) -> dict:
        if self.api_key:
            return {"X-DSN-API-Key": self.api_key}
        return {}

    def _http_get(self, path: str, **kwargs) -> requests.Response:
        return requests.get(f"{self.base}{path}", headers=self._headers(),
                            timeout=kwargs.pop("timeout", 30), **kwargs)

    def _http_post(self, path: str, **kwargs) -> requests.Response:
        return requests.post(f"{self.base}{path}", headers=self._headers(),
                             timeout=kwargs.pop("timeout", 30), **kwargs)

    def _http_post_stream(self, path: str, **kwargs) -> requests.Response:
        return requests.post(f"{self.base}{path}", headers=self._headers(),
                             stream=True, timeout=(10, 120), **kwargs)

    def send_async(self, message: str) -> Optional[str]:
        """发送异步消息，返回 task_id 供 AsyncTaskPoller 轮询。"""
        if not self.api_key or not message.strip():
            return None
        try:
            resp = self._http_post("/api/chat/async_send", json={
                "message": message,
                "chat_id": self.chat_id,
            })
            if resp.status_code == 202:
                data = resp.json()
                return data.get("task_id")
            log.warning("Async send HTTP %d: %s", resp.status_code, resp.text[:200])
            return None
        except Exception as e:
            log.error("Async send failed: %s", e)
            return None

    def send_audio(self, audio_b64: str) -> Optional[str]:
        if not self.api_key:
            return None

        t0 = time.perf_counter()

        try:
            resp = self._http_post_stream(
                "/api/asr/passthrough",
                json={
                    "audio_b64": audio_b64,
                    "chat_id": self.chat_id,
                    "chat_name": "minimal",
                },
            )
            if resp.status_code != 200:
                return None

            # TTS 直接推入播放队列，不等 SSE 结束
            reply_text, t_first_audio = self._handle_sse_stream(resp, self._tts_queue, t0, async_poller=self.async_poller)
            elapsed = time.perf_counter() - t0

            # 显示首条音频耗时
            if t_first_audio is not None:
                first_audio_ms = (t_first_audio - t0) * 1000
                print(f"\n  🔊 首条音频: {first_audio_ms:.0f}ms")

            # 显示总耗时
            minutes = int(elapsed) // 60
            seconds = int(elapsed) % 60
            if minutes > 0:
                print(f"\n  ⏱  {minutes}分{seconds}秒")
            else:
                print(f"\n  ⏱  {seconds}秒")

            return reply_text
        except Exception as e:
            log.error("Audio send failed: %s", e)
            return None

    def _handle_sse_stream(self, resp: requests.Response,
                           tts_queue: queue.Queue | None = None,
                           t_start: float = None,
                           async_poller=None) -> tuple[Optional[str], float]:
        reply = ""
        got_text = False
        t_first_audio = None

        for _evt_type, data in iter_sse_lines(resp):
            status = data.get("status", "")

            if status == "async_task":
                task_id = data.get("task_id", "")
                if task_id and async_poller:
                    async_poller.add_task(task_id)
                continue

            if status == "text_ready":
                reply = data.get("reply", "")
                got_text = True
                self.chat_id = data.get("chat_id", self.chat_id)
                if reply:
                    print(f"\n  💬 {reply}")

            elif status == "narrative_update":
                text = data.get("text", "")
                speaker = data.get("speaker", "")
                if speaker == "narrator":
                    print(f"\n  [Narrator] {text}")
                elif text:
                    print(f"\n  {text}")

            elif status == "line":
                idx = data.get("index", 0) + 1
                total = data.get("total", 1)
                text = data.get("text", "")
                audio_b64 = data.get("audio_b64", "")
                if audio_b64 and HAS_AUDIO and tts_queue is not None:
                    if t_first_audio is None:
                        t_first_audio = time.perf_counter()
                    tts_queue.put((text, audio_b64))
                print(f"\r  🎵 TTS [{idx}/{total}]", end="", flush=True)

            elif status == "completed":
                break
        return reply if got_text else None, t_first_audio


class AsyncTaskPoller:
    """后台线程: 每 N 秒轮询后端异步任务状态，完成时显示回复 + 播放 TTS。"""

    ASYNC_POLL_INTERVAL = 8      # 每 8 秒轮询一次
    ASYNC_POLL_TIMEOUT = 600     # 10 分钟超时

    def __init__(self, client: DSNClient, tts_queue: queue.Queue):
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
        """开始轮询一个异步任务"""
        with self._lock:
            if task_id not in self._tasks:
                self._tasks[task_id] = {"created": time.time()}
                log.info("AsyncTaskPoller: 开始轮询 %s", task_id)
                print(f"\n  ⏳ 异步任务已创建 ({task_id[:10]}...)，后台执行中...")
        self._wake_event.set()

    def _loop(self):
        while self._running:
            to_remove = []
            with self._lock:
                task_ids = list(self._tasks.keys())
                now = time.time()

            for task_id in task_ids:
                try:
                    resp = requests.get(
                        f"{self._client.base}/api/task/status/{task_id}",
                        headers=self._client._headers(),
                        timeout=10,
                    )
                    if resp.status_code != 200:
                        log.warning("AsyncTaskPoller: %s HTTP %d", task_id, resp.status_code)
                        continue

                    data = resp.json()
                    status = data.get("status", "running")
                    log.info("AsyncTaskPoller: %s → status=%s", task_id, status)

                    if status == "running":
                        with self._lock:
                            task = self._tasks.get(task_id)
                            if task and now - task.get("created", 0) > self.ASYNC_POLL_TIMEOUT:
                                print(f"\n  ⚠️ 异步任务超时 ({task_id[:10]}...)")
                                to_remove.append(task_id)
                        continue

                    # 完成
                    reply = data.get("reply", "")
                    audio_b64 = data.get("audio_b64", "")
                    error = data.get("error", "")

                    if status == "done":
                        if reply:
                            print(f"\n  💬 {reply}")
                        if audio_b64 and HAS_AUDIO and self._tts_queue is not None:
                            self._tts_queue.put((reply, audio_b64))
                        self._client.chat_id = data.get("chat_id", self._client.chat_id)
                        print(f"  ✅ 异步任务完成 ({task_id[:10]}...)")

                    elif status == "failed":
                        if error:
                            print(f"\n  ❌ 异步任务失败: {error}")
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

            # 清理已完成/超时任务
            with self._lock:
                for tid in to_remove:
                    self._tasks.pop(tid, None)

            self._wake_event.clear()
            self._wake_event.wait(timeout=self.ASYNC_POLL_INTERVAL)


class HeartbeatPoller:
    """后台线程: 每 N 秒向后端发心跳，检查是否有已完成的提醒任务。

    工作流程（与 /api/heartbeat 配合）：
      1. 每 HEARTBEAT_INTERVAL 秒发一次 GET /api/heartbeat
      2. 如果返回 has_notification=false → 什么都不做
      3. 如果返回 has_notification=true →
         a. 立即显示 reply 文本
         b. 把 audio_b64 推入 TTS 队列播放
         c. 记录最近触发的提醒，供 'k' 键跳过
      4. 前端不再主动判断提醒是否到期 —— 完全由后端 TaskManager 调度，
         到期后写入 task_notifications 表，心跳拉取并触发 AI 通知 + TTS。
    """

    HEARTBEAT_INTERVAL = 5      # 每 5 秒发一次心跳
    HEARTBEAT_TIMEOUT = 30      # 单次心跳请求超时

    def __init__(self, client: "DSNClient", tts_queue: queue.Queue):
        self._client = client
        self._tts_queue = tts_queue
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_triggered: dict[str, dict] = {}  # task_id -> {text, type, notification_id}
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
        """手动触发一次心跳（兼容旧接口，'r' 键调用）。"""
        self._beat()

    def skip_latest(self) -> bool:
        """跳过最近一条触发的提醒（调用 /api/reminder/skip）。"""
        if not self._last_triggered:
            return False
        task_id = list(self._last_triggered.keys())[-1]
        info = self._last_triggered.get(task_id, {})
        try:
            resp = requests.post(
                f"{self._client.base}/api/reminder/skip",
                json={"task_id": task_id},
                headers=self._client._headers(),
                timeout=10,
            )
            if resp.status_code == 200 and resp.json().get("success"):
                print(f"\n  ⏭ 已跳过: {info.get('text', task_id[:8])}")
                return True
        except Exception:
            pass
        return False

    def _loop(self):
        # 启动后稍等 2 秒再开始心跳，避免与服务端握手竞争
        time.sleep(2)
        while self._running:
            try:
                self._beat()
            except Exception as e:
                log.warning("HeartbeatPoller 心跳异常: %s", e)
            # 分段 sleep，便于快速退出
            for _ in range(self.HEARTBEAT_INTERVAL):
                if not self._running:
                    break
                time.sleep(1)

    def _beat(self):
        """发一次心跳请求并处理响应。"""
        try:
            resp = requests.get(
                f"{self._client.base}/api/heartbeat",
                headers=self._client._headers(),
                timeout=self.HEARTBEAT_TIMEOUT,
            )
        except requests.exceptions.RequestException as e:
            log.debug("心跳请求失败: %s", e)
            return

        if resp.status_code != 200:
            log.debug("心跳 HTTP %d", resp.status_code)
            return

        try:
            data = resp.json()
        except Exception:
            return

        if not data.get("has_notification"):
            return

        # 有提醒通知
        reply = data.get("reply", "") or ""
        audio_b64 = data.get("audio_b64", "") or ""
        task_id = data.get("task_id", "")
        notification_id = data.get("notification_id")
        task_type = data.get("task_type", "reminder")
        chat_id = data.get("chat_id")
        tts_error = data.get("tts_error", "")

        tlabel = self._type_label(task_type)

        # 更新 chat_id（后端可能新建了会话）
        if chat_id:
            self._client.chat_id = chat_id

        # 显示文本
        if reply:
            print(f"\n  ⏰ [{tlabel}] {reply}")

        # 播放提示音
        _play_beep(self._client, 880)

        # 播放 TTS
        if audio_b64 and HAS_AUDIO and self._tts_queue is not None:
            self._tts_queue.put((reply, audio_b64))
        elif tts_error:
            print(f"  (TTS 不可用: {tts_error})")

        # 记录最近触发的，供 'k' 键跳过
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

    @staticmethod
    def _type_label(task_type: str) -> str:
        labels = {
            "reminder": "提醒", "habit": "习惯", "countdown": "倒计时",
            "daily_plan": "每日计划", "periodic": "周期",
        }
        return labels.get(task_type, task_type)


# 兼容旧代码：ReminderWatcher 作为 HeartbeatPoller 的别名
ReminderWatcher = HeartbeatPoller


class VoiceRecorder:
    def __init__(self, client: DSNClient):
        self.client = client
        self._recording = False
        self._frames: list[np.ndarray] = []
        self._sent_frames = None
        self._last_speech_time = 0.0
        self._start_time = 0.0
        self._recorder: Optional[PvRecorder] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    @property
    def is_recording(self) -> bool:
        return self._recording

    def start(self):
        if self._recording:
            return
        if not HAS_PVRECORDER:
            print("  pvrecorder not installed")
            return

        try:
            self._recorder = PvRecorder(device_index=-1, frame_length=512)
        except Exception as e:
            print(f"  Cannot open microphone: {e}")
            return

        self._recording = True
        self._frames = []
        self._sent_frames = None
        self._last_speech_time = time.time()
        self._start_time = time.time()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop_and_send(self):
        if not self._recording:
            return

        self._recording = False
        self._stop_event.set()

        if self._recorder:
            try:
                self._recorder.stop()
            except Exception:
                pass

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)

        if self._recorder:
            try:
                self._recorder.delete()
            except Exception:
                pass
            self._recorder = None

        dur = time.time() - self._start_time

        if not self._frames or dur < 0.5:
            print("  Too short, ignored")
            return

        audio = np.concatenate(self._frames)
        b64 = raw_pcm_to_wav_b64(audio)
        self._sent_frames = self._frames
        self.client.send_audio(b64)

    def _capture_loop(self):
        try:
            self._recorder.start()
            while self._recording and not self._stop_event.is_set():
                frame = self._recorder.read()
                samples = np.array(frame, dtype=np.int16).astype(np.float32) / 32768.0
                energy = float(np.sqrt(np.mean(samples ** 2)))

                self._frames.append(samples)

                if energy > RMS_THRESHOLD:
                    self._last_speech_time = time.time()

                dur = time.time() - self._start_time
                sil = time.time() - self._last_speech_time

                bar_len = min(int(energy * 20), 20)
                bar = "#" * bar_len + "-" * (20 - bar_len)
                status = "Recording" if energy > RMS_THRESHOLD else "Silence  "
                print(f"\r  {status} [{bar}] {dur:.1f}s (Silence {sil:.1f}s)  ", end="", flush=True)

                if sil > SILENCE_TIMEOUT or dur > MAX_RECORD_SECS:
                    self._recording = False
                    break
        except Exception:
            pass
        finally:
            try:
                self._recorder.stop()
            except Exception:
                pass

class KeyboardHandler:
    def __init__(self):
        self._queue: queue.Queue[str] = queue.Queue()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1)

    def get(self, timeout: float = 0.1) -> Optional[str]:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def _loop(self):
        try:
            import termios
            import tty
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            tty.setcbreak(fd)
            try:
                while self._running:
                    import select
                    if select.select([sys.stdin], [], [], 0.1)[0]:
                        ch = sys.stdin.read(1)
                        if ch:
                            self._queue.put(ch)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except (ImportError, AttributeError):
            try:
                import msvcrt
                while self._running:
                    if msvcrt.kbhit():
                        ch = msvcrt.getch().decode("utf-8", errors="replace")
                        self._queue.put(ch)
                    time.sleep(0.05)
            except ImportError:
                while self._running:
                    time.sleep(0.1)

def print_header(cfg: dict, client: DSNClient = None, locked: bool = False):
    os.system("cls" if os.name == "nt" else "clear")
    print("===========================================")
    print("        DSN-exp  Minimal Client            ")
    print("===========================================")
    uid = cfg.get("uid", "?")
    name = cfg.get("display_name", "?")
    host = cfg.get("host", f"{DEFAULT_HOST}:{DEFAULT_PORT}")
    print(f"  Backend : {host}")
    print(f"  User    : uid={uid} ({name})")
    vol = int(client._volume * 100) if client else 50
    print(f"  Volume  : {vol}%")
    if locked:
        print("  🔒 Panel locked")
    print("===========================================")
    print("  [Enter]  Start / Stop speaking           ")
    print("  [Knob←]  Volume down (-10%)               ")
    print("  [Knob→]  Volume up (+10%)                  ")
    print("  [a x2]   Lock / Unlock panel              ")
    print("  [p]      Show personality status         ")
    print("  [s]      Toggle standby / wakeup         ")
    print("  [i]      System info (server + plan)      ")
    print("  [k]      Skip latest reminder             ")
    print("  [r]      Trigger heartbeat now            ")
    print("  [t]      Text input (sync)                 ")
    print("  [=]      Async task (long-running)          ")
    print("  [n/m]    Volume -/+                         ")
    print("  [h]      Show help                         ")
    print("  [q/Ctrl+C] Quit                          ")
    print("===========================================")
    print()

def print_personality(client: DSNClient):
    try:
        resp = client._http_get("/api/personality/status")
        if resp.status_code != 200:
            print(f"  Failed HTTP {resp.status_code}")
            return
        data = resp.json()
        mood = data.get("mood", {})
        aff = data.get("affinity_value", 0)
        lvl = data.get("affinity_level", {})
        interactions = data.get("total_interactions", 0)
        card = data.get("card_id", "")

        joy = mood.get("joy", 0.5)
        sad = mood.get("sadness", 0.2)
        ang = mood.get("anger", 0.1)
        fear = mood.get("fear", 0.15)

        print(f"\n  --- Personality Status ---")
        print(f"  Card      : {card}")
        print(f"  Interacts : {interactions}")
        print(f"  Affinity  : {aff:.0f}/100 ({lvl.get('label', '?')})")
        print(f"  Mood      : joy={joy:.2f} sad={sad:.2f} ang={ang:.2f} fear={fear:.2f}")
        print(f"  --------------------------")
    except Exception as e:
        print(f"  Error: {e}")

def toggle_standby(client: DSNClient):
    try:
        resp = requests.post(f"{client.base}/api/maintenance/toggle_standby", timeout=10)
        state = resp.json().get("state", "?")
        print(f"  Server State: {state}")
    except Exception as e:
        print(f"  Error: {e}")


def print_system_info(client: DSNClient):
    """显示系统状态 + 服务器维护态 + 计划摘要"""
    print(f"\n  --- System Info ---")
    try:
        resp = client._http_get("/api/maintenance/status")
        if resp.status_code == 200:
            st = resp.json()
            print(f"  Server   : {st.get('state', '?')}")
            idle = st.get("idle_minutes", 0)
            if idle:
                print(f"  Idle     : {idle} min")
    except Exception:
        pass

    try:
        resp = client._http_get("/api/todo/list")
        if resp.status_code == 200:
            todos = resp.json().get("todos", [])
            active = [t for t in todos if t.get("status") == "pending"]
            print(f"  Todos    : {len(active)} pending / {len(todos)} total")
    except Exception:
        pass

    try:
        resp = client._http_get("/api/reminder/list")
        if resp.status_code == 200:
            reminders = resp.json().get("reminders", [])
            if reminders:
                print(f"  Reminders: {len(reminders)} pending")
                for r in reminders[:5]:
                    tlabel = ReminderWatcher._type_label(r.get("task_type", ""))
                    st = r.get("scheduled_time", "")[:16].replace("T", " ")
                    print(f"    [{tlabel}] {st}  {r.get('text', '')[:40]}")
    except Exception:
        pass

    print(f"  ---------------------\n")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--pairing", default="")
    args = parser.parse_args()

    cfg = load_config()
    cfg["host"] = f"{args.host}:{args.port}"

    client = DSNClient(args.host, args.port)

    print(f"  Backend: http://{args.host}:{args.port}")
    try:
        r = requests.get(f"http://{args.host}:{args.port}/api/auth/status", timeout=5)
        if r.status_code == 200:
            st = r.json()
            methods = [k for k, v in st.get("methods", {}).items() if v]
            print(f"  Connected, methods: {', '.join(methods)}")
        else:
            print(f"  HTTP {r.status_code}")
    except Exception as e:
        print(f"  Connection check error: {e}")
        sys.exit(1)

    display_name = cfg.get("display_name", "")
    pairing_code = args.pairing

    while True:
        ok = client.authenticate(code=pairing_code, name=display_name)
        if ok:
            break

        print("\n  ========================================")
        print("            DSN-exp Registration          ")
        print("  ========================================")
        pairing_code = input("  Pairing Code: ").strip()
        if not display_name:
            display_name = input("  Your Name: ").strip()
        if not pairing_code:
            sys.exit(1)

    cfg = load_config()
    cfg["uid"] = client.uid
    cfg["display_name"] = client.display_name
    if client.chat_id:
        cfg["chat_id"] = client.chat_id
    save_config(cfg)

    print_header(cfg, client)
    print("  Ready! Press Enter to speak...\n")

    recorder = VoiceRecorder(client)
    keyboard = KeyboardHandler()
    keyboard.start()
    reminder = HeartbeatPoller(client, client._tts_queue)
    reminder.start()
    async_poller = AsyncTaskPoller(client, client._tts_queue)
    async_poller.start()
    client.async_poller = async_poller

    def on_sigint(sig, frame):
        if recorder.is_recording:
            recorder.stop_and_send()
        async_poller.stop()
        reminder.stop()
        keyboard.stop()
        save_config(cfg)
        print("\n  Goodbye")
        sys.exit(0)

    signal.signal(signal.SIGINT, on_sigint)

    buffer = ""
    locked = False
    _last_a_ts = 0.0
    _DOUBLE_CLICK_WINDOW = 0.5
    try:
        while True:
            ch = keyboard.get(timeout=0.15)
            if ch is None:
                if recorder._frames and not recorder.is_recording and not recorder._sent_frames is recorder._frames:
                    print()
                    recorder.stop_and_send()
                    print()
                continue

            # ── 双击 'a' 锁定/解锁 ──
            if ch.lower() == "a":
                now = time.time()
                if now - _last_a_ts < _DOUBLE_CLICK_WINDOW:
                    locked = not locked
                    if locked:
                        if recorder.is_recording:
                            recorder.stop_and_send()
                        print("\n  🔒 Panel locked")
                    else:
                        print("\n  🔓 Panel unlocked")
                    _last_a_ts = 0.0
                    continue
                _last_a_ts = now
                continue

            # ── 锁定时忽略除 'a' 外所有输入 ──
            if locked:
                continue

            if ch in ("\r", "\n"):
                if recorder.is_recording:
                    print()
                    recorder.stop_and_send()
                    print()
                else:
                    print("\n  Speaking... (Press Enter to stop)")
                    recorder.start()

            elif ch.lower() == "q":
                if recorder.is_recording:
                    recorder.stop_and_send()
                break

            elif ch.lower() == "p":
                print_personality(client)

            elif ch.lower() == "s":
                toggle_standby(client)

            elif ch.lower() == "i":
                print_system_info(client)

            elif ch.lower() == "k":
                if not reminder.skip_latest():
                    print("\n  No recent reminder to skip")

            elif ch.lower() == "r":
                # 手动触发一次心跳，并显示后端 PENDING 提醒列表
                reminder.sync_now()
                try:
                    resp = client._http_get("/api/reminder/list")
                    if resp.status_code == 200:
                        reminders = resp.json().get("reminders", [])
                        now = datetime.now()
                        upcoming = []
                        for r in reminders:
                            try:
                                st = datetime.fromisoformat(r["scheduled_time"])
                                if st > now:
                                    upcoming.append(r)
                            except Exception:
                                continue
                        upcoming.sort(key=lambda r: r.get("scheduled_time", ""))
                        print(f"\n  Reminders: {len(reminders)} total, {len(upcoming)} upcoming")
                        for r in upcoming[:5]:
                            tlabel = reminder._type_label(r.get("task_type", ""))
                            st = r.get("scheduled_time", "")[:16].replace("T", " ")
                            print(f"    [{tlabel}] {st}  {r.get('text', '')[:50]}")
                except Exception as e:
                    print(f"\n  Refresh failed: {e}")

            elif ch.lower() == "h":
                print_header(cfg, client, locked)

            elif ch.lower() == "t":
                text = input("  Text Input: ").strip()
                if text:
                    try:
                        resp = client._http_post("/api/chat/send", json={
                            "message": text,
                            "chat_id": client.chat_id,
                            "chat_name": "minimal",
                            "tts_enabled": False,
                        })
                        if resp.status_code == 200:
                            reply = resp.json().get("reply", "")
                            print(f"\n  {reply}")
                    except Exception as e:
                        pass

            elif ch == "=":
                text = input("  Async Task: ").strip()
                if text:
                    task_id = client.send_async(text)
                    if task_id:
                        async_poller.add_task(task_id)

            elif ch.lower() == "n":
                client._volume = max(0.0, client._volume - 0.1)
                if client._channel:
                    client._channel.set_volume(client._volume)
                _play_beep(client, 400)
                print(f"\n  Volume: {client._volume:.0%}")

            elif ch.lower() == "m":
                client._volume = min(1.0, client._volume + 0.1)
                if client._channel:
                    client._channel.set_volume(client._volume)
                _play_beep(client, 800)
                print(f"\n  Volume: {client._volume:.0%}")

            elif ch.lower() in ("b", "c", "d", "e", "f"):
                pass

            else:
                buffer += ch

    except KeyboardInterrupt:
        pass
    finally:
        async_poller.stop()
        reminder.stop()
        if recorder.is_recording:
            recorder.stop_and_send()
        keyboard.stop()
        cfg["chat_id"] = client.chat_id
        save_config(cfg)
        print("\n  Goodbye")

if __name__ == "__main__":
    main()