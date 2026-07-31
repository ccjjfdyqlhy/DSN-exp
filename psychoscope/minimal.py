
from __future__ import annotations

import argparse
import base64
import io
import json
import logging
import os
import queue
import re
import select
import signal
import struct
import sys
import threading
import time
import wave
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import requests

try:
    import vlc
    HAS_AUDIO = True
    # 全局 VLC 实例：哑界面 + 禁用键盘/鼠标抢占
    VLC_INSTANCE = vlc.Instance("--intf", "dummy", "--no-keyboard-events",
                                "--no-mouse-events", "--quiet")
except ImportError:
    vlc = None
    VLC_INSTANCE = None
    HAS_AUDIO = False
    print("[WARN] python-vlc not installed. pip install python-vlc")

try:
    from pvrecorder import PvRecorder
    HAS_PVRECORDER = True
except ImportError:
    HAS_PVRECORDER = False
    print("[WARN] pvrecorder missing. pip install pvrecorder")

try:
    import cv2
    HAS_CAMERA = True
except ImportError:
    cv2 = None
    HAS_CAMERA = False
    print("[WARN] opencv-python not installed. pip install opencv-python (本地摄像头需要)")

CAMERA_DEVICE_ID = int(os.environ.get("DSN_CAMERA_DEVICE_ID", "0"))

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

# ── 日志：只写文件，不写终端 ──

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

    return logging.getLogger("minimal")

log = setup_logging()

if HAS_AUDIO:
    log.info("VLC 就绪")


# ════════════════════════════════════════════════════════════════
# Terminal 管理：原始模式上下文管理器 + 按键读取 + 行输入
# ════════════════════════════════════════════════════════════════

class TerminalState:
    """保存终端原始模式状态，保证退出时恢复。"""
    def __init__(self):
        self.fd = None
        self.old_attr = None
        self._is_windows = os.name == "nt"

    def enter_raw(self):
        if self._is_windows:
            self._enter_windows()
        else:
            self._enter_unix()

    def exit_raw(self):
        if self._is_windows:
            self._exit_windows()
        else:
            self._exit_unix()

    def _enter_unix(self):
        import termios, tty
        self.fd = sys.stdin.fileno()
        self.old_attr = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        self.raw_attr = termios.tcgetattr(self.fd)  # 保存 setcbreak 后的完整属性

    def _exit_unix(self):
        import termios
        if self.old_attr is not None:
            try:
                termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old_attr)
            except Exception:
                logging.getLogger(__name__).warning("Set operation failed", exc_info=True)
        self.old_attr = None

    def _enter_windows(self):
        import msvcrt
        # Windows 下无需特殊设置，msvcrt.kbhit() + getch() 可用

    def _exit_windows(self):
        pass


_RAW_ATTRS = None
_RAW_FD = None

@contextmanager
def raw_mode():
    """上下文管理器：进入原始模式 → yield → 保证恢复。"""
    ts = TerminalState()
    global _RAW_ATTRS, _RAW_FD
    try:
        ts.enter_raw()
        _RAW_ATTRS = getattr(ts, 'raw_attr', None)
        _RAW_FD = ts.fd
        yield ts
    finally:
        _RAW_ATTRS = None
        _RAW_FD = None
        ts.exit_raw()


def _ensure_raw_mode():
    """完整恢复 setcbreak 后的终端属性（VLC 等可能破坏部分标志位）。"""
    if _RAW_ATTRS is not None and _RAW_FD is not None:
        try:
            import termios
            termios.tcsetattr(_RAW_FD, termios.TCSADRAIN, _RAW_ATTRS)
        except Exception:
            logging.getLogger(__name__).warning("Set operation failed", exc_info=True)


def read_key(timeout: float = 0.1) -> str | None:
    """非阻塞读一个按键，超时返回 None。"""
    if os.name == "nt":
        import msvcrt
        if msvcrt.kbhit():
            ch = msvcrt.getch()
            if ch == b'\xe0':
                ch = msvcrt.getch()
                return None
            try:
                return ch.decode("utf-8", errors="replace")
            except Exception:
                return None
        return None

    try:
        fd = sys.stdin.fileno()
        r, _, _ = select.select([fd], [], [], timeout)
        if r:
            raw = os.read(fd, 1)
            if not raw:
                return None
            return raw.decode("utf-8", errors="replace")
        return None
    except (OSError, ValueError, select.error):
        return None


def raw_input(prompt: str = "") -> str:
    """在原始终端模式下读取一行输入（支持退格，Enter 确认）。"""
    buf: list[str] = []
    if prompt:
        print(prompt, end="", flush=True)
    while True:
        ch = read_key(timeout=None)  # 阻塞读
        if ch is None:
            continue
        if ch == "\r" or ch == "\n":
            print()
            return "".join(buf)
        elif ch == "\x7f" or ch == "\b":  # 退格
            if buf:
                buf.pop()
                sys.stdout.write("\b \b")
                sys.stdout.flush()
        elif ch == "\x03":  # Ctrl+C
            raise KeyboardInterrupt
        elif ch == "\x04":  # Ctrl+D
            return "".join(buf)
        elif ch.isprintable() or ord(ch) >= 32:
            buf.append(ch)
            sys.stdout.write(ch)
            sys.stdout.flush()


# ════════════════════════════════════════════════════════════════
# MusicPlayer — 音乐播放器（独立于 TTS 的 VLC 播放）
# ════════════════════════════════════════════════════════════════

class MusicPlayer:
    def __init__(self, client: DSNClient, uid: int):
        self.client = client
        self.uid = uid
        self.playlist: list[dict] = []
        self.current_index = -1
        self.state: str = "stopped"
        self._volume = 0.7
        self._temp_files: list[str] = []
        self._running = False
        self._poll_thread: threading.Thread | None = None
        self._prev_volume = self._volume
        self._player = None
        if HAS_AUDIO and VLC_INSTANCE:
            self._player = VLC_INSTANCE.media_player_new()

    def load_playlist(self):
        try:
            resp = self.client._http_get(
                f"/api/music/list?uid={self.uid}", timeout=5
            )
            if resp.status_code == 200:
                self.playlist = resp.json().get("files", [])
        except Exception as e:
            log.warning("MusicPlayer: 刷新歌单失败 %s", e)

    def play_index(self, idx: int):
        if not (0 <= idx < len(self.playlist)):
            return
        self.stop()
        self.current_index = idx
        song = self.playlist[idx]
        url = f"{self.client.base}/api/music/play/{song['filename']}?uid={self.uid}"
        try:
            resp = requests.get(url, stream=True, timeout=10,
                                headers=self.client._headers())
            if resp.status_code != 200:
                log.warning("MusicPlayer: 下载失败 %d", resp.status_code)
                return
            import tempfile
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=song["filename"])
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    tmp.write(chunk)
            tmp.close()
            self._temp_files.append(tmp.name)
            if self._player:
                self._player.set_mrl(tmp.name)
                self._player.audio_set_volume(int(self._volume * 100))
                self._player.play()
            self.state = "playing"
            self._report_state()
        except Exception as e:
            log.warning("MusicPlayer: 播放失败 %s", e)

    def toggle(self):
        try:
            if self.state == "playing" and self._player:
                self._player.pause()
                self.state = "paused"
            elif self.state == "paused" and self._player:
                self._player.play()
                self.state = "playing"
            else:
                self.play_index(self.current_index if self.current_index >= 0 else 0)
        except Exception:
            log.warning("MusicPlayer.toggle: player error")
        self._report_state()

    def stop(self):
        try:
            if self._player:
                self._player.stop()
        except Exception:
            logging.getLogger(__name__).warning("Stop operation failed", exc_info=True)
        self.state = "stopped"
        self._report_state()

    def next(self):
        if not self.playlist:
            return
        idx = (self.current_index + 1) % len(self.playlist) if self.current_index >= 0 else 0
        self.play_index(idx)

    def prev(self):
        if not self.playlist:
            return
        idx = (self.current_index - 1) % len(self.playlist) if self.current_index >= 0 else len(self.playlist) - 1
        self.play_index(idx)

    def audio_set_volume(self, v: float):
        self._volume = max(0.0, min(1.0, v))
        try:
            if self._player:
                self._player.audio_set_volume(int(self._volume * 100))
        except Exception:
            logging.getLogger(__name__).warning("Set operation failed", exc_info=True)
        self._report_state()

    def duck(self):
        if self.state == "playing" and self._player:
            self._prev_volume = self._volume
            try:
                self._player.audio_set_volume(int(self._volume * 0.2 * 100))
            except Exception:
                logging.getLogger(__name__).warning("Set operation failed", exc_info=True)

    def unduck(self):
        if self.state == "playing" and self._player:
            try:
                self._player.audio_set_volume(int(self._prev_volume * 100))
            except Exception:
                logging.getLogger(__name__).warning("Set operation failed", exc_info=True)

    def start_poll(self):
        self._running = True
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def stop_poll(self):
        self._running = False
        if self._poll_thread:
            self._poll_thread.join(timeout=2)

    def cleanup(self):
        self.stop()
        self.stop_poll()
        if self._player:
            self._player.release()
            self._player = None
        for f in self._temp_files:
            try:
                os.unlink(f)
            except Exception:
                logging.getLogger(__name__).warning("Operation failed", exc_info=True)
        self._temp_files.clear()

    def _report_state(self):
        current = None
        if 0 <= self.current_index < len(self.playlist):
            current = {"filename": self.playlist[self.current_index]["filename"]}
        payload = {"state": self.state, "current": current, "volume": self._volume}
        try:
            self.client._http_post("/api/music/state", json=payload, timeout=2)
        except Exception:
            logging.getLogger(__name__).warning("Load/read operation failed", exc_info=True)

    def _poll_loop(self):
        import time as _time
        while self._running:
            _time.sleep(1.5)
            try:
                resp = self.client._http_get(
                    "/api/music/status?consume=1", timeout=3)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                cmd = data.get("pending_control")
                if not cmd:
                    continue
                action = cmd.get("action", "")
                value = cmd.get("value")
                log.info("MusicPlayer: 消费命令 action=%s value=%s", action, value)
                if action == "play" and value:
                    for i, s in enumerate(self.playlist):
                        if s["filename"] == value:
                            self.play_index(i)
                            break
                elif action == "next":
                    self.next()
                elif action == "prev":
                    self.prev()
                elif action == "pause":
                    if self.state == "playing":
                        self.toggle()
                elif action == "resume":
                    if self.state == "paused":
                        self.toggle()
                elif action == "stop":
                    self.stop()
                elif action == "volume" and value is not None:
                    self.audio_set_volume(float(value))
            except Exception:
                logging.getLogger(__name__).warning("Set operation failed", exc_info=True)


def _play_beep(client: DSNClient, freq: int = 600):
    if not HAS_AUDIO:
        return
    sr = 44100
    dur = 0.06
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    wave = np.sin(2 * np.pi * freq * t) * 0.3
    samples = np.clip(wave * 32767, -32768, 32767).astype(np.int16)
    import tempfile
    tmp_path = None
    try:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(samples.tobytes())
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        tmp_path = tmp.name
        tmp.write(buf.getvalue())
        tmp.close()
        p = VLC_INSTANCE.media_player_new() if VLC_INSTANCE else None
        if p:
            media = VLC_INSTANCE.media_new(tmp_path)
            p.set_media(media)
            p.play()
            time.sleep(dur + 0.1)
            p.stop()
            p.release()
    except Exception:
        logging.getLogger(__name__).warning("Resource release failed", exc_info=True)
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                logging.getLogger(__name__).warning("Operation failed", exc_info=True)


def raw_pcm_to_wav_b64(samples: np.ndarray, sr: int = SAMPLE_RATE) -> str:
    int_samples = np.clip(samples * 32767, -32768, 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(int_samples.tobytes())
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _capture_camera_frame(camera_id: int = CAMERA_DEVICE_ID) -> Optional[str]:
    """本地 cv2 抓一帧 → JPEG(q75) → base64 data URL。失败返回 None。

    产物格式与后端原 _observe_once/_capture_frame 完全一致
    ("data:image/jpeg;base64,...")，保证后端 VisionModel 管道零改动。
    """
    if not HAS_CAMERA:
        return None
    try:
        cap = cv2.VideoCapture(camera_id)
        if not cap.isOpened():
            log.warning("摄像头无法打开 (device_id=%s)", camera_id)
            return None
        ret, frame = cap.read()
        cap.release()
        if not ret:
            log.warning("摄像头读取画面失败")
            return None
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if not ok:
            log.warning("JPEG 编码失败")
            return None
        return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("utf-8")
    except Exception:
        log.warning("摄像头抓帧失败", exc_info=True)
        return None


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
                data = json.loads(data_str)
                status = data.get("status", "?")
                if status in ("line", "text_ready", "completed"):
                    log.info("[DEBUG_SSE] iter_sse_lines: 收到 status=%s, t=%.4f", status, time.perf_counter())
                yield event, data
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


# ════════════════════════════════════════════════════════════════
# DSNClient — API 客户端
# ════════════════════════════════════════════════════════════════

class DSNClient:
    def __init__(self, host: str, port: int):
        self.base = f"http://{host}:{port}"
        self.api_key: Optional[str] = None
        self.uid: int = 0
        self.chat_id: Optional[int] = None
        self.display_name: str = ""
        self._tts_queue: queue.Queue[tuple[str, str] | None] = queue.Queue()
        self._send_queue: queue.Queue[tuple[str, str] | None] = queue.Queue()
        self._volume = 1.0
        self.async_poller = None
        self._player: MusicPlayer | None = None
        self._tts_stop = threading.Event()
        self._sending = threading.Event()
        if HAS_AUDIO:
            self._tts_thread = threading.Thread(target=self._tts_worker, daemon=True)
            self._tts_thread.start()
        self._send_thread = threading.Thread(target=self._send_worker, daemon=True)
        self._send_thread.start()

    def stop_tts(self):
        self._tts_stop.set()
        while not self._tts_queue.empty():
            try:
                self._tts_queue.get_nowait()
                self._tts_queue.task_done()
            except queue.Empty:
                break

    def _tts_worker(self):
        while True:
            item = self._tts_queue.get()
            if item is None:
                self._tts_queue.task_done()
                continue
            text, b64 = item
            log.info("[DEBUG_CLI] _tts_worker: 开始播放, 文本[:40]=%r, queue_size=%d, t=%.4f", text[:40], self._tts_queue.qsize(), time.perf_counter())
            ducked = False
            tmp_path = None
            try:
                self._tts_stop.clear()
                raw = base64.b64decode(b64)
                if self._player:
                    self._player.duck()
                    ducked = True

                import tempfile
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
                tmp_path = tmp.name
                tmp.write(raw)
                tmp.close()

                p = VLC_INSTANCE.media_player_new() if VLC_INSTANCE else None
                if not p:
                    continue
                media = VLC_INSTANCE.media_new(tmp_path)
                p.set_media(media)
                p.audio_set_volume(100)
                media = p.get_media()
                media.parse()
                duration_ms = media.get_duration()
                if duration_ms > 0:
                    p.play()
                    log.info("[DEBUG_CLI] _tts_worker: VLC 开始播放, duration=%.1fms, t=%.4f", duration_ms, time.perf_counter())
                    played = 0.0
                    step = 0.3
                    total = duration_ms / 1000.0 + 0.2
                    while played < total:
                        if self._tts_stop.is_set():
                            log.info("[DEBUG_CLI] _tts_worker: 被 stop 信号中断, t=%.4f", time.perf_counter())
                            break
                        time.sleep(step)
                        played += step
                p.stop()
                p.release()
                log.info("[DEBUG_CLI] _tts_worker: 播放结束, t=%.4f", time.perf_counter())
            except Exception as e:
                log.error(f"[DEBUG_CLI] TTS playback error: {e}")
            finally:
                if tmp_path:
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        logging.getLogger(__name__).warning("Operation failed", exc_info=True)
            if ducked:
                self._player.unduck()
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
            logging.getLogger(__name__).warning("Parse operation failed", exc_info=True)

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
        log.info("[DEBUG_CLI] send_audio: 开始 SSE 请求, t=%.4f", t0)

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

            reply_text, t_first_audio = self._handle_sse_stream(resp, self._tts_queue, t0, async_poller=self.async_poller)
            elapsed = time.perf_counter() - t0
            log.info("[DEBUG_CLI] send_audio: SSE 流结束, t=%.4f, 总耗时=%.1fs", time.perf_counter(), elapsed)

            if t_first_audio is not None:
                first_audio_ms = (t_first_audio - t0) * 1000
                print(f"\n  \U0001f50a 首条音频: {first_audio_ms:.0f}ms")

            minutes = int(elapsed) // 60
            seconds = int(elapsed) % 60
            if minutes > 0:
                print(f"\n  \u23f1  {minutes}分{seconds}秒")
            else:
                print(f"\n  \u23f1  {seconds}秒")

            return reply_text
        except Exception as e:
            log.error("Audio send failed: %s", e)
            return None

    def send_text(self, message: str) -> Optional[str]:
        if not self.api_key or not message.strip():
            return None

        t0 = time.perf_counter()
        log.info("[DEBUG_CLI] send_text: 开始 SSE 请求, t=%.4f", t0)

        try:
            resp = self._http_post_stream(
                "/api/chat/stream_send",
                json={
                    "message": message,
                    "chat_id": self.chat_id,
                    "chat_name": "minimal",
                    "tts_enabled": True,
                    "is_asr_input": False,
                },
            )
            if resp.status_code != 200:
                log.warning("Text send HTTP %d: %s", resp.status_code, resp.text[:200])
                return None

            reply_text, t_first_audio = self._handle_sse_stream(
                resp, self._tts_queue, t0, async_poller=self.async_poller)
            elapsed = time.perf_counter() - t0
            log.info("[DEBUG_CLI] send_text: SSE 流结束, 总耗时=%.1fs", elapsed)

            if t_first_audio is not None:
                first_audio_ms = (t_first_audio - t0) * 1000
                print(f"\n  \U0001f50a 首条音频: {first_audio_ms:.0f}ms")

            return reply_text
        except Exception as e:
            log.error("Text send failed: %s", e)
            return None

    @property
    def is_sending(self) -> bool:
        return self._sending.is_set()

    def send_audio_async(self, audio_b64: str):
        self._send_queue.put(("audio", audio_b64))

    def send_text_async(self, message: str):
        self._send_queue.put(("text", message))

    def _send_worker(self):
        while True:
            item = self._send_queue.get()
            if item is None:
                self._send_queue.task_done()
                continue
            kind, payload = item
            self._sending.set()
            try:
                if kind == "audio":
                    self.send_audio(payload)
                elif kind == "text":
                    self.send_text(payload)
            except Exception:
                log.exception("Send worker error")
            finally:
                self._sending.clear()
                self._send_queue.task_done()

    def _handle_sse_stream(self, resp: requests.Response,
                           tts_queue: queue.Queue | None = None,
                           t_start: float = None,
                           async_poller=None) -> tuple[Optional[str], float]:
        reply = ""
        got_text = False
        t_first_audio = None
        _last_event = time.time()
        _SSE_WATCHDOG = 60  # 秒，距上次事件超过此值强制退出

        for _evt_type, data in iter_sse_lines(resp):
            # 看门狗：太久没收到事件 → 放弃
            if time.time() - _last_event > _SSE_WATCHDOG:
                log.warning("SSE 看门狗触发: %d 秒无事件，强制退出", _SSE_WATCHDOG)
                break
            _last_event = time.time()
            status = data.get("status", "")

            if status == "async_task":
                task_id = data.get("task_id", "")
                if task_id and async_poller:
                    async_poller.add_task(task_id)
                continue

            if status == "instant_reply":
                reply = data.get("reply", "")
                if reply:
                    print(f"\n  \U0001f4ac {reply}")
                audio_b64 = data.get("audio_b64", "")
                if audio_b64 and HAS_AUDIO and tts_queue is not None:
                    if t_first_audio is None:
                        t_first_audio = time.perf_counter()
                    tts_queue.put((reply, audio_b64))
                continue

            if status == "main_started":
                tid = data.get("task_id", "")
                desc = data.get("description", "")
                print(f"\n  \u2699\ufe0f 主模型启动 [{tid[:8]}] {desc}")
                continue

            if status == "progress":
                text = data.get("text", "")
                tid = data.get("task_id", "")
                if text:
                    print(f"\n  \U0001f504 [{tid[:8]}] {text}")
                audio_b64 = data.get("audio_b64", "")
                if audio_b64 and HAS_AUDIO and tts_queue is not None:
                    tts_queue.put((text, audio_b64))
                continue

            if status == "main_reply":
                reply = data.get("reply", "")
                tid = data.get("task_id", "")
                got_text = True
                self.chat_id = data.get("chat_id", self.chat_id)
                if reply:
                    print(f"\n  \U0001f4ac [{tid[:8]}] {reply}")
                audio_b64 = data.get("audio_b64", "")
                if audio_b64 and HAS_AUDIO and tts_queue is not None:
                    tts_queue.put((reply, audio_b64))
                continue

            if status == "cancelled":
                tid = data.get("task_id", "")
                print(f"\n  \u26d4 任务已取消 [{tid[:8]}]")
                continue

            if status == "heartbeat":
                continue

            if status == "text_ready":
                reply = data.get("reply", "")
                got_text = True
                self.chat_id = data.get("chat_id", self.chat_id)
                log.info("[DEBUG_CLI] text_ready 收到, reply[:60]=%r, t=%.4f", reply[:60], time.perf_counter())
                if reply:
                    print(f"\n  \U0001f4ac {reply}")

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
                log.info("[DEBUG_CLI] line %d/%d 收到, 推入 tts_queue, queue_size=%d, t=%.4f",
                         idx, total, tts_queue.qsize() if tts_queue else -1, time.perf_counter())
                if audio_b64 and HAS_AUDIO and tts_queue is not None:
                    if t_first_audio is None:
                        t_first_audio = time.perf_counter()
                    tts_queue.put((text, audio_b64))
                print(f"\r  \U0001f3b5 TTS [{idx}/{total}]", end="", flush=True)

            elif status == "completed":
                log.info("[DEBUG_CLI] completed 收到, t=%.4f", time.perf_counter())
                break
        return reply if got_text else None, t_first_audio


# ════════════════════════════════════════════════════════════════
# AsyncTaskPoller — 异步任务轮询
# ════════════════════════════════════════════════════════════════

class AsyncTaskPoller:
    ASYNC_POLL_INTERVAL = 8
    ASYNC_POLL_TIMEOUT = 600

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
                        if reply:
                            print(f"\n  \U0001f4ac {reply}")
                        if audio_b64 and HAS_AUDIO and self._tts_queue is not None:
                            self._tts_queue.put((reply, audio_b64))
                        self._client.chat_id = data.get("chat_id", self._client.chat_id)
                        print(f"  \u2705 异步任务完成 ({task_id[:10]}...)")

                    elif status == "failed":
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
# VisionObserver — 周期性主动视觉：本地 cv2 抓帧 → POST /api/vision/observation
# ════════════════════════════════════════════════════════════════

class VisionObserver:
    """每 interval 秒本地抓帧推送后端（后端跑 VisionModel + 场景变化 + 通知）。

    配置由 heartbeat 响应的 active_vision 字段自配置（configure→start）。
    """

    def __init__(self, client: DSNClient):
        self._client = client
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._enabled = False
        self._interval = 300

    def configure(self, enabled: bool, interval: int) -> bool:
        """更新配置；返回配置是否发生变化。"""
        enabled = bool(enabled)
        interval = max(30, int(interval or 300))
        changed = (enabled != self._enabled) or (interval != self._interval)
        self._enabled = enabled
        self._interval = interval
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
            frame = _capture_camera_frame()
            if frame is None:
                log.warning("VisionObserver: 抓帧失败，跳过本轮")
                continue
            try:
                self._client._http_post("/api/vision/observation", json={
                    "image_data": frame,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }, timeout=30)
                log.info("VisionObserver: 帧已推送后端")
            except Exception:
                log.warning("VisionObserver: 推送后端失败", exc_info=True)


# ════════════════════════════════════════════════════════════════
# HeartbeatPoller — 心跳 + 提醒轮询
# ════════════════════════════════════════════════════════════════

class HeartbeatPoller:
    HEARTBEAT_INTERVAL = 5
    HEARTBEAT_TIMEOUT = 30

    def __init__(self, client: "DSNClient", tts_queue: queue.Queue,
                 vision_observer: "VisionObserver | None" = None):
        self._client = client
        self._tts_queue = tts_queue
        self._vision_observer = vision_observer
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
            resp = requests.post(
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
        while self._running:
            try:
                self._beat()
            except Exception as e:
                log.warning("HeartbeatPoller 心跳异常: %s", e)
            for _ in range(self.HEARTBEAT_INTERVAL):
                if not self._running:
                    break
                time.sleep(1)

    def _beat(self):
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

        # ── 主动视觉：用 heartbeat 下发的配置自配置 VisionObserver ──
        av = data.get("active_vision")
        if av and self._vision_observer is not None:
            if self._vision_observer.configure(
                    av.get("enabled", False), av.get("interval", 300)):
                log.info("VisionObserver 配置更新: enabled=%s interval=%s",
                         av.get("enabled"), av.get("interval"))
                self._vision_observer.start()  # 已 start 则 no-op

        # ── 按需视觉请求：抓一帧回传后端，唤醒阻塞中的 look_around ──
        vr = data.get("vision_request")
        if vr:
            rid = vr.get("request_id", "")
            if rid:
                log.info("收到 on-demand 视觉请求: %s", rid)
                frame = _capture_camera_frame()
                if frame:
                    try:
                        self._client._http_post("/api/vision/frame", json={
                            "request_id": rid,
                            "image_data": frame,
                        }, timeout=30)
                        log.info("视觉帧已回传: %s", rid)
                    except Exception:
                        log.warning("视觉帧回传失败: %s", rid, exc_info=True)
                else:
                    log.warning("无法抓帧，视觉请求 %s 将在后端超时兜底", rid)

        if not data.get("has_notification"):
            return

        reply = data.get("reply", "") or ""
        audio_b64 = data.get("audio_b64", "") or ""
        task_id = data.get("task_id", "")
        notification_id = data.get("notification_id")
        task_type = data.get("task_type", "reminder")
        chat_id = data.get("chat_id")
        tts_error = data.get("tts_error", "")

        tlabel = self._type_label(task_type)

        if chat_id:
            self._client.chat_id = chat_id

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

    @staticmethod
    def _type_label(task_type: str) -> str:
        labels = {
            "reminder": "提醒", "habit": "习惯", "countdown": "倒计时",
            "daily_plan": "每日计划", "periodic": "周期", "alarm": "闹钟",
        }
        return labels.get(task_type, task_type)

ReminderWatcher = HeartbeatPoller


# ════════════════════════════════════════════════════════════════
# VoiceRecorder — 录音器
# ════════════════════════════════════════════════════════════════

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

    @property
    def has_frames(self) -> bool:
        return bool(self._frames) and self._sent_frames is not self._frames

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
        self._recording = False
        if not self._frames:
            return

        self._stop_event.set()

        if self._recorder:
            try:
                self._recorder.stop()
            except Exception:
                logging.getLogger(__name__).warning("Stop operation failed", exc_info=True)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)

        if self._recorder:
            try:
                self._recorder.delete()
            except Exception:
                logging.getLogger(__name__).warning("Delete/remove operation failed", exc_info=True)
            self._recorder = None

        dur = time.time() - self._start_time

        if not self._frames or dur < 0.5:
            print("  Too short, ignored")
            return

        audio = np.concatenate(self._frames)
        b64 = raw_pcm_to_wav_b64(audio)
        self._sent_frames = self._frames
        self.client.send_audio_async(b64)

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
            logging.getLogger(__name__).warning("Operation failed", exc_info=True)
        finally:
            try:
                self._recorder.stop()
            except Exception:
                logging.getLogger(__name__).warning("Stop operation failed", exc_info=True)


# ════════════════════════════════════════════════════════════════
# 界面输出函数
# ════════════════════════════════════════════════════════════════

def print_header(cfg: dict, client: DSNClient = None, locked: bool = False):
    print("=" * 43)
    print("        DSN-exp  Minimal Client")
    print("=" * 43)
    uid = cfg.get("uid", "?")
    name = cfg.get("display_name", "?")
    host = cfg.get("host", f"{DEFAULT_HOST}:{DEFAULT_PORT}")
    print(f"  Backend : {host}")
    print(f"  User    : uid={uid} ({name})")
    if locked:
        print("  \U0001f512 Panel locked")
    print("=" * 43)
    print("  [Enter] toggle record   [p] personality")
    print("  [a x2]  lock panel      [i] system info")
    print("  [b x2]  music mode      [h] help")
    print("  [t]     text input      [s] standby")
    print("  [=]     async task      [k] skip reminder")
    print("  [r]     heartbeat       [f] silence alarm")
    print("  [l]     alarm status    [q/Ctrl+C] quit")
    print("  [n/m]   vol-/vol+ (music mode)")
    print("  [d/e/f] prev/toggle/next (music mode)")
    print("=" * 43)
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
        resp = client._http_post("/api/maintenance/toggle_standby", timeout=10)
        state = resp.json().get("state", "?")
        print(f"  Server State: {state}")
    except Exception as e:
        print(f"  Error: {e}")


def print_system_info(client: DSNClient):
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
        logging.getLogger(__name__).warning("Operation failed", exc_info=True)

    try:
        resp = client._http_get("/api/todo/list")
        if resp.status_code == 200:
            todos = resp.json().get("todos", [])
            active = [t for t in todos if t.get("status") == "pending"]
            print(f"  Todos    : {len(active)} pending / {len(todos)} total")
    except Exception:
        logging.getLogger(__name__).warning("Operation failed", exc_info=True)

    try:
        resp = client._http_get("/api/reminder/list")
        if resp.status_code == 200:
            reminders = resp.json().get("reminders", [])
            if reminders:
                print(f"  Reminders: {len(reminders)} pending")
                for r in reminders[:5]:
                    tlabel = HeartbeatPoller._type_label(r.get("task_type", ""))
                    st = r.get("scheduled_time", "")[:16].replace("T", " ")
                    print(f"    [{tlabel}] {st}  {r.get('text', '')[:40]}")
    except Exception:
        logging.getLogger(__name__).warning("Get operation failed", exc_info=True)

    print(f"  ---------------------\n")


# ════════════════════════════════════════════════════════════════
# main — 单线程事件循环，所有输入走原始键盘
# ════════════════════════════════════════════════════════════════

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

    # 预处理 --pairing：尝试自动认证，否则进入交互式注册
    if not pairing_code:
        cfg_file = load_config()
        if cfg_file.get("api_key"):
            pairing_code = "cached"

    while True:
        ok = client.authenticate(code=pairing_code, name=display_name)
        if ok:
            break

        print("\n  ========================================")
        print("            DSN-exp Registration")
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

    # 初始化所有组件
    recorder = VoiceRecorder(client)
    vision_obs = VisionObserver(client)
    reminder = HeartbeatPoller(client, client._tts_queue, vision_observer=vision_obs)
    reminder.start()
    async_poller = AsyncTaskPoller(client, client._tts_queue)
    async_poller.start()
    client.async_poller = async_poller

    player = MusicPlayer(client, cfg.get("uid", 1))
    player.start_poll()
    client._player = player

    # 状态变量
    running = True
    locked = False
    _music_mode = False
    _music_was_playing = False
    _recording_session = False
    _auto_stop_ts = 0.0
    _last_a_ts = 0.0
    _last_b_ts = 0.0
    _DOUBLE_CLICK_WINDOW = 0.5

    print_header(cfg, client)
    print("  Ready! Press Enter to toggle recording...\n")

    def _sigint(sig, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGINT, _sigint)

    # ── 主事件循环 ──
    with raw_mode():
        try:
            while running:
                ch = read_key(timeout=0.1)

                # ── 静音/超时自动停止：capture loop 已将 _recording 置为 False ──
                if _recording_session and not recorder.is_recording and recorder.has_frames:
                    _ensure_raw_mode()
                    print("\n  (auto-stopped by silence)")
                    recorder.stop_and_send()
                    print()
                    _ensure_raw_mode()
                    _recording_session = False
                    _auto_stop_ts = time.time()
                    if _music_was_playing and player.state == "paused":
                        player.toggle()
                    _music_was_playing = False

                if ch is None:
                    continue

                # ── 双击 'a' 锁定/解锁 ──
                if ch.lower() == "a":
                    now = time.time()
                    if now - _last_a_ts < _DOUBLE_CLICK_WINDOW:
                        locked = not locked
                        if locked:
                            if _recording_session:
                                recorder.stop_and_send()
                                _recording_session = False
                                if _music_was_playing and player.state == "paused":
                                    player.toggle()
                                _music_was_playing = False
                            print("\n  \U0001f512 Panel locked")
                        else:
                            print("\n  \U0001f513 Panel unlocked")
                        _last_a_ts = 0.0
                        continue
                    _last_a_ts = now
                    continue

                # ── 双击 'b' 切换音乐模式 ──
                if ch.lower() == "b":
                    now = time.time()
                    if now - _last_b_ts < _DOUBLE_CLICK_WINDOW:
                        _music_mode = not _music_mode
                        if _music_mode:
                            player.load_playlist()
                            _play_beep(client, 880)
                            print("\n  \u266a Music Mode")
                        else:
                            print("\n  Exited Music Mode")
                            _play_beep(client, 440)
                        _last_b_ts = 0.0
                        continue
                    _last_b_ts = now
                    continue

                # ── 锁定时忽略除 'a' 外所有输入 ──
                if locked:
                    continue

                # ── Enter: toggle 开始/停止录音 ──
                if ch in ("\r", "\n"):
                    if client.is_sending:
                        print("\n  \u23f3 上一轮对话还在发送中，请稍候...")
                        continue
                    if not _recording_session:
                        # 刚自动停止则忽略本次 Enter，避免误启动新录音
                        if time.time() - _auto_stop_ts < 1.0:
                            continue
                        _music_was_playing = _music_mode and player.state == "playing"
                        if _music_was_playing:
                            player.toggle()
                        print("\n  Recording... (press Enter to stop)")
                        recorder.start()
                        _recording_session = True
                    else:
                        recorder.stop_and_send()
                        _ensure_raw_mode()
                        print()
                        _ensure_raw_mode()
                        _recording_session = False
                        if _music_was_playing and player.state == "paused":
                            player.toggle()
                        _music_was_playing = False

                # ── q / Ctrl+C: 退出 ──
                elif ch.lower() == "q":
                    if _recording_session:
                        recorder.stop_and_send()
                        _recording_session = False
                    break

                # ── p: 人格状态 ──
                elif ch.lower() == "p":
                    print_personality(client)

                # ── s: standby ──
                elif ch.lower() == "s":
                    toggle_standby(client)

                # ── i: 系统信息 ──
                elif ch.lower() == "i":
                    print_system_info(client)

                # ── k: 跳过提醒 ──
                elif ch.lower() == "k":
                    if not reminder.skip_latest():
                        print("\n  No recent reminder to skip")

                # ── r: 手动心跳 ──
                elif ch.lower() == "r":
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
                        log.warning("Reminder list failed: %s", e)

                    try:
                        resp = client._http_get("/api/alarms")
                        if resp.status_code == 200:
                            alarms = resp.json().get("alarms", [])
                            if alarms:
                                print(f"  Alarms: {len(alarms)} total")
                                for a in alarms:
                                    wd = ",".join(a["days"]) if a["days"] else "每天"
                                    status = "开" if a["enabled"] else "关"
                                    print(f"    \u23f0 {a['time']} [{wd}] {a['message'][:40]} ({status})")
                        resp2 = client._http_get("/api/alarms/now")
                        if resp2.status_code == 200:
                            nxt = resp2.json().get("next_alarm")
                            if nxt:
                                cd = nxt.get("countdown", "?")
                                icon = "\u26a1已触发" if nxt.get("fired") else "\U0001f514等待"
                                print(f"    {icon} 下次: {nxt['date']}({nxt['weekday']}) {nxt['time']} 剩{cd}")
                    except Exception as e:
                        log.warning("Alarm list failed: %s", e)

                # ── h: 帮助 ──
                elif ch.lower() == "h":
                    print_header(cfg, client, locked)

                # ── f: 静音闹钟 ──
                elif ch.lower() == "f":
                    last_ids = list(reminder._last_triggered.keys())
                    dismissed = False
                    for tid in reversed(last_ids):
                        if tid.startswith("alarm_"):
                            alarm_id = tid[6:]
                            try:
                                resp = client._http_post(f"/api/alarms/{alarm_id}/dismiss")
                                if resp.status_code == 200:
                                    print(f"\n  \U0001f515 闹钟 {alarm_id} 已静音")
                                    dismissed = True
                                    break
                            except Exception:
                                logging.getLogger(__name__).warning("Operation failed", exc_info=True)
                    if not dismissed:
                        try:
                            resp = client._http_get("/api/alarms/now")
                            if resp.status_code == 200:
                                nxt = resp.json().get("next_alarm")
                                if nxt and nxt.get("fired"):
                                    resp2 = client._http_post(f"/api/alarms/{nxt['id']}/dismiss")
                                    if resp2.status_code == 200:
                                        print(f"\n  \U0001f515 闹钟 {nxt['id']} 已静音")
                                        dismissed = True
                        except Exception:
                            logging.getLogger(__name__).warning("Operation failed", exc_info=True)
                    if not dismissed:
                        print(f"\n  \U0001f515 无活跃闹钟可静音")
                    client.stop_tts()

                # ── l: 闹钟状态 ──
                elif ch.lower() == "l":
                    try:
                        resp = client._http_get("/api/alarms")
                        if resp.status_code == 200:
                            alarms = resp.json().get("alarms", [])
                            print(f"\n  \u23f0 Alarms: {len(alarms)} total")
                            for a in alarms:
                                wd = ",".join(a["days"]) if a["days"] else "每天"
                                status = "\u2705" if a["enabled"] else "\u26d4"
                                snd = f" \U0001f50a{a['sound']}" if a.get("sound") else ""
                                print(f"    {status} {a['id']} {a['time']} [{wd}] {a['message']}{snd}")
                        resp2 = client._http_get("/api/alarms/now")
                        if resp2.status_code == 200:
                            nxt = resp2.json().get("next_alarm")
                            if nxt:
                                cd = nxt.get("countdown", "?")
                                icon = "\u26a1" if nxt.get("fired") else "\U0001f514"
                                print(f"    {icon} 下次: {nxt['date']}({nxt['weekday']}) {nxt['time']} 剩{cd}")
                            else:
                                print(f"    \u23f0 无待触发闹钟")
                        resp3 = client._http_get("/api/alarms/status")
                        if resp3.status_code == 200:
                            st = resp3.json()
                            print(f"    \U0001f4ca 今日触发: {st.get('fired_today', 0)} 次")
                    except Exception as e:
                        print(f"\n  Alarm status failed: {e}")

                # ── t: 文本输入（流式 SSE + TTS）──
                elif ch.lower() == "t":
                    text = raw_input("  Text Input: ").strip()
                    if text:
                        if client.is_sending:
                            print("\n  \u23f3 上一轮对话还在发送中，请稍候...")
                        else:
                            client.send_text_async(text)

                # ── =: 异步任务 ──
                elif ch == "=":
                    text = raw_input("  Async Task: ").strip()
                    if text:
                        task_id = client.send_async(text)
                        if task_id:
                            async_poller.add_task(task_id)

                # ── 音乐模式音量 ──
                elif ch.lower() == "n":
                    if _music_mode:
                        v = max(0.0, player._volume - 0.1)
                        player.audio_set_volume(v)
                        _play_beep(client, 400)
                        print(f"\n  \u266a Vol: {v:.0%}")

                elif ch.lower() == "m":
                    if _music_mode:
                        v = min(1.0, player._volume + 0.1)
                        player.audio_set_volume(v)
                        _play_beep(client, 800)
                        print(f"\n  \u266a Vol: {v:.0%}")

                # ── 音乐模式控制 ──
                elif _music_mode and ch.lower() == "d":
                    player.prev()
                    _play_beep(client, 600)
                    print(f"\n  \u266a Prev \u2192 {player.current_index + 1}/{len(player.playlist)}")
                elif _music_mode and ch.lower() == "e":
                    player.toggle()
                    _play_beep(client, 800 if player.state == "playing" else 400)
                    print(f"\n  \u266a {'▶' if player.state == 'playing' else '⏸'} {player.state}")
                elif _music_mode and ch.lower() == "f":
                    player.next()
                    _play_beep(client, 600)
                    print(f"\n  \u266a Next \u2192 {player.current_index + 1}/{len(player.playlist)}")
                elif ch.lower() in ("b", "c", "d", "e", "f"):
                    pass

        except KeyboardInterrupt:
            pass
        finally:
            vision_obs.stop()
            player.cleanup()
            async_poller.stop()
            reminder.stop()
            if _recording_session and recorder.has_frames:
                recorder.stop_and_send()
            cfg["chat_id"] = client.chat_id
            save_config(cfg)
            print("\n  Goodbye")


if __name__ == "__main__":
    main()
