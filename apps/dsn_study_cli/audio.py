# apps/dsn_study_cli/audio.py
# 录音 → WAV 16k mono s16 → base64（pvrecorder 可选；缺失时语音输入禁用）。
#
# 采样参数与 dsn CLI / 服务端 ASR（FunASR）对齐：16 kHz 单声道 16bit。
# VAD：帧 RMS 阈值 —— 静音超 SILENCE_TIMEOUT 自动停，总长 MAX_RECORD_SECS 封顶。

from __future__ import annotations

import base64
import io
import logging
import struct
import threading
import time
import wave

from apps.dsn_study_cli.env import HAS_PVRECORDER

logger = logging.getLogger("study_cli.audio")

SAMPLE_RATE = 16000
FRAME_LENGTH = 512              # 采样点/帧（32ms @16k）
SILENCE_TIMEOUT = 2.0           # 连续静音 N 秒自动停
MAX_RECORD_SECS = 30.0          # 单次录音上限
MIN_RECORD_SECS = 0.5           # 短于此时长视为误触，丢弃
RMS_THRESHOLD = 0.008


def rms_of(frame) -> float:
    """pcm int16 帧 → 归一化 RMS（frame 为字节串，2 字节/样本）。"""
    if not frame:
        return 0.0
    data = bytes(bytearray(frame))
    n = len(data) // 2          # int16 → 2 字节/样本
    if n == 0:
        return 0.0
    acc = 0.0
    for s in struct.unpack(f"<{n}h", data[: n * 2]):
        acc += (s / 32768.0) ** 2
    return (acc / n) ** 0.5


def pcm_to_wav_b64(samples: bytes, sr: int = SAMPLE_RATE) -> str:
    """PCM int16 单声道字节 → WAV base64。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(samples)
    return base64.b64encode(buf.getvalue()).decode("ascii")


class VoiceRecorder:
    """按键式录音器：start() 开始，stop_and_send() 停止并回调。

    无 pvrecorder 时 `available=False`，start 直接回调失败提示。
    """

    def __init__(self, device_index: int = -1,
                 on_audio=None, on_status=None):
        self._device_index = device_index
        self._on_audio = on_audio            # callable(audio_b64, secs)
        self._on_status = on_status          # callable(text)
        self._recorder = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._busy = threading.Lock()
        self._samples: list[bytes] = []
        self._last_speech = 0.0

    @property
    def available(self) -> bool:
        return HAS_PVRECORDER

    @property
    def is_recording(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _device(self) -> int:
        if self._device_index is not None and self._device_index >= 0:
            return self._device_index
        return -1   # pvrecorder 默认设备

    def start(self) -> bool:
        if not HAS_PVRECORDER:
            if self._on_status:
                self._on_status("（本机未安装 pvrecorder，语音输入不可用）")
            return False
        with self._busy:
            if self.is_recording:
                return False
            self._stop.clear()
            self._samples = []
            try:
                self._recorder = HAS_PVRECORDER and __import__(
                    "pvrecorder", fromlist=["PvRecorder"]).PvRecorder(
                    device_index=self._device(), frame_length=FRAME_LENGTH)
                self._recorder.start()
            except Exception as e:   # noqa: BLE001
                logger.warning("录音器启动失败: %s", e)
                if self._on_status:
                    self._on_status(f"（录音器启动失败: {e}）")
                return False
            self._last_speech = time.time()
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
            return True

    def _loop(self):
        start = time.time()
        while not self._stop.is_set():
            try:
                frame = self._recorder.read()
            except Exception:   # noqa: BLE001
                break
            if not frame:
                continue
            self._samples.append(bytes(bytearray(frame)))
            energy = rms_of(frame[-FRAME_LENGTH:])
            if energy > RMS_THRESHOLD:
                self._last_speech = time.time()
            now = time.time()
            if (now - self._last_speech > SILENCE_TIMEOUT
                    or now - start > MAX_RECORD_SECS):
                break
        self._finalize()

    def stop_and_send(self):
        """停止录音并把音频交给回调（<0.5s 丢弃）。"""
        self._stop.set()

    def _finalize(self):
        try:
            if self._recorder is not None:
                try:
                    self._recorder.stop()
                except Exception:   # noqa: BLE001
                    pass
                try:
                    self._recorder.delete()
                except Exception:   # noqa: BLE001
                    pass
        finally:
            self._recorder = None
        samples = b"".join(self._samples)
        self._samples = []
        secs = len(samples) / 2 / SAMPLE_RATE
        if secs < MIN_RECORD_SECS:
            if self._on_status:
                self._on_status("（录音太短，已丢弃）")
            return
        audio_b64 = pcm_to_wav_b64(samples)
        if self._on_audio:
            self._on_audio(audio_b64, secs)
