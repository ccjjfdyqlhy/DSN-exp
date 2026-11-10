# apps/dsn_study_cli/audio.py
# 录音 → WAV 16k mono s16 → base64（pvrecorder 可选；缺失时语音输入禁用）。
#
# 采样参数与 dsn CLI / 服务端 ASR（FunASR）对齐：16 kHz 单声道 16bit。
# VAD：帧 RMS 阈值 —— 静音超 SILENCE_TIMEOUT 自动停，总长 MAX_RECORD_SECS 封顶。

from __future__ import annotations

import base64
import io
import logging
import os
import struct
import threading
import time
import wave

from apps.dsn_study_cli.env import HAS_PVRECORDER

logger = logging.getLogger("study_cli.audio")

SAMPLE_RATE = 16000
FRAME_LENGTH = 512              # 采样点/帧（32ms @16k）
# 连续静音 N 秒自动停 —— 这是「用户说完话 → 请求发出」的**第一段固定延迟**，
# 直接计入对讲机的体感延迟。VAD 挂起时间典型取 0.5~1.0s：
# 太大 → 白等；太小 → 句中换气被误判成说完，把话截断。
# 可用 STUDY_SILENCE_TIMEOUT 覆盖。
SILENCE_TIMEOUT = float(os.environ.get("STUDY_SILENCE_TIMEOUT", "0.9"))
MAX_RECORD_SECS = 30.0          # 单次录音上限
MIN_RECORD_SECS = 0.5           # 短于此时长视为误触，丢弃
RMS_THRESHOLD = 0.008


def list_microphones() -> list[str]:
    """枚举本机可用麦克风设备名列表（列表下标即 PvRecorder 的 device_index）。"""
    if not HAS_PVRECORDER:
        return []
    try:
        from pvrecorder import PvRecorder as _PR
        # 注意：方法名是 get_available_devices()（pvrecorder 1.2.7）；
        # dsn CLI 里写的 get_audio_devices() 在这个版本上不存在，
        # 会被 except 静默吞掉 → 麦克风按名字选永远选不中。
        getter = getattr(_PR, "get_available_devices", None)
        if getter is None:
            return []
        return list(getter())
    except Exception:   # noqa: BLE001
        logger.warning("麦克风枚举失败", exc_info=True)
        return []


def resolve_device_index(cfg: dict | None = None) -> int:
    """解析要用的麦克风 device_index。

    **按名字优先，不按序号。**
    PipeWire 的 ALSA 插件会随 USB 设备插拔增删采集设备，序号整体平移 ——
    实测插上第二个摄像头（自带 USB 麦克风）后，原序号就指向了别的设备
    （还一度指到 "Monitor of 内置音频" 这种回环通道上）。
    所以配置用 mic_device_name（子串匹配，忽略大小写）；
    mic_device_index 只在名字没配/没匹配上时兜底。
    """
    cfg = cfg or {}
    name = str(cfg.get("mic_device_name") or "").strip().lower()
    if name:
        names = list_microphones()
        for i, dev in enumerate(names):
            if name in dev.lower():
                logger.info("麦克风按名字命中: idx=%d (%s)", i, dev)
                return i
        logger.warning("麦克风名字未命中: %r（可用: %s）", name, names)
    try:
        return int(cfg.get("mic_device_index", -1))
    except (TypeError, ValueError):
        return -1


def frame_to_bytes(frame) -> bytes:
    """录音帧 → 原始 int16 小端字节。

    pvrecorder 1.2.7 的 read() 返回的是 **int16 样本列表**，而另一些实现
    返回 bytes —— 两种都得认。`bytes(bytearray(list))` 会抛
    "byte must be in range(0, 256)"（样本值远超 255）。
    """
    if frame is None:
        return b""
    if isinstance(frame, (bytes, bytearray, memoryview)):
        return bytes(frame)
    try:
        return struct.pack("<%dh" % len(frame), *frame)
    except (TypeError, struct.error, OverflowError):
        return b""


def rms_of(frame) -> float:
    """pcm int16 帧 → 归一化 RMS（2 字节/样本）。"""
    if not frame:
        return 0.0
    data = frame_to_bytes(frame)
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
                 on_audio=None, on_status=None, cfg: dict | None = None):
        # 有 cfg 时按名字解析 —— 抗 PipeWire 设备序号漂移
        self._device_index = (resolve_device_index(cfg) if cfg
                              else device_index)
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
            self._samples.append(frame_to_bytes(frame))
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
