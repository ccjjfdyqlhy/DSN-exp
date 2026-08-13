# tracking/media.py
# MediaManager — 用户跟踪系统的多模态媒体 / 文件落盘管理（infra）。
#
# 这是"个人行为日记本"的媒体底座：统一管理 拍照 / 录像 / 录音 / 任意文件 的保存目录，
# 按用户隔离（media/<uid>/<date>/<kind>/...），保证每位用户的媒体互不可见。
#
# 依赖 opencv-python（拍照/录像）与 numpy（录音 PCM→WAV）。二者缺失时相关能力降级，
# 但文件/文本记录不受影响。

from __future__ import annotations

import io
import logging
import os
import shutil
import threading
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("tracking.media")

# 默认保存根目录（可被环境变量覆盖）
DEFAULT_ROOT = Path(os.environ.get("TRACKING_MEDIA_ROOT", ".dsn/tracking_media"))


class MediaManager:
    """多模态媒体落盘管理器。

    用法：
        mm = MediaManager(root=..., uid=1)
        path = mm.save_audio(pcm_array)          # 录音
        path = mm.capture_photo()                # 拍照
        path = mm.capture_video(duration=3.0)    # 录像
        path = mm.save_file(data, "doc.md")      # 任意文件
        path = mm.alloc_path("text", ".md")      # 仅分配路径（文本由调用方写）
    """

    def __init__(self, root: Optional[Path] = None, uid: int = 0):
        self._root = Path(root) if root else DEFAULT_ROOT
        self._uid = int(uid or 0)
        self._lock = threading.Lock()
        self._root.mkdir(parents=True, exist_ok=True)

    # ── 基础 ──
    def user_root(self) -> Path:
        """当前用户的媒体根目录：<root>/<uid>"""
        p = self._root / str(self._uid)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def alloc_path(self, kind: str, ext: str, uid: Optional[int] = None) -> Path:
        """为指定媒体类型分配一个唯一路径：<root>/<uid>/<date>/<kind>/<kind>_<ts>.<ext>"""
        u = int(uid) if uid is not None else self._uid
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        date_dir = self._root / str(u) / datetime.now().strftime("%Y%m%d")
        sub = date_dir / kind
        sub.mkdir(parents=True, exist_ok=True)
        ext = ext.lstrip(".") if ext else "bin"
        return sub / f"{kind}_{ts}.{ext}"

    # ── 拍照 ──
    def capture_photo(self, uid: Optional[int] = None) -> dict:
        """拍摄一张照片保存为 jpg。返回 {ok, path, width, height, error}。"""
        try:
            import cv2
        except ImportError:
            return {"ok": False, "error": "opencv-python 未安装"}
        if not self._lock.acquire(blocking=False):
            return {"ok": False, "error": "相机被占用"}
        try:
            cap = cv2.VideoCapture(int(os.environ.get("DSN_CAMERA_DEVICE_ID", "0")))
            if not cap.isOpened():
                return {"ok": False, "error": "无法打开摄像头"}
            try:
                ok, frame = cap.read()
                if not ok or frame is None:
                    return {"ok": False, "error": "抓帧失败"}
                path = self.alloc_path("photo", "jpg", uid=uid)
                cv2.imwrite(str(path), frame)
                h, w = frame.shape[:2]
                logger.info("MediaManager: 拍照 %s (%dx%d)", path, w, h)
                return {"ok": True, "path": str(path), "width": w, "height": h}
            finally:
                cap.release()
        except Exception as e:
            logger.warning("MediaManager: 拍照失败 %s", e)
            return {"ok": False, "error": str(e)}
        finally:
            self._lock.release()

    # ── 录像 ──
    def capture_video(self, duration: float = 3.0, fps: int = 20,
                      uid: Optional[int] = None) -> dict:
        """录制一段视频（mp4）。返回 {ok, path, frames, duration, error}。"""
        try:
            import cv2
        except ImportError:
            return {"ok": False, "error": "opencv-python 未安装"}
        duration = max(0.5, float(duration))
        fps = max(1, int(fps))
        if not self._lock.acquire(blocking=False):
            return {"ok": False, "error": "相机被占用"}
        try:
            cap = cv2.VideoCapture(int(os.environ.get("DSN_CAMERA_DEVICE_ID", "0")))
            if not cap.isOpened():
                return {"ok": False, "error": "无法打开摄像头"}
            try:
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                path = self.alloc_path("video", "mp4", uid=uid)
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                writer = cv2.VideoWriter(str(path), fourcc, fps, (w, h))
                frames = 0
                start = time.time()
                while time.time() - start < duration:
                    ok, frame = cap.read()
                    if not ok or frame is None:
                        break
                    writer.write(frame)
                    frames += 1
                writer.release()
                if frames == 0:
                    path.unlink(missing_ok=True)
                    return {"ok": False, "error": "未录到有效帧"}
                logger.info("MediaManager: 录像 %s (%d 帧, %.1fs)",
                            path, frames, time.time() - start)
                return {"ok": True, "path": str(path), "frames": frames,
                        "duration": round(time.time() - start, 2)}
            finally:
                cap.release()
        except Exception as e:
            logger.warning("MediaManager: 录像失败 %s", e)
            return {"ok": False, "error": str(e)}
        finally:
            self._lock.release()

    # ── 录音：PCM 数组 → WAV ──
    def save_audio(self, samples, sample_rate: int = 16000,
                   uid: Optional[int] = None) -> Optional[str]:
        """把音频样本（np.float32/int16 数组）保存为 WAV，返回路径；失败返回 None。

        支持传入 bytes（已编码 WAV）直接落盘，无需 numpy。
        """
        path = self.alloc_path("audio", "wav", uid=uid)
        try:
            if isinstance(samples, bytes):
                path.write_bytes(samples)
                logger.info("MediaManager: 录音 %s (%d bytes)", path, len(samples))
                return str(path)
            try:
                import numpy as np
            except ImportError:
                logger.warning("MediaManager: numpy 未安装，无法从样本数组保存录音")
                return None
            arr = np.asarray(samples, dtype=np.float32)
            int_samples = np.clip(arr * 32767, -32768, 32767).astype(np.int16)
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(int_samples.tobytes())
            path.write_bytes(buf.getvalue())
            logger.info("MediaManager: 录音 %s (%.1fs @ %dHz)",
                        path, len(int_samples) / sample_rate, sample_rate)
            return str(path)
        except Exception as e:
            logger.warning("MediaManager: 保存录音失败 %s", e)
            return None

    # ── 任意文件 ──
    def save_file(self, data, filename: str, kind: str = "file",
                  uid: Optional[int] = None) -> Optional[str]:
        """保存任意文件（bytes 或 str 内容）。filename 决定扩展名，kind 决定目录。"""
        if isinstance(data, str):
            data = data.encode("utf-8")
        ext = Path(filename).suffix or ".bin"
        path = self.alloc_path(kind, ext, uid=uid)
        try:
            path.write_bytes(data)
            logger.info("MediaManager: 保存文件 %s (%d bytes)", path, len(data))
            return str(path)
        except Exception as e:
            logger.warning("MediaManager: 保存文件失败 %s", e)
            return None

    # ── 文件复制入库 ──
    def import_file(self, src: str, kind: str = "file",
                    uid: Optional[int] = None) -> Optional[str]:
        """把已有文件复制进用户媒体库。返回新路径；失败返回 None。"""
        src_p = Path(src)
        if not src_p.exists():
            return None
        ext = src_p.suffix or ".bin"
        path = self.alloc_path(kind, ext, uid=uid)
        try:
            shutil.copy2(str(src_p), str(path))
            logger.info("MediaManager: 导入文件 %s <- %s", path, src_p)
            return str(path)
        except Exception as e:
            logger.warning("MediaManager: 导入文件失败 %s", e)
            return None
