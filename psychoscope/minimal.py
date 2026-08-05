
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
from concurrent.futures import ThreadPoolExecutor
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
    # 抑制 OpenCV 摄像头枚举/抓帧时的控制台噪音（DSHOW/MSMF 警告、obsensor 错误刷屏）
    try:
        cv2.setLogLevel(0)  # 0 = LOG_LEVEL_SILENT
    except Exception:
        pass
except ImportError:
    cv2 = None
    HAS_CAMERA = False
    print("[WARN] opencv-python not installed. pip install opencv-python (本地摄像头需要)")

CAMERA_DEVICE_ID = int(os.environ.get("DSN_CAMERA_DEVICE_ID", "0"))

# 摄像头枚举整体超时（秒）——cv2 打开部分设备可能阻塞，超时后放弃剩余探测
ENUM_TIMEOUT = 5.0

# 逻辑名 → 设备索引的映射（可被环境变量覆盖，格式: cam0=0,cam1=2）
# 未配置时按枚举顺序自动分配 cam0, cam1, ...
_CAMERA_NAME_TO_INDEX: dict[str, int] = {}
_CAMERA_INDEX_TO_NAME: dict[int, str] = {}
_CAMERA_BACKEND: dict[int, int] = {}   # 设备索引 → 最佳 cv2 后端
_CAMERA_SCAN_DONE = False
_CAMERA_SCAN_LOCK = threading.Lock()


def _parse_camera_map(raw: str) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, idx = part.split("=", 1)
        try:
            mapping[name.strip()] = int(idx.strip())
        except ValueError:
            continue
    return mapping


def _enumerate_cameras(max_probe: int = 8) -> list[dict]:
    """枚举本机摄像头，返回 [{index, name, logical_name}]。
    通过尝试打开 cv2 设备判断可用性；探测上限 max_probe。
    整体有超时保护：cv2.VideoCapture 在部分驱动上可能长时间阻塞，
    在独立线程中执行并限定上限（ENUM_TIMEOUT 秒）。
    线程安全：并发调用时串行扫描；只有扫描完整完成且找到摄像头时才缓存结果，
    空/超时结果不缓存，下次调用会重新扫描。
    """
    global _CAMERA_NAME_TO_INDEX, _CAMERA_INDEX_TO_NAME, _CAMERA_SCAN_DONE
    if not HAS_CAMERA:
        return []
    with _CAMERA_SCAN_LOCK:
        if _CAMERA_SCAN_DONE:
            return [{"index": i, "name": n, "logical_name": nm}
                    for i, nm in sorted(_CAMERA_INDEX_TO_NAME.items())
                    for n in [f"cam{i}"]]

        result_holder: list = []
        done = threading.Event()

        def _scan():
            try:
                result_holder.extend(_scan_devices(max_probe))
            except Exception:
                log.warning("摄像头扫描异常", exc_info=True)
            finally:
                done.set()

        t = threading.Thread(target=_scan, daemon=True, name="cam-scan")
        t.start()
        scan_completed = done.wait(timeout=ENUM_TIMEOUT)
        devices = list(result_holder)

        env_map = _parse_camera_map(os.environ.get("DSN_CAMERA_MAP", ""))

        # 分配逻辑名：优先 env 映射，其余按顺序 cam0, cam1...
        used_names = set()
        _CAMERA_NAME_TO_INDEX = {}
        _CAMERA_INDEX_TO_NAME = {}
        _CAMERA_BACKEND.clear()
        for dev in devices:
            idx = dev["index"]
            logical = None
            for nm, mapped_idx in env_map.items():
                if mapped_idx == idx and nm not in used_names:
                    logical = nm
                    break
            if logical is None:
                i = 0
                while f"cam{i}" in used_names:
                    i += 1
                logical = f"cam{i}"
            used_names.add(logical)
            dev["logical_name"] = logical
            _CAMERA_NAME_TO_INDEX[logical] = idx
            _CAMERA_INDEX_TO_NAME[idx] = logical
            if dev.get("backend"):
                _CAMERA_BACKEND[idx] = dev["backend"]

        # 仅当扫描完整完成且找到设备时才缓存；否则留待下次重试
        if scan_completed and devices:
            _CAMERA_SCAN_DONE = True
        if devices:
            log.info("枚举到 %d 个摄像头: %s",
                     len(devices),
                     ", ".join(f"{d['logical_name']}=device{d['index']}" for d in devices))
        else:
            log.warning("本次扫描未检测到可用摄像头（completed=%s）", scan_completed)
        return devices


def _scan_devices(max_probe: int, backends: list | None = None) -> list[dict]:
    """在子线程中执行的实际设备探测（cv2 打开可能阻塞）。
    记录每个 index 的最佳可用后端，抓帧时复用同一后端（关键：枚举与抓帧后端不一致
    会导致 Windows 上 DSHOW/MSMF 冲突，出现 cam 打不开或抓帧失败）。
    :param backends: 可显式指定后端列表（测试用）；默认按平台推断。
    """
    if backends is None:
        backends = _default_backends()
    elif isinstance(backends, (list, tuple)):
        backends = list(backends)

    devices = []
    for idx in range(max_probe):
        for backend in backends:
            try:
                if backend:
                    cap = cv2.VideoCapture(idx, backend)
                else:
                    cap = cv2.VideoCapture(idx)
                opened = cap.isOpened()
                if opened:
                    devices.append({"index": idx, "name": f"cam{idx}", "backend": backend})
                    cap.release()
                    break
                try:
                    cap.release()
                except Exception:
                    pass
            except Exception:
                continue
    return devices


def _default_backends() -> list:
    """按平台返回默认的 cv2 摄像头后端候选列表。"""
    if sys.platform.startswith("linux"):
        return [getattr(cv2, "CAP_V4L2", 0), getattr(cv2, "CAP_FFMPEG", 0), 0]
    if sys.platform == "darwin":
        return [getattr(cv2, "CAP_AVFOUNDATION", 0), 0]
    if os.name == "nt":
        # DSHOW 优先，其次 MSMF，最后默认——部分摄像头只在特定后端可开
        return [getattr(cv2, "CAP_DSHOW", 0), getattr(cv2, "CAP_MSMF", 0), 0]
    return [0]


def _resolve_camera(camera: str) -> int:
    """把逻辑名（cam0/front）解析为设备索引；空或 'all' 返回主摄像头索引。"""
    if camera in (None, "", "all", "default"):
        return CAMERA_DEVICE_ID
    if not _CAMERA_SCAN_DONE and HAS_CAMERA:
        _enumerate_cameras()
    if camera in _CAMERA_NAME_TO_INDEX:
        return _CAMERA_NAME_TO_INDEX[camera]
    try:
        return int(camera)
    except (ValueError, TypeError):
        return CAMERA_DEVICE_ID


def _camera_backend_for(device_id: int) -> int:
    """返回指定设备的最佳 cv2 后端（枚举时记录），未知则 0（默认后端）。"""
    if _CAMERA_SCAN_DONE:
        return _CAMERA_BACKEND.get(device_id, 0)
    if HAS_CAMERA:
        _enumerate_cameras()
    return _CAMERA_BACKEND.get(device_id, 0)


def _open_camera(device_id: int):
    """用记录的最佳后端打开摄像头；无记录后端则用默认。"""
    backend = _camera_backend_for(device_id)
    if backend:
        return cv2.VideoCapture(device_id, backend)
    return cv2.VideoCapture(device_id)


HERE = Path(__file__).resolve().parent
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000
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

# ── 闲置时感知参数 ──
# 未按 Enter 录音时，后台监听麦克风。连续 DETECT_FRAMES 帧 RMS 超过阈值即视为一次"响动"，
# 捕捉到静音/上限后打包上报后端 ASR 存档。阈值略高于正常录音 VAD，避免背景环境噪声误触发。
SENSING_RMS_THRESHOLD = float(os.environ.get("DSN_SENSING_RMS_THRESHOLD", "0.03"))
SENSING_DETECT_FRAMES = 3
SENSING_SILENCE_TIMEOUT = float(os.environ.get("DSN_SENSING_SILENCE_TIMEOUT", "1.5"))
SENSING_MIN_RECORD_SECS = float(os.environ.get("DSN_SENSING_MIN_RECORD_SECS", "0.4"))

# 麦克风仲裁：录音会话开始时置位，闲置监听立即让出麦克风（PvRecorder 同一设备不支持双开）。
_SENSING_PAUSE = threading.Event()

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


def _capture_camera_frame(camera: str | int | None = None) -> Optional[str]:
    """本地 cv2 抓一帧 → JPEG(q75) → base64 data URL。失败返回 None。

    支持逻辑名（cam0 / front）或设备索引；空则用主摄像头 CAMERA_DEVICE_ID。
    产物格式 ("data:image/jpeg;base64,...") 与后端 VisionModel 管道一致。
    成功抓帧后写入模块级帧缓存，供后续 on-demand 视觉请求零等待复用。
    """
    if not HAS_CAMERA:
        return None
    device_id = _resolve_camera(camera)
    try:
        cap = _open_camera(device_id)
        if not cap.isOpened():
            log.warning("摄像头无法打开 (device_id=%s)", device_id)
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
        data_url = "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("utf-8")
        _store_frame_cache(device_id, data_url)
        return data_url
    except Exception:
        log.warning("摄像头抓帧失败 (device_id=%s)", device_id, exc_info=True)
        return None


# ── 客户端帧缓存：缩短 on-demand 视觉请求的抓帧等待 ──
# key: device_id(int) → (ts, data_url)。抓帧开摄像头耗时较高（数百 ms 到 1s+），
# 心跳收到 vision_request 时优先复用新鲜缓存帧，避免每请求都重新开摄像头。
_FRAME_CACHE: dict[int, tuple[float, str]] = {}
_FRAME_CACHE_LOCK = threading.Lock()
FRAME_CACHE_MAX_AGE = float(os.environ.get("DSN_FRAME_CACHE_MAX_AGE", "3"))


def _store_frame_cache(device_id: int, data_url: str) -> None:
    with _FRAME_CACHE_LOCK:
        _FRAME_CACHE[device_id] = (time.time(), data_url)


def _cached_camera_frame(camera: str | int | None = None) -> Optional[str]:
    """返回缓存中仍新鲜的帧；无/过期则返回 None（由调用方决定是否现场抓帧）。"""
    if not HAS_CAMERA:
        return None
    device_id = _resolve_camera(camera)
    with _FRAME_CACHE_LOCK:
        entry = _FRAME_CACHE.get(device_id)
        if not entry:
            return None
        ts, data_url = entry
        if time.time() - ts > FRAME_CACHE_MAX_AGE:
            _FRAME_CACHE.pop(device_id, None)
            return None
        return data_url


def _capture_all_cameras() -> list[dict]:
    """枚举并逐台抓帧，返回 [{logical_name, index, image_data}]（只含抓帧成功的）。
    优先复用新鲜缓存帧；缺失/过期者现场抓帧（并行）。"""
    if not HAS_CAMERA:
        return []
    devices = _enumerate_cameras()
    if not devices:
        return []

    def _grab(dev: dict) -> Optional[dict]:
        idx = dev["index"]
        frame = _cached_camera_frame(idx)
        if frame is None:
            frame = _capture_camera_frame(idx)
        if not frame:
            return None
        return {
            "logical_name": dev["logical_name"],
            "index": idx,
            "image_data": frame,
        }

    if len(devices) <= 1:
        grabbed = [_grab(dev) for dev in devices]
    else:
        with ThreadPoolExecutor(max_workers=min(len(devices), 4),
                                thread_name_prefix="cam-capture") as ex:
            grabbed = list(ex.map(_grab, devices))
    return [g for g in grabbed if g]


def _capture_and_save_frame(camera, save_dir: Path) -> Optional[Path]:
    """抓一帧并保存为 JPEG 文件到 save_dir，返回保存路径；失败返回 None。"""
    if not HAS_CAMERA:
        return None
    device_id = _resolve_camera(camera)
    try:
        cap = _open_camera(device_id)
        if not cap.isOpened():
            log.warning("摄像头无法打开 (device_id=%s)", device_id)
            return None
        ret, frame = cap.read()
        cap.release()
        if not ret:
            log.warning("摄像头读取画面失败 (device_id=%s)", device_id)
            return None
        save_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = save_dir / f"camera_{device_id}_{ts}.jpg"
        ok = cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            log.warning("JPEG 写入失败: %s", path)
            return None
        return path
    except Exception:
        log.warning("摄像头抓帧保存失败 (device_id=%s)", device_id, exc_info=True)
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


def prompt_backend_host(cfg: dict) -> str:
    """首次启动时询问后端地址并持久化到配置文件；端口固定 5000，仅记录主机名。"""
    while True:
        choice = input("  Backend address (default 127.0.0.1): ").strip()
        if not choice:
            host = DEFAULT_HOST
        else:
            for scheme in ("http://", "https://"):
                if choice.startswith(scheme):
                    choice = choice[len(scheme):].split("/")[0]
                    break
            host = choice.split(":")[0].strip()
        if not host:
            continue
        cfg["backend_host"] = host
        save_config(cfg)
        print(f"  Backend address saved: {host}:{DEFAULT_PORT}")
        return host


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
# HeartbeatPoller — 心跳 + 提醒轮询
# ════════════════════════════════════════════════════════════════

class HeartbeatPoller:
    HEARTBEAT_INTERVAL = int(os.environ.get("DSN_HEARTBEAT_INTERVAL", "2"))
    HEARTBEAT_TIMEOUT = 30

    def __init__(self, client: "DSNClient", tts_queue: queue.Queue,
                 vision_observer: "VisionObserver | None" = None,
                 sensing_monitor: "IdleSensingMonitor | None" = None):
        self._client = client
        self._tts_queue = tts_queue
        self._vision_observer = vision_observer
        self._sensing_monitor = sensing_monitor
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
                    av.get("enabled", False), av.get("interval", 300),
                    av.get("camera", "")):
                log.info("VisionObserver 配置更新: enabled=%s interval=%s camera=%s",
                         av.get("enabled"), av.get("interval"), av.get("camera", ""))
                self._vision_observer.start()  # 已 start 则 no-op

        # ── 闲置时感知：用 heartbeat 下发的配置自配置 IdleSensingMonitor ──
        se = data.get("sensing")
        if se and self._sensing_monitor is not None:
            if self._sensing_monitor.configure(
                    se.get("enabled", False), se.get("cooldown", 60),
                    se.get("max_record_secs", 6.0)):
                log.info("IdleSensingMonitor 配置更新: enabled=%s cooldown=%s max_record=%s",
                         se.get("enabled"), se.get("cooldown"), se.get("max_record_secs"))
                self._sensing_monitor.start()  # 已 start 则 no-op

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
# 麦克风设备管理
# ════════════════════════════════════════════════════════════════

def _list_microphones() -> list[str]:
    """枚举本机可用麦克风设备名列表（列表下标即 PvRecorder 的 device_index）。"""
    if not HAS_PVRECORDER:
        return []
    try:
        return list(PvRecorder.get_audio_devices())
    except Exception:
        log.warning("麦克风枚举失败", exc_info=True)
        return []


def prompt_mic_selection(cfg: dict) -> Optional[int]:
    """列出所有麦克风并让用户选择（回车取消），把选择持久化到配置文件。
    返回选中的 device_index；未选择或不可用时返回 None。
    """
    devices = _list_microphones()
    if len(devices) <= 1:
        return None

    current = cfg.get("mic_device_index")
    print("\n  检测到多个麦克风:")
    for i, name in enumerate(devices):
        marker = "  ← 当前" if i == current else ""
        print(f"    [{i}] {name}{marker}")
    while True:
        choice = raw_input(f"  选择麦克风 [0-{len(devices)-1}]（回车保持默认）: ").strip()
        if choice == "":
            return None
        try:
            idx = int(choice)
        except ValueError:
            print("  无效输入，请重试")
            continue
        if 0 <= idx < len(devices):
            cfg["mic_device_index"] = idx
            save_config(cfg)
            print(f"  已选择麦克风: {devices[idx]} (device index={idx})")
            return idx
        print("  无效选择，请重试")


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

    @staticmethod
    def _device_index() -> int:
        """从配置读取持久化的麦克风设备索引；无效/缺失时用默认设备 (-1)。"""
        cfg = load_config()
        idx = cfg.get("mic_device_index")
        devices = _list_microphones()
        if isinstance(idx, int) and 0 <= idx < len(devices):
            return idx
        return -1

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

        # 让闲置监听让出麦克风：置位 + 短暂等待，避免同设备双开冲突
        _SENSING_PAUSE.set()
        time.sleep(0.15)

        try:
            self._recorder = PvRecorder(device_index=self._device_index(), frame_length=512)
        except Exception as e:
            print(f"  Cannot open microphone: {e}")
            _SENSING_PAUSE.clear()
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
        try:
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
        finally:
            _SENSING_PAUSE.clear()

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
# IdleSensingMonitor — 闲置时感知
# 未按 Enter 录音时后台监听麦克风，感知到响动 → 捕捉片段 → POST /api/sensing/event
# 后端 ASR 存档。配置由 heartbeat 响应的 sensing 字段自配置（configure→start）。
# ════════════════════════════════════════════════════════════════

class IdleSensingMonitor:
    def __init__(self, client: DSNClient, recorder: VoiceRecorder):
        self._client = client
        self._recorder = recorder
        self._running = False
        self._enabled = False
        self._cooldown = 60
        self._max_record_secs = 6.0
        self._last_event_ts = 0.0
        self._thread: Optional[threading.Thread] = None

    def configure(self, enabled: bool, cooldown: int, max_record_secs: float) -> bool:
        enabled = bool(enabled)
        cooldown = max(1, int(cooldown or 60))
        max_record_secs = max(1.0, float(max_record_secs or 6.0))
        changed = (enabled != self._enabled) or (cooldown != self._cooldown) \
            or (max_record_secs != self._max_record_secs)
        self._enabled = enabled
        self._cooldown = cooldown
        self._max_record_secs = max_record_secs
        return changed

    def start(self):
        if self._running:
            return
        if not self._enabled:
            log.info("IdleSensingMonitor 未启用 (sensing.enabled=false)")
            return
        if not HAS_PVRECORDER:
            log.warning("IdleSensingMonitor: pvrecorder 未安装，无法监听")
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log.info("IdleSensingMonitor 已启动 (cooldown=%ds, max_record=%.1fs)",
                 self._cooldown, self._max_record_secs)

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _loop(self):
        while self._running:
            if not self._enabled:
                time.sleep(1)
                continue
            if self._recorder.is_recording or _SENSING_PAUSE.is_set():
                time.sleep(0.5)
                continue
            if time.time() - self._last_event_ts < self._cooldown:
                time.sleep(0.5)
                continue
            audio = self._listen_once()
            if audio is None:
                continue
            self._send_event(audio)

    def _listen_once(self) -> Optional[np.ndarray]:
        """监听一轮：等触发→捕捉片段→返回音频；无可感知声音/被打断返回 None。"""
        recorder = None
        try:
            recorder = PvRecorder(device_index=VoiceRecorder._device_index(), frame_length=512)
        except Exception as e:
            log.warning("IdleSensingMonitor: 打开麦克风失败 %s", e)
            return None

        capture: list[np.ndarray] = []
        last_loud_ts = 0.0
        trigger_ts = 0.0
        consecutive_loud = 0
        peak = 0.0
        try:
            recorder.start()
            while self._running:
                if not self._enabled or self._recorder.is_recording or _SENSING_PAUSE.is_set():
                    return None
                frame = recorder.read()
                samples = np.array(frame, dtype=np.int16).astype(np.float32) / 32768.0
                energy = float(np.sqrt(np.mean(samples ** 2)))
                peak = max(peak, energy)
                now = time.time()

                if trigger_ts == 0.0:
                    # 触发阶段：连续多帧超阈值才算一次响动，避免单帧噪声误触发
                    if energy > SENSING_RMS_THRESHOLD:
                        consecutive_loud += 1
                    else:
                        consecutive_loud = 0
                    if consecutive_loud >= SENSING_DETECT_FRAMES:
                        trigger_ts = now
                        last_loud_ts = now
                        capture.append(samples)  # 把触发帧一并纳入捕捉
                else:
                    # 捕捉阶段：从触发开始收集，直到静音超时或达到上限
                    capture.append(samples)
                    if energy > SENSING_RMS_THRESHOLD:
                        last_loud_ts = now
                    dur = now - trigger_ts
                    sil = now - last_loud_ts
                    if sil > SENSING_SILENCE_TIMEOUT or dur >= self._max_record_secs:
                        break
        except Exception:
            log.warning("IdleSensingMonitor: 监听异常", exc_info=True)
            return None
        finally:
            try:
                recorder.stop()
            except Exception:
                logging.getLogger(__name__).warning("Stop operation failed", exc_info=True)
            try:
                recorder.delete()
            except Exception:
                logging.getLogger(__name__).warning("Delete/remove operation failed", exc_info=True)

        if trigger_ts == 0.0 or not capture:
            return None
        dur = time.time() - trigger_ts
        if dur < SENSING_MIN_RECORD_SECS:
            return None
        audio = np.concatenate(capture)
        log.info("IdleSensingMonitor: 捕捉到响动 %.1fs (peak_rms=%.3f)",
                 dur, peak)
        return audio

    def _send_event(self, audio: np.ndarray):
        if not self._client.api_key:
            return
        b64 = raw_pcm_to_wav_b64(audio)
        peak = float(np.sqrt(np.mean(np.abs(audio) ** 2))) if len(audio) else 0.0
        try:
            resp = self._client._http_post("/api/sensing/event", json={
                "audio_b64": b64,
                "source": "sensing",
                "rms_level": round(peak, 4),
                "chat_id": self._client.chat_id,
            }, timeout=30)
            data = resp.json() if resp.status_code == 200 else {}
            if resp.status_code == 200:
                # 无论是否落盘（文本过短/服务端节流），都进入冷却，避免对同一环境音反复上报
                self._last_event_ts = time.time()
                if data.get("recorded"):
                    log.info("IdleSensingMonitor: 已存档 text=%s", data.get("text", "")[:40])
                else:
                    log.info("IdleSensingMonitor: 上报被丢弃 (text=%r)",
                             (data.get("text") or "")[:40])
            elif resp.status_code == 403:
                log.info("IdleSensingMonitor: 服务端未启用感知，暂停监听")
                self._enabled = False
            else:
                log.info("IdleSensingMonitor: 上报异常 code=%s recorded=%s",
                         resp.status_code, data.get("recorded"))
        except Exception:
            log.warning("IdleSensingMonitor: 上报失败", exc_info=True)


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
    print("  [l]     alarm status    [v] list cameras")
    print("  [g]     select mic")
    print("  [q/Ctrl+C] quit         [n/m] vol-/+ (music)")
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


def print_cameras(client: DSNClient = None, save_shots: bool = True):
    """列出本机所有可用摄像头及其逻辑名/备注，并对每台抓一帧保存到 temp。"""
    print(f"\n  --- Cameras ---")
    if not HAS_CAMERA:
        print("  opencv-python 未安装，无法枚举摄像头")
        return

    cams = _enumerate_cameras()
    if not cams:
        print("  未检测到任何可用摄像头")
        return

    # 尝试拉取后端登记的备注（若有客户端引用）
    notes: dict[str, str] = {}
    if client is not None:
        try:
            resp = client._http_get("/api/vision/cameras", timeout=10)
            if resp.status_code == 200:
                for c in resp.json().get("cameras", []):
                    if c.get("note"):
                        notes[c["logical_name"]] = c["note"]
        except Exception:
            pass

    for c in cams:
        note = notes.get(c["logical_name"], "")
        marker = "  ← 主摄像头" if c["index"] == CAMERA_DEVICE_ID else ""
        line = f"  {c['logical_name']}: device{c['index']} (index={c['index']}){marker}"
        if note:
            line += f"  [备注: {note}]"
        print(line)

    # 对每台摄像头各拍一帧保存到 temp（测试效果 / 排查用）
    if save_shots:
        print("  正在逐台拍照保存到 temp/ ...")
        for c in cams:
            saved = _capture_and_save_frame(c["index"], TTS_DIR)
            if saved:
                print(f"    ✓ {c['logical_name']} → {saved.name}")
            else:
                print(f"    ✗ {c['logical_name']} 抓帧失败")
    print("  --------------------------")


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
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--pairing", default="")
    args = parser.parse_args()

    # 尽早注册 SIGINT，确保任何阻塞（含 cv2 摄像头枚举）期间 ^C 都能生效
    def _early_sigint(sig, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGINT, _early_sigint)

    cfg = load_config()

    # 后端地址解析：CLI --host > 配置文件 backend_host > 首次启动询问并持久化；端口固定 5000
    host = args.host
    if not host:
        host = (cfg.get("backend_host") or "").strip()
    if not host:
        host = prompt_backend_host(cfg)

    cfg["host"] = f"{host}:{args.port}"

    client = DSNClient(host, args.port)

    print(f"  Backend: http://{host}:{args.port}")
    try:
        r = requests.get(f"http://{host}:{args.port}/api/auth/status", timeout=5)
        if r.status_code == 200:
            st = r.json()
            methods = [k for k, v in st.get("methods", {}).items() if v]
            print(f"  Connected, methods: {', '.join(methods)}")
        else:
            print(f"  HTTP {r.status_code}")
    except Exception as e:
        print(f"  Connection check error: {e}")
        sys.exit(1)

    # 首次启动（无配置文件）或尚未选定麦克风：若检测到多个麦克风则询问用户选择并持久化
    if not CONFIG_FILE.exists() or "mic_device_index" not in cfg:
        prompt_mic_selection(cfg)

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
    sensing_mon = IdleSensingMonitor(client, recorder)
    vision_obs = VisionObserver(client)
    reminder = HeartbeatPoller(client, client._tts_queue, vision_observer=vision_obs,
                               sensing_monitor=sensing_mon)
    reminder.start()
    async_poller = AsyncTaskPoller(client, client._tts_queue)
    async_poller.start()
    client.async_poller = async_poller

    # 枚举摄像头并上报后端（多摄像头支持）——后台守护线程，避免 cv2 打开慢设备阻塞启动
    def _report_cameras_background():
        try:
            cams = _enumerate_cameras()
            if cams:
                client._http_post("/api/vision/cameras", json={"cameras": cams}, timeout=15)
                log.info("已上报 %d 个摄像头到后端: %s",
                         len(cams), ", ".join(d["logical_name"] for d in cams))
        except Exception:
            log.warning("摄像头枚举/上报失败", exc_info=True)
    threading.Thread(target=_report_cameras_background, daemon=True,
                     name="camera-report").start()

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

                # ── v: 列出所有可用摄像头 ──
                elif ch.lower() == "v":
                    print_cameras(client)

                # ── g: 选择/更换麦克风 ──
                elif ch.lower() == "g":
                    prompt_mic_selection(load_config())

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
            sensing_mon.stop()
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
