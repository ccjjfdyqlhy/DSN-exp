"""
ASR 客户端 — 录音并发送到 ASR 独立服务，显示识别结果

用法:
    python asr_client.py                          # 默认连接 localhost:5001
    python asr_client.py --host 192.168.1.100     # 指定地址
    python asr_client.py --port 5002               # 指定端口
    python asr_client.py --text "你好"              # 跳过录音，直接输入文本模拟

操作:
    [Enter]  开始 / 停止录音
    [q]      退出
"""

from __future__ import annotations

import argparse
import base64
import logging

_log = logging.getLogger(__name__)
import io
import json
import logging
import os
import sys
import threading
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import requests

try:
    from pvrecorder import PvRecorder
    HAS_PVRECORDER = True
except ImportError:
    HAS_PVRECORDER = False

SAMPLE_RATE = 16000
SILENCE_TIMEOUT = 2.0
MAX_RECORD_SECS = 30
RMS_THRESHOLD = 0.008


def raw_pcm_to_wav_b64(samples: np.ndarray, sr: int = SAMPLE_RATE) -> str:
    int_samples = np.clip(samples * 32767, -32768, 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(int_samples.tobytes())
    return base64.b64encode(buf.getvalue()).decode("utf-8")


class VoiceRecorder:
    def __init__(self, on_audio_b64, save_dir: str | None = None):
        self._on_audio = on_audio_b64
        self._save_dir = Path(save_dir) if save_dir else None
        self._recording = False
        self._frames: list[np.ndarray] = []
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
            print("  pvrecorder 未安装, pip install pvrecorder")
            return
        try:
            self._recorder = PvRecorder(device_index=-1, frame_length=512)
        except Exception as e:
            print(f"  麦克风打开失败: {e}")
            return
        self._recording = True
        self._frames = []
        self._last_speech_time = time.time()
        self._start_time = time.time()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self):
        if not self._recording:
            return
        self._recording = False
        self._stop_event.set()
        if self._recorder:
            try:
                self._recorder.stop()
            except Exception:
                _log.warning("Stop operation failed", exc_info=True)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        if self._recorder:
            try:
                self._recorder.delete()
            except Exception:
                _log.warning("Delete/remove operation failed", exc_info=True)
            self._recorder = None
        dur = time.time() - self._start_time
        if not self._frames or dur < 0.5:
            print("\n  录音太短，已忽略")
            return
        audio = np.concatenate(self._frames)
        b64 = raw_pcm_to_wav_b64(audio)

        # 保存本地
        if self._save_dir:
            self._save_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            wav_path = self._save_dir / f"recording_{ts}.wav"
            int_samples = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
            with wave.open(str(wav_path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(int_samples.tobytes())
            print(f"\n  💾 已保存: {wav_path}")

        self._on_audio(b64)

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
                status = "录音中" if energy > RMS_THRESHOLD else "静音  "
                print(f"\r  {status} [{bar}] {dur:.1f}s (静音 {sil:.1f}s)  ", end="", flush=True)
                if sil > SILENCE_TIMEOUT or dur > MAX_RECORD_SECS:
                    self._recording = False
                    break
        except Exception:
            _log.warning("Operation failed", exc_info=True)
        finally:
            try:
                self._recorder.stop()
            except Exception:
                _log.warning("Stop operation failed", exc_info=True)


class ASRClient:
    def __init__(self, base_url: str):
        self._base = base_url.rstrip("/")

    def recognize_b64(self, audio_b64: str) -> str:
        resp = requests.post(
            f"{self._base}/api/asr/recognize_b64",
            json={"audio_b64": audio_b64},
            timeout=60,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text}")
        return resp.json().get("text", "")

    def recognize_file(self, path: str) -> str:
        with open(path, "rb") as f:
            resp = requests.post(
                f"{self._base}/api/asr/recognize",
                files={"audio": f},
                timeout=60,
            )
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text}")
        return resp.json().get("text", "")


def _send_and_print(client: ASRClient, audio_b64: str, label: str = ""):
    prefix = f"  [{label}] " if label else "  "
    print(f"\n{prefix}正在识别...")
    try:
        text = client.recognize_b64(audio_b64)
        print(f"{prefix}识别结果: {text}")
    except Exception as e:
        print(f"{prefix}识别失败: {e}")


def main():
    parser = argparse.ArgumentParser(description="ASR 客户端")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--text", help="直接输入文本模拟音频（跳过录音）")
    parser.add_argument("--file", help="直接识别指定的音频文件")
    parser.add_argument("--save-dir", default="asr_recordings", help="录音保存目录（默认 asr_recordings）")
    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}"
    client = ASRClient(base_url)

    # 健康检查
    try:
        r = requests.get(f"{base_url}/api/health", timeout=5)
        if r.status_code != 200:
            print(f"服务端返回异常: {r.status_code}")
            sys.exit(1)
        info = r.json()
        print(f"ASR 服务端: {base_url}  模型已加载: {info.get('model_loaded')}")
    except requests.ConnectionError:
        print(f"无法连接 ASR 服务端: {base_url}")
        sys.exit(1)

    # 文件模式
    if args.file:
        print(f"\n  识别文件: {args.file}")
        text = client.recognize_file(args.file)
        print(f"  识别结果: {text}")
        return

    # 文本模拟模式
    if args.text:
        print(f"\n  输入文本: {args.text}")
        print(f"  识别结果: {args.text}  (模拟)")
        return

    # 交互录音模式
    print("\n  =========================")
    print("   ASR 录音客户端")
    print("  =========================")
    print("  [Enter]  开始 / 停止录音")
    print("  [q]      退出")
    print("  =========================")
    print()

    def on_audio(audio_b64: str):
        _send_and_print(client, audio_b64, "录音")

    recorder = VoiceRecorder(on_audio, save_dir=args.save_dir)

    try:
        import select
        import sys as _sys
        import termios
        import tty
        fd = _sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        tty.setcbreak(fd)
        try:
            while True:
                if select.select([_sys.stdin], [], [], 0.1)[0]:
                    ch = _sys.stdin.read(1)
                    if ch in ("\r", "\n"):
                        if recorder.is_recording:
                            recorder.stop()
                            print()
                        else:
                            print("\n  录音中...(按 Enter 停止)")
                            recorder.start()
                    elif ch.lower() == "q":
                        if recorder.is_recording:
                            recorder.stop()
                        break
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except (ImportError, AttributeError):
        print("\n  不支持 raw 终端模式，使用简单输入模式")
        while True:
            cmd = input("  Enter=录音 q=退出: ").strip().lower()
            if cmd == "q":
                break
            if recorder.is_recording:
                recorder.stop()
                print()
            else:
                print("  录音中...(按 Enter 停止)")
                recorder.start()

    print("\n  再见")


if __name__ == "__main__":
    main()
