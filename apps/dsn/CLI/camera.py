# apps/dsn/CLI/camera.py
# 摄像头链路：枚举 / 后端选择 / 打开 / 抓帧 / 帧缓存 / 多摄并行 / 保存。
#
# 从原 psychoscope/minimal.py 抽出（74-262 设备管理 + 669-806 抓帧）。
# 模块级扫描状态（_CAMERA_*）与帧缓存（_FRAME_CACHE）随迁，对外接口不变。

from __future__ import annotations

import base64
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Optional

from .env import HAS_CAMERA, cv2, log

CAMERA_DEVICE_ID = int(os.environ.get("DSN_CAMERA_DEVICE_ID", "0"))

# 摄像头枚举整体超时（秒）——cv2 打开部分设备可能阻塞，超时后放弃剩余探测
ENUM_TIMEOUT = 5.0

# 逻辑名 → 设备索引的映射（可被环境变量覆盖，格式: cam0=0,cam1=2）
# 未配置时按枚举顺序自动分配 cam0, cam1, ...
_CAMERA_NAME_TO_INDEX: dict[str, int] = {}
_CAMERA_INDEX_TO_NAME: dict[int, str] = {}
_CAMERA_BACKEND: dict[int, int] = {}   # 设备索引 → 最佳 cv2 后端
_CAMERA_SCAN_DONE = False
_CAMERA_SCAN_LOCK = threading.Lock()


def _parse_camera_map(raw: str) -> dict[str, int]:
    if not raw:
        return {}
    result: dict[str, int] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        name, _, idx = pair.partition("=")
        try:
            result[name.strip()] = int(idx.strip())
        except ValueError:
            continue
    return result


def _enumerate_cameras(max_probe: int = 8) -> list[dict]:
    """枚举本机摄像头，返回 [{index, name, logical_name}]。
    通过尝试打开 cv2 设备判断可用性；探测上限 max_probe。
    整体有超时保护：cv2.VideoCapture 在部分驱动上可能长时间阻塞，
    在独立线程中执行并限定上限（ENUM_TIMEOUT 秒）。
    线程安全：并发调用时串行扫描；只有扫描完整完成且找到摄像头时才缓存结果，
    空/超时结果不缓存，下次调用会重新扫描。
    """
    global _CAMERA_NAME_TO_INDEX, _CAMERA_INDEX_TO_NAME, _CAMERA_SCAN_DONE
    if not HAS_CAMERA:
        return []
    with _CAMERA_SCAN_LOCK:
        if _CAMERA_SCAN_DONE:
            return [{"index": i, "name": n, "logical_name": nm}
                    for i, nm in sorted(_CAMERA_INDEX_TO_NAME.items())
                    for n in [f"cam{i}"]]

        result_holder: list = []
        done = threading.Event()

        def _scan():
            try:
                result_holder.extend(_scan_devices(max_probe))
            except Exception:
                log.warning("摄像头扫描异常", exc_info=True)
            finally:
                done.set()

        t = threading.Thread(target=_scan, daemon=True, name="cam-scan")
        t.start()
        scan_completed = done.wait(timeout=ENUM_TIMEOUT)
        devices = list(result_holder)

        env_map = _parse_camera_map(os.environ.get("DSN_CAMERA_MAP", ""))

        # 分配逻辑名：优先 env 映射，其余按顺序 cam0, cam1...
        used_names = set()
        _CAMERA_NAME_TO_INDEX = {}
        _CAMERA_INDEX_TO_NAME = {}
        _CAMERA_BACKEND.clear()
        for dev in devices:
            idx = dev["index"]
            logical = None
            for nm, mapped_idx in env_map.items():
                if mapped_idx == idx and nm not in used_names:
                    logical = nm
                    break
            if logical is None:
                i = 0
                while f"cam{i}" in used_names:
                    i += 1
                logical = f"cam{i}"
            used_names.add(logical)
            dev["logical_name"] = logical
            _CAMERA_NAME_TO_INDEX[logical] = idx
            _CAMERA_INDEX_TO_NAME[idx] = logical
            if dev.get("backend"):
                _CAMERA_BACKEND[idx] = dev["backend"]

        # 仅当扫描完整完成且找到设备时才缓存；否则留待下次重试
        if scan_completed and devices:
            _CAMERA_SCAN_DONE = True
        if devices:
            log.info("枚举到 %d 个摄像头: %s",
                     len(devices),
                     ", ".join(f"{d['logical_name']}=device{d['index']}" for d in devices))
        else:
            log.warning("本次扫描未检测到可用摄像头（completed=%s）", scan_completed)
        return devices


def _scan_devices(max_probe: int, backends: list | None = None) -> list[dict]:
    """在子线程中执行的实际设备探测（cv2 打开可能阻塞）。
    记录每个 index 的最佳可用后端，抓帧时复用同一后端（关键：枚举与抓帧后端不一致
    会导致 Windows 上 DSHOW/MSMF 冲突，出现 cam 打不开或抓帧失败）。
    :param backends: 可显式指定后端列表（测试用）；默认按平台推断。
    """
    if backends is None:
        backends = _default_backends()
    elif isinstance(backends, (list, tuple)):
        backends = list(backends)

    devices = []
    for idx in range(max_probe):
        for backend in backends:
            try:
                if backend:
                    cap = cv2.VideoCapture(idx, backend)
                else:
                    cap = cv2.VideoCapture(idx)
                opened = cap.isOpened()
                if opened:
                    devices.append({"index": idx, "name": f"cam{idx}", "backend": backend})
                    cap.release()
                    break
                try:
                    cap.release()
                except Exception:
                    pass
            except Exception:
                continue
    return devices


def _default_backends() -> list:
    """按平台返回默认的 cv2 摄像头后端候选列表。"""
    if sys.platform.startswith("linux"):
        return [getattr(cv2, "CAP_V4L2", 0), getattr(cv2, "CAP_FFMPEG", 0), 0]
    if sys.platform == "darwin":
        return [getattr(cv2, "CAP_AVFOUNDATION", 0), 0]
    if os.name == "nt":
        # DSHOW 优先，其次 MSMF，最后默认——部分摄像头只在特定后端可开
        return [getattr(cv2, "CAP_DSHOW", 0), getattr(cv2, "CAP_MSMF", 0), 0]
    return [0]


def _resolve_camera(camera: str) -> int:
    """把逻辑名（cam0/front）解析为设备索引；空或 'all' 返回主摄像头索引。"""
    if camera in (None, "", "all", "default"):
        return CAMERA_DEVICE_ID
    if not _CAMERA_SCAN_DONE and HAS_CAMERA:
        _enumerate_cameras()
    if camera in _CAMERA_NAME_TO_INDEX:
        return _CAMERA_NAME_TO_INDEX[camera]
    try:
        return int(camera)
    except (ValueError, TypeError):
        return CAMERA_DEVICE_ID


def _camera_backend_for(device_id: int) -> int:
    """返回指定设备的最佳 cv2 后端（枚举时记录），未知则 0（默认后端）。"""
    if _CAMERA_SCAN_DONE:
        return _CAMERA_BACKEND.get(device_id, 0)
    if HAS_CAMERA:
        _enumerate_cameras()
    return _CAMERA_BACKEND.get(device_id, 0)


def _open_camera(device_id: int):
    """用记录的最佳后端打开摄像头；无记录后端则用默认。"""
    backend = _camera_backend_for(device_id)
    if backend:
        return cv2.VideoCapture(device_id, backend)
    return cv2.VideoCapture(device_id)


# ── 摄像头设备级访问锁 ──
# StreamPusher（实时监控流）、VisionObserver（周期主动视觉）、心跳 on-demand
# 回传（look_around）可能并发抓帧。cv2.VideoCapture 对同一本地设备并发打开
# 经常失败/阻塞，导致抓帧失败、视频流断流。按 device_id 加锁串行化同一设备，
# 不同设备仍可并行抓帧。
_CAPTURE_LOCKS: dict[int, threading.Lock] = {}
_CAPTURE_LOCKS_GUARD = threading.Lock()


def _device_lock(device_id: int) -> threading.Lock:
    with _CAPTURE_LOCKS_GUARD:
        lock = _CAPTURE_LOCKS.get(device_id)
        if lock is None:
            lock = threading.Lock()
            _CAPTURE_LOCKS[device_id] = lock
        return lock


def _capture_camera_frame(camera: str | int | None = None) -> Optional[str]:
    """本地 cv2 抓一帧 → JPEG(q75) → base64 data URL。失败返回 None。

    支持逻辑名（cam0 / front）或设备索引；空则用主摄像头 CAMERA_DEVICE_ID。
    产物格式 ("data:image/jpeg;base64,...") 与后端 VisionModel 管道一致。
    成功抓帧后写入模块级帧缓存，供后续 on-demand 视觉请求零等待复用。
    """
    if not HAS_CAMERA:
        return None
    device_id = _resolve_camera(camera)
    try:
        with _device_lock(device_id):
            cap = _open_camera(device_id)
            if not cap.isOpened():
                log.warning("摄像头无法打开 (device_id=%s)", device_id)
                return None
            ret, frame = cap.read()
            cap.release()
        if not ret:
            log.warning("摄像头读取画面失败")
            return None
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if not ok:
            log.warning("JPEG 编码失败")
            return None
        data_url = "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("utf-8")
        _store_frame_cache(device_id, data_url)
        return data_url
    except Exception:
        log.warning("摄像头抓帧失败 (device_id=%s)", device_id, exc_info=True)
        return None


# ── 客户端帧缓存：缩短 on-demand 视觉请求的抓帧等待 ──
# key: device_id(int) → (ts, data_url)。抓帧开摄像头耗时较高（数百 ms 到 1s+），
# 心跳收到 vision_request 时优先复用新鲜缓存帧，避免每请求都重新开摄像头。
_FRAME_CACHE: dict[int, tuple[float, str]] = {}
_FRAME_CACHE_LOCK = threading.Lock()
FRAME_CACHE_MAX_AGE = float(os.environ.get("DSN_FRAME_CACHE_MAX_AGE", "3"))


def _store_frame_cache(device_id: int, data_url: str) -> None:
    with _FRAME_CACHE_LOCK:
        _FRAME_CACHE[device_id] = (time.time(), data_url)


def _cached_camera_frame(camera: str | int | None = None) -> Optional[str]:
    """返回缓存中仍新鲜的帧；无/过期则返回 None（由调用方决定是否现场抓帧）。"""
    if not HAS_CAMERA:
        return None
    device_id = _resolve_camera(camera)
    with _FRAME_CACHE_LOCK:
        entry = _FRAME_CACHE.get(device_id)
        if not entry:
            return None
        ts, data_url = entry
        if time.time() - ts > FRAME_CACHE_MAX_AGE:
            _FRAME_CACHE.pop(device_id, None)
            return None
        return data_url


def _capture_all_cameras() -> list[dict]:
    """枚举并逐台抓帧，返回 [{logical_name, index, image_data}]（只含抓帧成功的）。
    优先复用新鲜缓存帧；缺失/过期者现场抓帧（并行）。"""
    if not HAS_CAMERA:
        return []
    devices = _enumerate_cameras()
    if not devices:
        return []

    def _grab(dev: dict) -> Optional[dict]:
        idx = dev["index"]
        frame = _cached_camera_frame(idx)
        if frame is None:
            frame = _capture_camera_frame(idx)
        if not frame:
            return None
        return {
            "logical_name": dev["logical_name"],
            "index": idx,
            "image_data": frame,
        }

    if len(devices) <= 1:
        grabbed = [_grab(dev) for dev in devices]
    else:
        with ThreadPoolExecutor(max_workers=min(len(devices), 4),
                                thread_name_prefix="cam-capture") as ex:
            grabbed = list(ex.map(_grab, devices))
    return [g for g in grabbed if g]


def _capture_and_save_frame(camera, save_dir: Path) -> Optional[Path]:
    """抓一帧并保存为 JPEG 文件到 save_dir，返回保存路径；失败返回 None。"""
    if not HAS_CAMERA:
        return None
    device_id = _resolve_camera(camera)
    try:
        cap = _open_camera(device_id)
        if not cap.isOpened():
            log.warning("摄像头无法打开 (device_id=%s)", device_id)
            return None
        ret, frame = cap.read()
        cap.release()
        if not ret:
            log.warning("摄像头读取画面失败 (device_id=%s)", device_id)
            return None
        save_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = save_dir / f"camera_{device_id}_{ts}.jpg"
        ok = cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            log.warning("JPEG 写入失败: %s", path)
            return None
        return path
    except Exception:
        log.warning("摄像头抓帧保存失败 (device_id=%s)", device_id, exc_info=True)
        return None
