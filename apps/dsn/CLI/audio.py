# apps/dsn/CLI/audio.py
# 音频链路：WAV 编码 / 提示音 / 麦克风仲裁 / 录音器 / TTS 播放 / 音乐播放。
#
# 从原 psychoscope/minimal.py 抽出（MusicPlayer / _play_beep / raw_pcm_to_wav_*
# / VoiceRecorder / DSNClient._tts_worker）。
# 新增两块：
#   - MicArbiter：麦克风占用仲裁（引用计数）。录音 / TTS / 音乐持有期间，
#     闲置监听（IdleSensingMonitor）让出麦克风——修掉"TTS 播放被闲置监听录回去"
#     的自触发回路。
#   - TtsPlayer：原 DSNClient._tts_worker 独立成类，播放逻辑不变。

from __future__ import annotations

import base64
import io
import logging
import os
import queue
import tempfile
import threading
import time
import wave
from typing import Callable, Optional

import numpy as np

from .env import HAS_AUDIO, HAS_PVRECORDER, PvRecorder, VLC_INSTANCE, log

# ── 录音参数（与原 minimal.py 一致）──
SAMPLE_RATE = 16000
SILENCE_TIMEOUT = 2.0
MAX_RECORD_SECS = 30
RMS_THRESHOLD = 0.008


class MicArbiter:
    """麦克风占用仲裁：引用计数，>0 表示有组件持有（录音/TTS/音乐），闲置监听应让出。

    持有方必须保证 acquire/release 成对（推荐 try/finally）；计数归零即释放。
    """

    def __init__(self):
        self._count = 0
        self._lock = threading.Lock()

    def acquire(self) -> int:
        with self._lock:
            self._count += 1
            return self._count

    def release(self) -> int:
        with self._lock:
            self._count = max(0, self._count - 1)
            return self._count

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._count > 0


# 模块级单例：全客户端共用一个麦克风仲裁器
MIC = MicArbiter()


def raw_pcm_to_wav_b64(samples: np.ndarray, sr: int = SAMPLE_RATE) -> str:
    int_samples = np.clip(samples * 32767, -32768, 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(int_samples.tobytes())
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def raw_pcm_to_wav_bytes(samples: np.ndarray, sr: int = SAMPLE_RATE) -> bytes:
    """把 PCM float 样本数组编码为 WAV 字节（用于上传打卡音频）。"""
    int_samples = np.clip(samples * 32767, -32768, 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(int_samples.tobytes())
    return buf.getvalue()


def _play_beep(client=None, freq: int = 600):
    """短提示音（VLC 临时文件播放）。client 参数保留原签名但未使用。"""
    if not HAS_AUDIO:
        return
    sr = 44100
    dur = 0.06
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    wave_ = np.sin(2 * np.pi * freq * t) * 0.3
    samples = np.clip(wave_ * 32767, -32768, 32767).astype(np.int16)
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


# ════════════════════════════════════════════════════════════════
# 麦克风设备枚举
# ════════════════════════════════════════════════════════════════

def _list_microphones() -> list[str]:
    """枚举本机可用麦克风设备名列表（列表下标即 PvRecorder 的 device_index）。"""
    if not HAS_PVRECORDER:
        return []
    try:
        # pvrecorder 1.2.7 的方法名是 get_available_devices()；
        # 之前写的 get_audio_devices() 在这个版本上不存在，
        # 会被 except 静默吞掉 → 麦克风按名字选永远选不中。
        getter = getattr(PvRecorder, "get_available_devices", None)
        if getter is None:
            return []
        return list(getter())
    except Exception:
        log.warning("麦克风枚举失败", exc_info=True)
        return []


# ════════════════════════════════════════════════════════════════
# TtsPlayer — TTS 播放线程（从 DSNClient._tts_worker 抽出）
# ════════════════════════════════════════════════════════════════

class TtsPlayer:
    """消费 (text, audio_b64) 队列并逐段播放（VLC 写临时 WAV 文件）。

    :param tts_queue:  (text, b64) 元组队列，None 为空占位
    :param tts_stop:   停止事件（外部 stop_tts 置位 → 当前段中断 + 清队列）
    :param music_lookup: callable() -> MusicPlayer | None，播放前 duck 音乐、结束 unduck
    """

    def __init__(self, tts_queue: queue.Queue,
                 tts_stop: threading.Event,
                 music_lookup: Callable[[], Optional[object]]):
        self._queue = tts_queue
        self._stop = tts_stop
        self._music_lookup = music_lookup
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._worker, daemon=True, name="tts-player")
        self._thread.start()

    def _worker(self):
        while True:
            item = self._queue.get()
            if item is None:
                self._queue.task_done()
                continue
            text, b64 = item
            log.info("[DEBUG_CLI] TtsPlayer: 开始播放, 文本[:40]=%r, queue_size=%d, t=%.4f",
                     text[:40], self._queue.qsize(), time.perf_counter())
            ducked = False
            tmp_path = None
            held = False
            try:
                self._stop.clear()
                raw = base64.b64decode(b64)
                music = self._music_lookup()
                if music:
                    music.duck()
                    ducked = True

                # TTS 播放期间让闲置监听让出麦克风（修自触发回路）
                MIC.acquire()
                held = True

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
                    log.info("[DEBUG_CLI] TtsPlayer: VLC 开始播放, duration=%.1fms, t=%.4f",
                             duration_ms, time.perf_counter())
                    played = 0.0
                    step = 0.3
                    total = duration_ms / 1000.0 + 0.2
                    while played < total:
                        if self._stop.is_set():
                            log.info("[DEBUG_CLI] TtsPlayer: 被 stop 信号中断, t=%.4f",
                                     time.perf_counter())
                            break
                        time.sleep(step)
                        played += step
                p.stop()
                p.release()
                log.info("[DEBUG_CLI] TtsPlayer: 播放结束, t=%.4f", time.perf_counter())
            except Exception as e:
                log.error(f"[DEBUG_CLI] TTS playback error: {e}")
            finally:
                if held:
                    MIC.release()
                if tmp_path:
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        logging.getLogger(__name__).warning("Operation failed", exc_info=True)
            if ducked:
                music = self._music_lookup()
                if music:
                    music.unduck()
            self._queue.task_done()


# ════════════════════════════════════════════════════════════════
# VoiceRecorder — 按键录音器（RMS VAD + 静音自动停）
# ════════════════════════════════════════════════════════════════

class VoiceRecorder:
    def __init__(self, client):
        self.client = client
        self._recording = False
        self._frames: list[np.ndarray] = []
        self._sent_frames = None
        self._last_speech_time = 0.0
        self._start_time = 0.0
        self._recorder: Optional[PvRecorder] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._mic_held = False

    @staticmethod
    def _device_index() -> int:
        """从配置读取持久化的麦克风设备索引；无效/缺失时用默认设备 (-1)。"""
        from .config import load_config
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

        # 让闲置监听/音乐让出麦克风：持有仲裁 + 短暂等待，避免同设备双开冲突
        MIC.acquire()
        self._mic_held = True
        time.sleep(0.15)

        try:
            self._recorder = PvRecorder(device_index=self._device_index(), frame_length=512)
        except Exception as e:
            print(f"  Cannot open microphone: {e}")
            MIC.release()
            self._mic_held = False
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
            if self._mic_held:
                MIC.release()
                self._mic_held = False

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
# MusicPlayer — 音乐播放器（独立于 TTS 的 VLC 播放，由 webUI 远控）
# ════════════════════════════════════════════════════════════════

class MusicPlayer:
    def __init__(self, client, uid: int):
        self.client = client
        self.uid = uid
        self.playlist: list[dict] = []
        self.current_index = -1
        self.state: str = "stopped"
        self._volume = 0.7
        self._temp_files: list[str] = []
        self._running = False
        self._poll_thread: Optional[threading.Thread] = None
        self._prev_volume = self._volume
        self._player = None
        self._mic_held = False
        if HAS_AUDIO and VLC_INSTANCE:
            self._player = VLC_INSTANCE.media_player_new()

    def _hold_mic(self, hold: bool):
        """播放期间持有麦克风仲裁（闲置监听不录自己的音乐）。"""
        if hold and not self._mic_held:
            MIC.acquire()
            self._mic_held = True
        elif not hold and self._mic_held:
            MIC.release()
            self._mic_held = False

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
            resp = self.client._session.get(url, stream=True, timeout=10,
                                            headers=self.client._headers())
            if resp.status_code != 200:
                log.warning("MusicPlayer: 下载失败 %d", resp.status_code)
                return
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
            self._hold_mic(True)
            self._report_state()
        except Exception as e:
            log.warning("MusicPlayer: 播放失败 %s", e)

    def toggle(self):
        try:
            if self.state == "playing" and self._player:
                self._player.pause()
                self.state = "paused"
                self._hold_mic(False)
            elif self.state == "paused" and self._player:
                self._player.play()
                self.state = "playing"
                self._hold_mic(True)
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
        self._hold_mic(False)
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
        while self._running:
            time.sleep(1.5)
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
