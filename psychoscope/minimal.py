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

try:
    pygame.init()
    pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=512)
    HAS_AUDIO = True
except Exception as e:
    HAS_AUDIO = False

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
        self._audio_queue = queue.Queue()
        self._mixer_ready = False
        self._channel = None
        if HAS_AUDIO:
            self._audio_thread = threading.Thread(target=self._audio_worker, daemon=True)
            self._audio_thread.start()

    def _audio_worker(self):
        while True:
            b64 = self._audio_queue.get()
            if b64 is None:
                continue
            try:
                raw = base64.b64decode(b64)
                if not self._mixer_ready:
                    with wave.open(io.BytesIO(raw), 'rb') as wf:
                        sr = wf.getframerate()
                        ch = wf.getnchannels()
                    pygame.mixer.quit()
                    pygame.mixer.init(frequency=sr, size=-16, channels=ch, buffer=512)
                    self._channel = pygame.mixer.Channel(0)
                    self._mixer_ready = True

                sound = pygame.mixer.Sound(file=io.BytesIO(raw))
                while self._channel.get_busy() and self._channel.get_queue() is not None:
                    time.sleep(0.005)

                if not self._channel.get_busy():
                    self._channel.play(sound)
                else:
                    self._channel.queue(sound)
            except Exception as e:
                log.error(f"Playback error: {e}")

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

            reply_text = self._handle_sse_stream(resp)
            return reply_text
        except Exception as e:
            log.error("Audio send failed: %s", e)
            return None

    def _handle_sse_stream(self, resp: requests.Response) -> Optional[str]:
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
                    self._audio_queue.put(audio_b64)
                print(f"\r  TTS [{idx}/{total}] {text[:50]}", end="", flush=True)

            elif status == "completed":
                print("\n  Complete")
                break

        return reply if got_text else None

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

def print_header(cfg: dict):
    os.system("cls" if os.name == "nt" else "clear")
    print("===========================================")
    print("        DSN-exp  Minimal Client            ")
    print("===========================================")
    uid = cfg.get("uid", "?")
    name = cfg.get("display_name", "?")
    host = cfg.get("host", f"{DEFAULT_HOST}:{DEFAULT_PORT}")
    print(f"  Backend : {host}")
    print(f"  User    : uid={uid} ({name})")
    print("===========================================")
    print("  [Enter]  Start / Stop speaking           ")
    print("  [p]      Show personality status         ")
    print("  [s]      Toggle standby / wakeup         ")
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

    print_header(cfg)
    print("  Ready! Press Enter to speak...\n")

    recorder = VoiceRecorder(client)
    keyboard = KeyboardHandler()
    keyboard.start()

    def on_sigint(sig, frame):
        if recorder.is_recording:
            recorder.stop_and_send()
        keyboard.stop()
        save_config(cfg)
        print("\n  Goodbye")
        sys.exit(0)

    signal.signal(signal.SIGINT, on_sigint)

    buffer = ""
    try:
        while True:
            ch = keyboard.get(timeout=0.15)
            if ch is None:
                if recorder._frames and not recorder.is_recording and not recorder._sent_frames is recorder._frames:
                    print()
                    recorder.stop_and_send()
                    print()
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

            elif ch.lower() == "h":
                print_header(cfg)

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
            else:
                buffer += ch

    except KeyboardInterrupt:
        pass
    finally:
        if recorder.is_recording:
            recorder.stop_and_send()
        keyboard.stop()
        cfg["chat_id"] = client.chat_id
        save_config(cfg)
        print("\n  Goodbye")

if __name__ == "__main__":
    main()