# tracking/vision_capture.py
# VisionCapture — 用户跟踪系统的"感官捕捉"能力（infra）。
#
# 提供多模态采集原语：拍照 / 录像 / 录音（麦克风）。真正的媒体落盘统一交给
# MediaManager（tracking/media.py），本层只负责"从传感器采集"。
#
# 说明：拍照/录像/录音当前为 infra 能力；闲时感知（仅音频聆听）依赖
# AudioListeningMonitor，而主动录音由上层按需调用本层。

from __future__ import annotations

import logging
from typing import Optional

from .media import MediaManager

logger = logging.getLogger("tracking.vision_capture")


class VisionCapture:
    """多模态采集封装：拍照 / 录像 / 录音。

    用法：
        vc = VisionCapture(root=..., uid=1)
        vc.capture_photo()          # -> {"ok": True, "path": "..."}
        vc.capture_video(3.0)       # -> {"ok": True, "path": "..."}
        vc.capture_audio(5.0)       # -> {"ok": True, "path": "..."}
    """

    def __init__(self, root=None, uid: int = 0):
        self.media = MediaManager(root=root, uid=uid)

    # ── 拍照 ──
    def capture_photo(self, uid: Optional[int] = None) -> dict:
        return self.media.capture_photo(uid=uid)

    # ── 录像 ──
    def capture_video(self, duration: float = 3.0, fps: int = 20,
                      uid: Optional[int] = None) -> dict:
        return self.media.capture_video(duration=duration, fps=fps, uid=uid)

    # ── 录音（麦克风主动采集，保存为 WAV）──
    def capture_audio(self, duration: float = 5.0, sample_rate: int = 16000,
                      uid: Optional[int] = None) -> dict:
        """用麦克风录制一段音频并保存为 WAV。

        依赖 pvrecorder 读取 PCM + numpy 转浮点；缺失时返回错误。
        返回 {ok, path, duration, error}。
        """
        try:
            import numpy as np
        except ImportError:
            return {"ok": False, "error": "numpy 未安装"}
        try:
            from pvrecorder import PvRecorder
        except ImportError:
            return {"ok": False, "error": "pvrecorder 未安装"}

        duration = max(0.5, float(duration))
        frames: list = []
        recorder = None
        try:
            recorder = PvRecorder(device_index=-1, frame_length=512)
            recorder.start()
            end = __import__("time").time() + duration
            while __import__("time").time() < end:
                frame = recorder.read()
                samples = np.array(frame, dtype=np.int16).astype(np.float32) / 32768.0
                frames.append(samples)
        except Exception as e:
            logger.warning("VisionCapture: 录音失败 %s", e)
            return {"ok": False, "error": str(e)}
        finally:
            if recorder is not None:
                try:
                    recorder.stop()
                    recorder.delete()
                except Exception:
                    logger.warning("VisionCapture: 清理录音器失败", exc_info=True)

        if not frames:
            return {"ok": False, "error": "未采到音频"}
        audio = np.concatenate(frames) if len(frames) > 1 else frames[0]
        path = self.media.save_audio(audio, sample_rate=sample_rate, uid=uid)
        if not path:
            return {"ok": False, "error": "保存录音失败"}
        return {"ok": True, "path": path, "duration": round(duration, 2)}
