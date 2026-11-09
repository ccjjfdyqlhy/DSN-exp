# apps/dsn_study_cli/camera.py
# 摄像头 —— 枚举 / 逻辑名映射 / 抓帧 / JPEG q75 data URL。
#
# 逻辑名规则（与 dsn CLI 一致）：
#   1. 显式映射优先：环境变量 STUDY_CAMERA_MAP 或配置 camera_map，
#      格式 "name=idx,name=idx"（如 "doc=2"）—— **推荐用来钉死摄像头 2**，
#      免受枚举顺序漂移影响；
#   2. 其余按枚举顺序填空位 cam0, cam1, ...（0-based）。
# 「摄像头 2」的两种语义：枚举顺序第 2 台 = cam1；cv2 设备索引 2 = 显式钉住。
# 服务端只认 logical_name 字符串，index 只是元数据。

from __future__ import annotations

import base64
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from apps.dsn_study_cli.env import HAS_CAMERA

logger = logging.getLogger("study_cli.camera")

ENUM_TIMEOUT = 5.0            # 枚举整体超时（秒）
ENUM_MAX_PROBE = 8            # 最多探测 /dev/video0..7
_FRAME_CACHE_MAX_AGE = 3.0    # 帧缓存有效期（秒）

_CAMERA_LOCK = threading.Lock()
_CAMERA_SCAN_LOCK = threading.Lock()
_CAMERA_SCAN_DONE = False
_CAMERA_LIST: list[dict] = []          # [{index, name, logical_name, backend}]
_CAMERA_NAME_TO_INDEX: dict[str, int] = {}
_CAPTURE_LOCKS: dict[int, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()
_FRAME_CACHE: dict[int, tuple[float, str]] = {}   # device_id -> (ts, data_url)


def _default_backends() -> list:
    import cv2
    return [cv2.CAP_V4L2, cv2.CAP_FFMPEG, 0]   # linux


def _parse_camera_map(raw: str) -> dict[str, int]:
    """解析 "cam1=2,doc=3" → {"cam1": 2, "doc": 3}。非法对跳过。"""
    mapping: dict[str, int] = {}
    for pair in (raw or "").split(","):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        name, _, idx = pair.partition("=")
        try:
            mapping[name.strip()] = int(idx.strip())
        except ValueError:
            continue
    return mapping


def get_camera_map(cfg: dict | None = None) -> dict[str, int]:
    """显式映射：环境变量 STUDY_CAMERA_MAP 优先，其次配置文件。"""
    env_map = _parse_camera_map(os.environ.get("STUDY_CAMERA_MAP", ""))
    if env_map:
        return env_map
    cm = (cfg or {}).get("camera_map")
    if isinstance(cm, dict):
        return {str(k): int(v) for k, v in cm.items() if str(v).isdigit()}
    return {}


def _scan_devices() -> list[dict]:
    """逐索引探测可用设备（枚举与抓帧复用同一 backend）。"""
    import cv2
    found: dict[int, dict] = {}
    for idx in range(ENUM_MAX_PROBE):
        for backend in _default_backends():
            try:
                cap = cv2.VideoCapture(idx, backend)
                ok = cap.isOpened()
                if ok:
                    ok, _frame = cap.read()
                cap.release()
            except Exception:   # noqa: BLE001
                ok = False
            if ok:
                found[idx] = {"index": idx, "backend": int(backend)}
                break
    return list(found.values())


def _assign_logical_names(devices: list[dict], camera_map: dict[str, int]) -> list[dict]:
    """先按显式映射命名，其余按顺序填 cam0/cam1/... 的最小未占用空位。"""
    used: set[int] = set()
    out: list[dict] = []
    by_index = {d["index"]: d for d in devices}
    # 显式映射：名字绑定到实际打开成功的设备
    for name, idx in camera_map.items():
        if idx in by_index:
            by_index[idx]["logical_name"] = name
            used.add(idx)
    used_names = {d.get("logical_name") for d in devices}
    i = 0
    for d in devices:
        if d.get("logical_name"):
            continue
        while f"cam{i}" in used_names:
            i += 1
        d["logical_name"] = f"cam{i}"
        used_names.add(f"cam{i}")
        i += 1
        used.add(d["index"])
    for d in devices:
        d.setdefault("name", d.get("logical_name", ""))
        out.append(d)
    return out


def enumerate_cameras(cfg: dict | None = None, force: bool = False) -> list[dict]:
    """枚举摄像头（带 5s 超时保护；空/超时结果下次重扫）。"""
    global _CAMERA_SCAN_DONE, _CAMERA_LIST, _CAMERA_NAME_TO_INDEX
    if not HAS_CAMERA:
        return []
    with _CAMERA_SCAN_LOCK:
        if _CAMERA_SCAN_DONE and not force:
            return list(_CAMERA_LIST)
        result: list[dict] = []
        done = threading.Event()

        def _work():
            nonlocal result
            try:
                result = _assign_logical_names(_scan_devices(),
                                               get_camera_map(cfg))
            except Exception:   # noqa: BLE001
                result = []
            done.set()

        t = threading.Thread(target=_work, daemon=True)
        t.start()
        done.wait(timeout=ENUM_TIMEOUT)
        if done.is_set() and result:
            _CAMERA_LIST = result
            _CAMERA_NAME_TO_INDEX = {
                d["logical_name"]: d["index"] for d in result}
            _CAMERA_SCAN_DONE = True
            logger.info("枚举到 %d 台摄像头: %s", len(result),
                        [d["logical_name"] for d in result])
        else:
            logger.warning("摄像头枚举超时或无设备")
        return list(result)


def _lock_for(device_id: int) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _CAPTURE_LOCKS.get(device_id)
        if lock is None:
            lock = threading.Lock()
            _CAPTURE_LOCKS[device_id] = lock
        return lock


def resolve_camera(camera, cfg: dict | None = None) -> int:
    """解析逻辑名 → cv2 设备索引。None/""/default → 首台（映射优先）。"""
    if not HAS_CAMERA:
        return -1
    import cv2
    camera_map = get_camera_map(cfg)
    default_id = int(os.environ.get("STUDY_CAMERA_DEVICE_ID", "0"))
    if camera in (None, "", "all", "all_cameras", "default"):
        return (list(camera_map.values()) or [default_id])[0]
    name = str(camera)
    if name in camera_map:
        return camera_map[name]
    if name in _CAMERA_NAME_TO_INDEX:
        return _CAMERA_NAME_TO_INDEX[name]
    if name.isdigit():
        return int(name)
    return (list(camera_map.values()) or [default_id])[0]


def capture_frame(camera=None, cfg: dict | None = None,
                  use_cache: bool = True) -> str | None:
    """抓一帧 → JPEG q75 → base64 data URL。失败返回 None。"""
    if not HAS_CAMERA:
        return None
    import cv2
    import time as _time
    device_id = resolve_camera(camera, cfg)
    if device_id < 0:
        return None
    if use_cache:
        cached = _FRAME_CACHE.get(device_id)
        if cached and _time.time() - cached[0] < _FRAME_CACHE_MAX_AGE:
            return cached[1]
    with _lock_for(device_id):
        try:
            backend = None
            for d in _CAMERA_LIST:
                if d["index"] == device_id:
                    backend = d.get("backend")
                    break
            cap = (cv2.VideoCapture(device_id, backend)
                   if backend is not None else cv2.VideoCapture(device_id))
            ok, frame = cap.read()
            cap.release()
            if not ok or frame is None:
                return None
            ok2, buf = cv2.imencode(".jpg", frame,
                                    [int(cv2.IMWRITE_JPEG_QUALITY), 75])
            if not ok2:
                return None
            data_url = ("data:image/jpeg;base64,"
                        + base64.b64encode(buf.tobytes()).decode("ascii"))
            _FRAME_CACHE[device_id] = (_time.time(), data_url)
            return data_url
        except Exception:   # noqa: BLE001
            logger.warning("抓帧失败 device=%s", device_id, exc_info=True)
            return None


def capture_all_cameras(cfg: dict | None = None) -> list[dict]:
    """并行抓全部摄像头：[{logical_name, index, image_data}]。"""
    devices = enumerate_cameras(cfg)
    if not devices:
        return []

    def _one(d):
        return {"logical_name": d["logical_name"], "index": d["index"],
                "image_data": capture_frame(d["logical_name"], cfg) or ""}

    if len(devices) == 1:
        return [_one(devices[0])]
    with ThreadPoolExecutor(max_workers=min(len(devices), 4)) as ex:
        return list(ex.map(_one, devices))
