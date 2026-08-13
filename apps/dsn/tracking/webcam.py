# tracking/webcam.py
# WebCamManager — 远程网络摄像头接入层（infra）。
#
# 定位：把局域网/公网上的 IP 摄像头（RTSP / HTTP MJPEG / 快照 URL）注册进
#       视觉系统，使 AI 能像调用 minimal.py 连接的本地物理摄像头一样调用它们。
#
# 与本地物理摄像头的关系：
#   - 物理摄像头：设备在运行 minimal.py 的机器上，只能由本地客户端抓帧，
#                 后端通过「心跳下发 vision_request → 客户端抓帧回传」获取画面。
#   - 远程 webcam：网络可达，后端直接 cv2 抓帧（无需经过 minimal.py），
#                 产物与物理摄像头一致（base64 JPEG data URL），
#                 因此对上层 look_around / list_cameras / set_camera_note 完全透明。
#
# 管理方式：
#   1. 配置文件（默认 .dsn/webcams.json，可用 WEBCAM_CONFIG_PATH 覆盖）
#   2. 后端控制台命令 /webcam（add / remove / list / note / test / reload / snapshot）
#   3. REST API（/api/vision/webcams，见 api/vision.py）
#
# 配置（config.py）：
#   WEBCAM_CONFIG_PATH    配置文件路径（默认 .dsn/webcams.json）
#   WEBCAM_OPEN_TIMEOUT   打开流超时秒数（默认 5）
#   WEBCAM_FRAME_TIMEOUT  单帧抓取超时秒数（默认 8）
#   WEBCAM_MAX_FRAMES     并发抓帧的线程上限（默认 4）

from __future__ import annotations

import base64
import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("tracking.webcam")

# 远程摄像头的虚拟设备索引起点（远大于本地设备探测范围，避免冲突）
WEBCAM_INDEX_BASE = 10000

# 逻辑名允许的字符集（与控制台/REST 参数一致，避免特殊字符注入文件名/URL）
_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,48}$")

_DEFAULT_PATH = Path(os.environ.get("WEBCAM_CONFIG_PATH", ".dsn/webcams.json"))


def _sanitize_name(name: str) -> str:
    """清洗逻辑名：去空白、仅保留安全字符。非法返回 None。"""
    name = (name or "").strip()
    if not _NAME_RE.match(name):
        return ""
    return name


class WebCam:
    """单台远程摄像头条目。"""

    def __init__(self, url: str, logical_name: str = "", note: str = "",
                 index: Optional[int] = None, enabled: bool = True,
                 created_at: str = ""):
        self.url = (url or "").strip()
        self.logical_name = logical_name or ""
        self.note = note or ""
        self.index = index if index is not None else WEBCAM_INDEX_BASE
        self.enabled = bool(enabled)
        self.created_at = created_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def to_dict(self) -> dict:
        return {
            "logical_name": self.logical_name,
            "url": self.url,
            "note": self.note,
            "index": self.index,
            "enabled": self.enabled,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WebCam":
        return cls(
            url=str(d.get("url", "")),
            logical_name=str(d.get("logical_name", "")),
            note=str(d.get("note", "")),
            index=int(d.get("index") or WEBCAM_INDEX_BASE),
            enabled=bool(d.get("enabled", True)),
            created_at=str(d.get("created_at", "")),
        )

    def redacted_url(self) -> str:
        """隐藏 URL 中的认证凭据（rtsp://user:pass@host → rtsp://***@host）。"""
        try:
            return re.sub(r"://([^:@/]+):([^@/]+)@", r"://\1:***@", self.url)
        except Exception:
            return self.url


class WebCamManager:
    """远程摄像头注册表：持久化 JSON 配置 + CRUD + cv2 抓帧。线程安全。

    用法：
        mgr = WebCamManager()                 # 自动从默认路径加载
        mgr.add("rtsp://192.168.1.50:554/1", name="door", note="门口")
        mgr.list()
        mgr.remove("door")
        data_url = mgr.capture_frame("door")  # "data:image/jpeg;base64,..."
    """

    def __init__(self, path: Optional[str] = None,
                 open_timeout: Optional[float] = None,
                 frame_timeout: Optional[float] = None,
                 max_workers: Optional[int] = None):
        self.path = Path(path) if path else _DEFAULT_PATH
        from apps.dsn.config import Config
        self._open_timeout = open_timeout or float(getattr(Config, "WEBCAM_OPEN_TIMEOUT", 5))
        self._frame_timeout = frame_timeout or float(getattr(Config, "WEBCAM_FRAME_TIMEOUT", 8))
        self._max_workers = max_workers or int(getattr(Config, "WEBCAM_MAX_FRAMES", 4))
        self._lock = threading.Lock()
        self._cameras: dict[str, WebCam] = {}
        self._grab_guard = threading.Lock()   # 串行化抓帧，避免多线程同时开流压垮设备
        self.load()

    # ── 持久化 ──

    def load(self) -> bool:
        """从配置文件加载摄像头列表。文件缺失/损坏时回退为空列表。"""
        try:
            if not self.path.exists():
                self._cameras = {}
                return True
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            entries = raw.get("cameras", raw) if isinstance(raw, dict) else raw
            cams: dict[str, WebCam] = {}
            for e in entries or []:
                if not isinstance(e, dict):
                    continue
                cam = WebCam.from_dict(e)
                if not cam.logical_name or not cam.url:
                    continue
                cams[cam.logical_name] = cam
            with self._lock:
                self._cameras = cams
            logger.info("WebCamManager: 已加载 %d 个远程摄像头 (%s)", len(cams), self.path)
            return True
        except Exception:
            logger.warning("WebCamManager: 加载配置失败，使用空列表 (%s)", self.path, exc_info=True)
            with self._lock:
                self._cameras = {}
            return False

    def save(self) -> bool:
        """把当前列表持久化到配置文件。"""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                entries = [c.to_dict() for c in self._cameras.values()]
            data = {"version": 1, "updated_at": datetime.now().isoformat(timespec="seconds"),
                    "cameras": entries}
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)
            return True
        except Exception:
            logger.warning("WebCamManager: 保存配置失败 (%s)", self.path, exc_info=True)
            return False

    # ── 查询 ──

    def list(self) -> list[dict]:
        """返回全部摄像头（含 URL，凭据已打码到 redacted_url）。"""
        with self._lock:
            items = [c.to_dict() for c in sorted(self._cameras.values(), key=lambda c: c.index)]
        for it in items:
            it["redacted_url"] = self._redact(it.get("url", ""))
        return items

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._cameras.keys())

    def get(self, name: str) -> Optional[WebCam]:
        with self._lock:
            return self._cameras.get(name)

    def is_webcam(self, name: str) -> bool:
        return self.get(name) is not None

    def has_webcams(self) -> bool:
        with self._lock:
            return bool(self._cameras)

    def count(self) -> int:
        with self._lock:
            return len(self._cameras)

    @staticmethod
    def _redact(url: str) -> str:
        return re.sub(r"://([^:@/]+):([^@/]+)@", r"://\1:***@", url)

    # ── 管理操作 ──

    def add(self, url: str, name: str = "", note: str = "", test: bool = True) -> dict:
        """添加一台远程摄像头。

        :param url:  支持 rtsp:// / http(s):// (MJPEG 或单帧快照) / 本地文件等 cv2 可打开的源
        :param name: 逻辑名；缺省自动分配 webcam0/webcam1...
        :param note: 备注（位置/用途）
        :param test: 是否先做连通性测试（打开 + 抓一帧），失败则不添加
        :return: {ok, ...} 或 {ok: False, error}
        """
        url = (url or "").strip()
        if not url:
            return {"ok": False, "error": "缺少摄像头 URL"}
        if not url.lower().startswith(("rtsp://", "rtspx://", "rtsps://",
                                       "http://", "https://", "rtmp://")):
            return {"ok": False, "error": "URL 需以 rtsp:// 或 http(s):// 开头"}

        if name:
            name = _sanitize_name(name)
            if not name:
                return {"ok": False, "error": "逻辑名仅允许字母/数字/_/-（≤48 字符）"}
        else:
            name = self._auto_name()
        if self.get(name):
            return {"ok": False, "error": f"逻辑名 {name} 已存在"}

        if test:
            res = self.test(url)
            if not res.get("ok"):
                return {"ok": False, "error": f"连通性测试失败: {res.get('error', '无法打开')}"}

        with self._lock:
            idx = WEBCAM_INDEX_BASE
            used = {c.index for c in self._cameras.values()}
            while idx in used:
                idx += 1
            cam = WebCam(url=url, logical_name=name, note=note, index=idx)
            self._cameras[name] = cam
        if not self.save():
            logger.warning("WebCamManager: add 后保存失败（内存仍生效）")
        logger.info("WebCamManager: 已添加远程摄像头 %s (%s)", name, self._redact(url))
        return {"ok": True, "logical_name": name, "camera": cam.to_dict()}

    def remove(self, name: str) -> dict:
        """删除指定逻辑名的摄像头。"""
        name = (name or "").strip()
        with self._lock:
            if name not in self._cameras:
                return {"ok": False, "error": f"远程摄像头 {name} 不存在"}
            del self._cameras[name]
        self.save()
        logger.info("WebCamManager: 已删除远程摄像头 %s", name)
        return {"ok": True, "logical_name": name}

    def set_note(self, name: str, note: str) -> dict:
        """写/改备注。"""
        name = (name or "").strip()
        with self._lock:
            cam = self._cameras.get(name)
            if not cam:
                return {"ok": False, "error": f"远程摄像头 {name} 不存在"}
            cam.note = (note or "").strip()
        self.save()
        return {"ok": True, "logical_name": name, "note": cam.note}

    def set_enabled(self, name: str, enabled: bool) -> dict:
        """启用/禁用（禁用的摄像头不出现在列表、不参与抓帧）。"""
        name = (name or "").strip()
        with self._lock:
            cam = self._cameras.get(name)
            if not cam:
                return {"ok": False, "error": f"远程摄像头 {name} 不存在"}
            cam.enabled = bool(enabled)
        self.save()
        return {"ok": True, "logical_name": name, "enabled": cam.enabled}

    def _auto_name(self) -> str:
        with self._lock:
            n = 0
            while f"webcam{n}" in self._cameras:
                n += 1
            return f"webcam{n}"

    # ── 连通性测试 / 抓帧 ──

    def test(self, url: str) -> dict:
        """尝试打开并抓一帧，验证流可用。返回 {ok, width, height, error}。"""
        result: dict = {"ok": False}
        frame = self._grab_from_url(url, timeout=self._frame_timeout, meta=result)
        if frame is None:
            result["error"] = result.get("error") or "无法从该地址获取画面"
            return result
        result["ok"] = True
        return result

    def capture_frame(self, name: str) -> Optional[str]:
        """抓取指定摄像头一帧，返回 base64 data URL；失败返回 None。

        在线程中执行打开+读帧，外层等待 WEBCAM_FRAME_TIMEOUT 秒——
        cv2 打开 RTSP 在部分设备/网络上可能长时间阻塞，超时后直接放弃，
        保证上层（look_around 的 8 秒窗口）不会因此卡死。
        """
        cam = self.get(name)
        if not cam or not cam.enabled:
            return None
        return self._grab_from_url(cam.url, timeout=self._frame_timeout)

    def capture_frames(self, names: list[str]) -> tuple[dict[str, str], list[str]]:
        """并行抓取多台摄像头。

        :return: (frames: {logical_name: data_url}, failed: [logical_name, ...])
        """
        frames: dict[str, str] = {}
        failed: list[str] = []
        names = [n for n in (names or []) if self.is_webcam(n)]
        if not names:
            return frames, failed
        if len(names) == 1:
            n = names[0]
            f = self.capture_frame(n)
            if f:
                frames[n] = f
            else:
                failed.append(n)
            return frames, failed

        import concurrent.futures
        workers = min(len(names), max(1, self._max_workers))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers,
                                                   thread_name_prefix="webcam-grab") as ex:
            future_map = {ex.submit(self.capture_frame, n): n for n in names}
            for fut in concurrent.futures.as_completed(future_map):
                n = future_map[fut]
                try:
                    f = fut.result()
                    if f:
                        frames[n] = f
                    else:
                        failed.append(n)
                except Exception as e:
                    failed.append(n)
                    logger.warning("WebCamManager: 抓帧异常 %s: %s", n, e)
        return frames, failed

    def snapshot(self, name: str, save_dir) -> Optional[str]:
        """抓一帧并保存为 JPEG 文件，返回文件路径；失败返回 None。"""
        data_url = self.capture_frame(name)
        if not data_url:
            return None
        try:
            header, _, b64 = data_url.partition(",")
            if not b64:
                return None
            raw = base64.b64decode(b64)
            save_dir = Path(save_dir)
            save_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            path = save_dir / f"webcam_{name}_{ts}.jpg"
            path.write_bytes(raw)
            logger.info("WebCamManager: 快照已保存 %s", path)
            return str(path)
        except Exception as e:
            logger.warning("WebCamManager: 快照保存失败 %s: %s", name, e)
            return None

    def _grab_from_url(self, url: str, timeout: Optional[float] = None,
                       meta: Optional[dict] = None) -> Optional[str]:
        """核心抓帧：在线程中 cv2 打开 URL → 读一帧 → JPEG q75 → base64 data URL。

        :param meta: 可选 dict，成功后写入 {"width": w, "height": h}，失败写入 {"error": ...}
        """
        if not url:
            return None
        timeout = timeout or self._frame_timeout
        holder: dict = {}
        done = threading.Event()

        def _work():
            try:
                import cv2
            except ImportError:
                holder["error"] = "opencv-python 未安装"
                done.set()
                return
            cap = None
            try:
                with self._grab_guard:
                    cap = cv2.VideoCapture(url)
                    # 仅在支持时设置超时（OpenCV ≥4.5.4）
                    try:
                        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, int(timeout * 1000))
                        cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, int(timeout * 1000))
                    except Exception:
                        pass
                    if not cap.isOpened():
                        holder["error"] = "无法打开流"
                        return
                    ok, frame = cap.read()
                    if not ok or frame is None:
                        holder["error"] = "读取画面失败"
                        return
                    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                    if not ok:
                        holder["error"] = "JPEG 编码失败"
                        return
                    h, w = frame.shape[:2]
                    holder["frame"] = ("data:image/jpeg;base64," +
                                       base64.b64encode(buf.tobytes()).decode("utf-8"))
                    holder["width"] = w
                    holder["height"] = h
            except Exception as e:
                holder["error"] = str(e)
            finally:
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass
                done.set()

        t = threading.Thread(target=_work, daemon=True, name="webcam-frame")
        t.start()
        t.join(timeout=timeout + 2.0)   # 多留 2s 让线程能释放资源
        if "frame" not in holder:
            if meta is not None:
                meta["error"] = holder.get("error") or f"抓帧超时（>{timeout:.0f}s）"
            return None
        if meta is not None:
            meta["width"] = holder.get("width")
            meta["height"] = holder.get("height")
        return holder["frame"]
