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
            if text:
                print(f"\n  💬 {text}")
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

    def send_audio(self, audio_b64: str) -> Optional[str]:
        if not self.api_key:
            return None

        tts_queue_items: list[tuple[str, str]] = []
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

            reply_text = self._handle_sse_stream(resp, tts_queue_items)
            elapsed = time.perf_counter() - t0

            # 推送 TTS 项到播放队列，等待全部播完
            for item in tts_queue_items:
                self._tts_queue.put(item)
            self._tts_queue.join()

            # 显示耗时
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
                           tts_out: list[tuple[str, str]]) -> Optional[str]:
        reply = ""
        got_text = False

        for _evt_type, data in iter_sse_lines(resp):
            status = data.get("status", "")

            if status == "text_ready":
                reply = data.get("reply", "")
                got_text = True
                self.chat_id = data.get("chat_id", self.chat_id)

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
                if audio_b64 and HAS_AUDIO:
                    tts_out.append((text, audio_b64))
                print(f"\r  🎵 TTS [{idx}/{total}]", end="", flush=True)

            elif status == "completed":
                break
        return reply if got_text else None


class ReminderWatcher:
    """后台线程: 每 60s 检查 reminders.json，到期则通知后端并弹回提醒。"""

    def __init__(self, client: DSNClient):
        self._client = client
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_triggered: dict[str, dict] = {}

    def start(self):
        if self._running:
            return
        self._running = True
        self._sync()  # 启动时立即同步
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def sync_now(self):
        """手动触发同步"""
        self._sync()

    def skip_latest(self) -> bool:
        """跳过最近一条触发的提醒"""
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

    def _sync(self):
        """从后端拉取 PENDING 提醒到本地 JSON"""
        try:
            resp = requests.get(
                f"{self._client.base}/api/reminder/list",
                headers=self._client._headers(),
                timeout=10,
            )
            if resp.status_code != 200:
                return
            data = resp.json()
            remote = data.get("reminders", [])
            # 合并: 保留本地已标记 trigger_done 的，仅追加新的
            local = self._load_local()
            local_ids = {r["task_id"] for r in local}
            for rem in remote:
                if rem["task_id"] not in local_ids:
                    local.append({
                        "task_id": rem["task_id"],
                        "text": rem["text"],
                        "scheduled_time": rem["scheduled_time"],
                        "task_type": rem["task_type"],
                        "interval_seconds": rem.get("interval_seconds", 0),
                    })
            self._save_local(local)
        except Exception:
            pass

    def _load_local(self) -> list[dict]:
        if REMINDER_FILE.exists():
            try:
                return json.loads(REMINDER_FILE.read_text(encoding="utf-8"))
            except Exception:
                return []
        return []

    def _save_local(self, reminders: list[dict]):
        TTS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            REMINDER_FILE.write_text(
                json.dumps(reminders, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _loop(self):
        while self._running:
            try:
                reminders = self._load_local()
                now = datetime.now()
                changed = False
                for r in reminders:
                    try:
                        st = datetime.fromisoformat(r["scheduled_time"])
                    except Exception:
                        continue
                    if st <= now:
                        self._trigger(r)
                        changed = True

                if changed:
                    # 移除已触发的
                    remaining = []
                    for r in reminders:
                        try:
                            st = datetime.fromisoformat(r["scheduled_time"])
                        except Exception:
                            remaining.append(r)
                            continue
                        if st > now:
                            remaining.append(r)
                    self._save_local(remaining)
            except Exception:
                pass
            time.sleep(60)

    def _trigger(self, reminder: dict):
        """向后端发送 done 请求，并通知用户"""
        task_id = reminder["task_id"]
        text = reminder.get("text", "") or "提醒时间到了"
        tlabel = self._type_label(reminder.get("task_type", ""))
        try:
            resp = requests.post(
                f"{self._client.base}/api/reminder/done",
                json={"task_id": task_id},
                headers=self._client._headers(),
                timeout=10,
            )
            if resp.status_code == 200:
                result = resp.json()
                if result.get("success"):
                    print(f"\n  ⏰ [{tlabel}] {text}")
                    _play_beep(self._client, 880)
                    self._last_triggered[task_id] = {"text": text, "type": tlabel}

                    if result.get("next_task_id"):
                        pass
                else:
                    print(f"\n  ⚠️ 提醒失败: {result.get('error', '')}")
        except Exception:
            pass

    @staticmethod
    def _type_label(task_type: str) -> str:
        labels = {
            "reminder": "提醒", "habit": "习惯", "countdown": "倒计时",
            "daily_plan": "每日计划", "periodic": "周期",
        }
        return labels.get(task_type, task_type)


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
    print("  [r]      Refresh reminders sync           ")
    print("  [h]      Show help                       ")
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
    reminder = ReminderWatcher(client)
    reminder.start()

    def on_sigint(sig, frame):
        if recorder.is_recording:
            recorder.stop_and_send()
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
                else:
                    reminder._sync()

            elif ch.lower() == "r":
                reminder.sync_now()
                reminders = reminder._load_local()
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
        reminder.stop()
        if recorder.is_recording:
            recorder.stop_and_send()
        keyboard.stop()
        cfg["chat_id"] = client.chat_id
        save_config(cfg)
        print("\n  Goodbye")

if __name__ == "__main__":
    main()