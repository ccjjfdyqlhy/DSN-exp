# tracking/audio_listen.py
# AudioListeningMonitor — 用户跟踪系统的"聆听"能力（infra）。
# 从原 psychoscope/minimal.py 的 IdleSensingMonitor 抽取而来，去掉了对 DSNClient /
# VoiceRecorder / 模块级常量 的强依赖，改为通过轻量接口注入：
#   - is_busy():      返回 True 表示外部正在占用麦克风（如正式录音），应让出
#   - send(audio):    将捕捉到的一段音频交给上层（客户端会转 WAV base64 上报后端）
#
# 监听逻辑保持不变：连续多帧 RMS 超阈值判定"响动"，静音超时/达到上限结束捕捉。
# 这是 infra 的一部分；闲时感知（仅音频）依赖它。

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger("tracking.audio_listen")

try:
    import numpy as np
except ImportError:  # numpy 仅聆听时使用，缺失时降级为不可用
    np = None

# 可独立调节的默认参数（环境变量可覆盖，与原 minimal.py 默认值一致）
RMS_THRESHOLD = float(os.environ.get("DSN_SENSING_RMS_THRESHOLD", "0.03"))
DETECT_FRAMES = int(os.environ.get("DSN_TRACKING_DETECT_FRAMES", "3"))
SILENCE_TIMEOUT = float(os.environ.get("DSN_SENSING_SILENCE_TIMEOUT", "1.5"))
MIN_RECORD_SECS = float(os.environ.get("DSN_SENSING_MIN_RECORD_SECS", "0.4"))
FRAME_LENGTH = 512


class AudioListeningMonitor:
    """后台持续聆听麦克风，感知到"响动"即捕捉一段音频交给上层。

    :param transport_send:  callable(audio: np.ndarray) — 接收捕捉到的一段音频
    :param is_busy:         callable() -> bool — 外部占用麦克风时为 True
    :param device_index:    麦克风设备索引
    """

    def __init__(self, transport_send: Callable[[np.ndarray], None],
                 is_busy: Optional[Callable[[], bool]] = None,
                 device_index: Optional[int] = None):
        self._send = transport_send
        self._is_busy = is_busy or (lambda: False)
        self._device_index = device_index

        self._running = False
        self._enabled = False
        self._cooldown = 60
        self._max_record_secs = 6.0
        self._last_event_ts = 0.0
        self._thread: Optional[threading.Thread] = None

    # ── 生命周期 ──
    def configure(self, enabled: bool, cooldown: int, max_record_secs: float) -> bool:
        """更新配置；返回是否有实质变化（供调用方决定是否需要 start）。"""
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
            logger.info("AudioListeningMonitor 未启用 (tracking.enabled=false)")
            return
        try:
            from pvrecorder import PvRecorder  # noqa: F401
        except ImportError:
            logger.warning("AudioListeningMonitor: pvrecorder 未安装，无法监听")
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("AudioListeningMonitor 已启动 (cooldown=%ds, max_record=%.1fs)",
                    self._cooldown, self._max_record_secs)

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def running(self) -> bool:
        return self._running

    # ── 主循环 ──
    def _loop(self):
        while self._running:
            if not self._enabled:
                time.sleep(1)
                continue
            if self._is_busy():
                time.sleep(0.5)
                continue
            if time.time() - self._last_event_ts < self._cooldown:
                time.sleep(0.5)
                continue
            audio = self._listen_once()
            if audio is None:
                continue
            self._last_event_ts = time.time()
            try:
                self._send(audio)
            except Exception:
                logger.warning("AudioListeningMonitor: 上报失败", exc_info=True)

    def _listen_once(self) -> Optional[np.ndarray]:
        """监听一轮：等触发→捕捉片段→返回音频；无可感知声音/被打断返回 None。"""
        from pvrecorder import PvRecorder

        recorder = None
        try:
            recorder = PvRecorder(device_index=self._device_index if self._device_index is not None else -1,
                                  frame_length=FRAME_LENGTH)
        except Exception as e:
            logger.warning("AudioListeningMonitor: 打开麦克风失败 %s", e)
            return None

        capture: list[np.ndarray] = []
        last_loud_ts = 0.0
        trigger_ts = 0.0
        consecutive_loud = 0
        peak = 0.0
        try:
            recorder.start()
            while self._running:
                if not self._enabled or self._is_busy():
                    return None
                frame = recorder.read()
                samples = np.array(frame, dtype=np.int16).astype(np.float32) / 32768.0
                energy = float(np.sqrt(np.mean(samples ** 2)))
                peak = max(peak, energy)
                now = time.time()

                if trigger_ts == 0.0:
                    # 触发阶段：连续多帧超阈值才算一次响动，避免单帧噪声误触发
                    if energy > RMS_THRESHOLD:
                        consecutive_loud += 1
                    else:
                        consecutive_loud = 0
                    if consecutive_loud >= DETECT_FRAMES:
                        trigger_ts = now
                        last_loud_ts = now
                        capture.append(samples)  # 把触发帧一并纳入捕捉
                else:
                    # 捕捉阶段：从触发开始收集，直到静音超时或达到上限
                    capture.append(samples)
                    if energy > RMS_THRESHOLD:
                        last_loud_ts = now
                    dur = now - trigger_ts
                    sil = now - last_loud_ts
                    if sil > SILENCE_TIMEOUT or dur >= self._max_record_secs:
                        break
        except Exception:
            logger.warning("AudioListeningMonitor: 监听异常", exc_info=True)
            return None
        finally:
            try:
                recorder.stop()
            except Exception:
                logger.warning("AudioListeningMonitor: stop 失败", exc_info=True)
            try:
                recorder.delete()
            except Exception:
                logger.warning("AudioListeningMonitor: delete 失败", exc_info=True)

        if trigger_ts == 0.0 or not capture:
            return None
        dur = time.time() - trigger_ts
        if dur < MIN_RECORD_SECS:
            return None
        audio = np.concatenate(capture)
        logger.info("AudioListeningMonitor: 捕捉到响动 %.1fs (peak_rms=%.3f)", dur, peak)
        return audio
