# apps/dsn/CLI/sensing.py
# IdleSensingMonitor — 闲置时感知（聆听）。
# 聆听能力由独立 tracking 子系统（用户跟踪系统 infra）的 AudioListeningMonitor 提供。
# 本适配器把 tracking 的聆听器接入本客户端：transport 负责把捕捉到的音频转 WAV base64
# 上报后端 /api/sensing/event（后端落库到统一 tracking_events，并回写旧 sensing_events）。
# 配置由 heartbeat 响应的 tracking / sensing 字段自配置（configure→start）。
#
# 从原 psychoscope/minimal.py 抽出（1995-2083）。两处调整：
#   - 麦克风让位判断改走 audio.MIC 仲裁器（录音/TTS/音乐持有期间不监听，
#     修掉"TTS 播放被闲置监听录回去"的自触发回路）
#   - tracking.audio_listen 导入失败显式降级（独立部署缺失该模块时禁用并告警，
#     不再静默吞掉每次心跳里的 ImportError）

from __future__ import annotations

import numpy as np

from .audio import MIC, VoiceRecorder, raw_pcm_to_wav_b64
from .env import HAS_PVRECORDER, log


class IdleSensingMonitor:
    """适配 tracking.AudioListeningMonitor 的闲置聆听器（保持原接口 configure/start/stop/enabled）。

    原实现（监听 + 上报）已抽取到 tracking/audio_listen.py，此处仅做依赖绑定：
      - is_busy:  正式录音/TTS/音乐占用麦克风时让出
      - transport_send: 捕捉到音频后转 base64 上报后端
    """

    def __init__(self, client, recorder: VoiceRecorder):
        self._client = client
        self._recorder = recorder
        self._inner = None
        self._pending_enabled = False
        self._pending_cooldown = 60
        self._pending_max_record = 6.0
        self._instantiated = False

    def _ensure_inner(self):
        if self._instantiated:
            return
        self._instantiated = True
        try:
            from apps.dsn.tracking.audio_listen import AudioListeningMonitor
        except Exception:
            # 独立部署（如树莓派）缺失 tracking 子树时禁用，不影响其余功能
            log.warning("闲置感知不可用：无法导入 tracking.audio_listen（缺失该模块？）",
                        exc_info=True)
            return

        def _is_busy() -> bool:
            return bool(self._recorder.is_recording or MIC.busy)

        def _transport(audio: np.ndarray):
            self._send_event(audio)

        self._inner = AudioListeningMonitor(
            transport_send=_transport,
            is_busy=_is_busy,
            device_index=VoiceRecorder._device_index() if HAS_PVRECORDER else -1,
        )
        # 应用此前缓存的配置
        self._inner.configure(self._pending_enabled, self._pending_cooldown,
                              self._pending_max_record)

    def configure(self, enabled: bool, cooldown: int, max_record_secs: float) -> bool:
        self._pending_enabled = bool(enabled)
        self._pending_cooldown = max(1, int(cooldown or 60))
        self._pending_max_record = max(1.0, float(max_record_secs or 6.0))
        if self._instantiated:
            return self._inner.configure(self._pending_enabled, self._pending_cooldown,
                                         self._pending_max_record)
        # 未实例化时先缓存，返回"需要 start"标记
        return self._pending_enabled

    def start(self):
        self._ensure_inner()
        if self._inner is None:
            return
        self._inner.start()

    def stop(self):
        if self._inner is not None:
            self._inner.stop()

    @property
    def enabled(self) -> bool:
        return self._pending_enabled

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
                if data.get("recorded"):
                    log.info("IdleSensingMonitor: 已存档 text=%s", data.get("text", "")[:40])
                else:
                    log.info("IdleSensingMonitor: 上报被丢弃 (text=%r)",
                             (data.get("text") or "")[:40])
            elif resp.status_code == 403:
                log.info("IdleSensingMonitor: 服务端未启用感知，暂停监听")
                self.configure(False, self._pending_cooldown, self._pending_max_record)
            else:
                log.info("IdleSensingMonitor: 上报异常 code=%s recorded=%s",
                         resp.status_code, data.get("recorded"))
        except Exception:
            log.warning("IdleSensingMonitor: 上报失败", exc_info=True)
