# apps/dsn/CLI/checkin.py
# CheckinRecorder — 打卡录制器。
# 基于 tracking 子系统：按下按键 → 用"AI 备注为主摄像头"录像 + 麦克风录音
# → 再按停止 → 上传后端 /api/checkin/record 合并存档 + ASR 写 tracking 日志。
#
# 从原 psychoscope/minimal.py 抽出（2092-2315）。
# 录制期间持有 audio.MIC 仲裁（闲置监听让出）。

from __future__ import annotations

import os
import tempfile
import threading
import time
from typing import Optional

import numpy as np

from .audio import MIC, VoiceRecorder, _play_beep, raw_pcm_to_wav_bytes
from .camera import _open_camera
from .env import HAS_CAMERA, HAS_PVRECORDER, PvRecorder, cv2, log


class CheckinRecorder:
    def __init__(self, client):
        self._client = client
        self._recording = False
        self._cap: Optional[object] = None
        self._writer = None
        self._recorder: Optional[PvRecorder] = None
        self._audio_frames: list[np.ndarray] = []
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._camera_device = -1
        self._frame_size = (640, 480)
        self._fps = 20
        self._video_tmp: Optional[str] = None
        self._audio_tmp: Optional[str] = None
        # 真实录制统计（用于后端修正视频时长，避免"视频比实际短"）
        self._start_ts = 0.0
        self._frame_count = 0
        self._mic_held = False

    @property
    def is_recording(self) -> bool:
        return self._recording

    @staticmethod
    def _resolve_primary_camera(client) -> int:
        """选择打卡用主摄像头（AI 备注为主/面向用户的），否则回退 CAMERA_DEVICE_ID。

        优先：后端已登记摄像头中备注含"主"/"用户"/"正面"者；其次 CAMERA_DEVICE_ID。
        """
        from .camera import CAMERA_DEVICE_ID
        primary = CAMERA_DEVICE_ID
        try:
            resp = client._http_get("/api/vision/cameras", timeout=8)
            if resp.status_code == 200:
                for c in resp.json().get("cameras", []):
                    note = (c.get("note") or "").lower()
                    if any(k in note for k in ("主", "用户", "正面", "正对")):
                        idx = c.get("index")
                        if isinstance(idx, int) and idx >= 0:
                            primary = idx
                            break
        except Exception:
            log.warning("解析主摄像头失败，回退 CAMERA_DEVICE_ID", exc_info=True)
        return primary

    def start(self):
        if self._recording:
            return
        if not HAS_CAMERA:
            print("  opencv-python 未安装，无法录像打卡")
            return
        if not HAS_PVRECORDER:
            print("  pvrecorder 未安装，无法录音打卡")
            return

        # 让闲置监听/音乐让出麦克风
        MIC.acquire()
        self._mic_held = True
        time.sleep(0.15)

        device = self._resolve_primary_camera(self._client)
        self._camera_device = device
        cap = _open_camera(device)
        if not cap or not cap.isOpened():
            print(f"  无法打开主摄像头 device{device}")
            MIC.release()
            self._mic_held = False
            return
        self._cap = cap

        try:
            self._recorder = PvRecorder(device_index=VoiceRecorder._device_index(), frame_length=512)
        except Exception as e:
            print(f"  无法打开麦克风: {e}")
            cap.release()
            MIC.release()
            self._mic_held = False
            return

        # 准备临时视频/音频文件
        _tmpdir = tempfile.gettempdir()
        ts = time.strftime("%Y%m%d_%H%M%S")
        self._video_tmp = os.path.join(_tmpdir, f"checkin_video_{ts}.mp4")
        self._audio_tmp = os.path.join(_tmpdir, f"checkin_audio_{ts}.wav")

        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 640)
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 480)
        self._frame_size = (w, h)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        self._writer = cv2.VideoWriter(self._video_tmp, fourcc, self._fps, (w, h))

        self._audio_frames = []
        self._stop_event.clear()
        self._start_ts = time.time()
        self._frame_count = 0
        self._recording = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        print(f"\n  📌 打卡录制中... (再按一次停止)  cam={device}")
        _play_beep(self._client, 880)

    def stop(self):
        if not self._recording:
            return
        self._recording = False
        self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        try:
            if self._writer:
                self._writer.release()
            if self._cap:
                self._cap.release()
            if self._recorder:
                self._recorder.stop()
                self._recorder.delete()
        except Exception:
            log.warning("停止打卡录制失败", exc_info=True)
        self._recorder = None
        self._writer = None
        self._cap = None
        if self._mic_held:
            MIC.release()
            self._mic_held = False

        # 收集音频帧 → WAV 临时文件
        audio_wav = b""
        if self._audio_frames:
            try:
                audio = np.concatenate(self._audio_frames)
                audio_wav = raw_pcm_to_wav_bytes(audio)
                with open(self._audio_tmp, "wb") as f:
                    f.write(audio_wav)
            except Exception:
                log.warning("保存打卡音频失败", exc_info=True)

        video_ok = os.path.exists(self._video_tmp) and os.path.getsize(self._video_tmp) > 0
        audio_ok = bool(audio_wav) and os.path.exists(self._audio_tmp)

        if not video_ok and not audio_ok:
            print("  打卡录制过短，忽略")
            self._cleanup_tmp()
            return

        # 计算真实录制时长与视频实际帧率（供后端修正视频时长）
        real_duration = max(0.0, time.time() - self._start_ts)
        actual_fps = self._frame_count / real_duration if real_duration > 0.1 else float(self._fps)

        _play_beep(self._client, 440)
        print(f"  正在上传打卡... (录 {real_duration:.1f}s, 实际fps≈{actual_fps:.1f})")
        self._upload(video_ok, audio_ok, duration=real_duration, fps=actual_fps)
        self._cleanup_tmp()

    def _capture_loop(self):
        # 以节拍控制摄像头读取，尽量贴近目标 fps；同时持续读麦克风
        frame_interval = 1.0 / max(1, self._fps)
        next_frame_ts = time.time()
        try:
            self._recorder.start()
            while self._recording and not self._stop_event.is_set():
                # 麦克风帧（不阻塞视频节拍）
                try:
                    pf = self._recorder.read()
                    samples = np.array(pf, dtype=np.int16).astype(np.float32) / 32768.0
                    self._audio_frames.append(samples)
                except Exception:
                    pass
                # 摄像头按节拍读帧
                now = time.time()
                if now >= next_frame_ts:
                    ok, frame = self._cap.read()
                    if ok and self._writer:
                        self._writer.write(frame)
                        self._frame_count += 1
                    next_frame_ts = now + frame_interval
        except Exception:
            log.warning("打卡录制循环异常", exc_info=True)
        finally:
            try:
                self._recorder.stop()
            except Exception:
                log.warning("打卡录音停止失败", exc_info=True)

    def _upload(self, has_video: bool, has_audio: bool,
                duration: float = 0.0, fps: float = 0.0):
        if not self._client.api_key:
            print("  未登录，无法上传打卡")
            return
        files = {}
        try:
            if has_video:
                files["video"] = open(self._video_tmp, "rb")
            if has_audio:
                files["audio"] = open(self._audio_tmp, "rb")
            data = {}
            if duration > 0:
                data["duration"] = str(round(duration, 2))
            if fps > 0:
                data["fps"] = str(round(fps, 2))
            resp = self._client._session.post(
                f"{self._client.base}/api/checkin/record",
                headers=self._client._headers(),
                files=files, data=data, timeout=60,
            )
            if resp.status_code == 200:
                data = resp.json()
                today = data.get("today_checkin_time", "")
                print(f"  ✅ 今日已打卡 {today}  ({data.get('checkin_date','')})")
                if data.get("text"):
                    print(f"     ASR: {data['text'][:60]}")
            else:
                print(f"  打卡上传失败 HTTP {resp.status_code}: {resp.text[:120]}")
        except Exception as e:
            log.warning("打卡上传失败: %s", e)
            print(f"  打卡上传异常: {e}")
        finally:
            for f in files.values():
                try:
                    f.close()
                except Exception:
                    pass

    def _cleanup_tmp(self):
        for p in (self._video_tmp, self._audio_tmp):
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    log.warning("清理打卡临时文件失败", exc_info=True)
