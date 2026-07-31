# api/vision.py
# 视觉感知协调层 — 桥接本地客户端(minimal.py)摄像头与后端 VisionModel/场景变化逻辑。
#
# 摄像头抓帧已迁移到本地客户端 minimal.py(本地 cv2)，后端只保留:
#   - VisionModel 多模态分析
#   - 场景变化检测 + 主动通知(task_notifications)
#   - PRE_PROCESS 注入(主动视觉插件)
#
# 多摄像头: 所有摄像头都连接在本地客户端上。首次视觉请求（camera="all"）
# 由客户端枚举+逐台抓帧，回传多帧；后端逐张给视觉模型，返回逻辑名+描述列表。
# 主 AI 可用 set_camera_note 给各摄像头写备注，之后可按逻辑名单独 look_around。
#
# 两条管线:
#   1. 周期性主动视觉:
#        minimal.py 定时 cv2 抓帧 → POST /api/vision/observation
#        → ActiveVisionPlugin.ingest_observation (VisionModel + 场景变化 + task_notifications)
#        → /api/heartbeat 拉取 → 主 LLM 决策 → 主动说话 + TTS
#
#   2. 按需 look_around:
#        Agent 调 look_around(camera=...) → VisionCoordinator.create_request (阻塞等待)
#        → /api/heartbeat 响应携带 vision_request(camera)
#        → minimal.py 抓帧(单/全) → POST /api/vision/frame
#        → 唤醒 look_around → VisionModel → 返回描述(超时则兜底)

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Optional

from flask import Blueprint, request, jsonify, g

logger = logging.getLogger("Vision")

vision_bp = Blueprint("vision_api", __name__)

_db = None
_engine = None
_auth_manager = None

# 模块级单例协调器（init_vision_api 时创建，被 skill/heartbeat 懒读取）
coordinator: Optional["VisionCoordinator"] = None


def init_vision_api(db=None, engine=None, auth_manager=None):
    """注入依赖并创建 VisionCoordinator 单例（boot.py 启动时调用）。"""
    global _db, _engine, _auth_manager, coordinator
    _db = db
    _engine = engine
    _auth_manager = auth_manager
    if coordinator is None:
        coordinator = VisionCoordinator()
    logger.info("Vision API 已初始化 (coordinator=%s)", type(coordinator).__name__)


class VisionCoordinator:
    """按需视觉请求的内存协调器（线程安全）。

    桥接同步的 look_around 调用与异步 heartbeat 轮询的本地客户端：
      - create_request: look_around 注册一条 pending 请求并阻塞 wait
      - pending_for_uid: heartbeat 用来查询是否有待响应请求（下发给客户端）
      - submit_frame: 客户端回传帧后唤醒阻塞的 look_around
      - wait: look_around 阻塞直到帧到达或超时
    """

    REQUEST_TIMEOUT = 20.0     # look_around 阻塞等待客户端帧的超时秒数
    _GC_MAX_AGE = 120.0        # 过期请求清理阈值

    def __init__(self):
        self._lock = threading.Lock()
        self._pending: dict[str, dict] = {}  # request_id -> {...}
        # 摄像头元数据: logical_name -> {index, note, last_seen}
        self._cameras: dict[str, dict] = {}
        self._camera_lock = threading.Lock()

    # === 摄像头元数据（客户端枚举上报 + 主AI备注） ===

    def register_cameras(self, cameras: list[dict]) -> None:
        """客户端枚举上报摄像头: [{logical_name, index, ...}]。"""
        with self._camera_lock:
            for c in cameras:
                name = c.get("logical_name", "")
                if not name:
                    continue
                entry = self._cameras.setdefault(name, {"index": None, "note": "", "last_seen": time.time()})
                entry["index"] = c.get("index", entry.get("index"))
                entry["last_seen"] = time.time()
        logger.info("已登记 %d 个摄像头: %s", len(cameras), [c.get("logical_name") for c in cameras])

    def list_cameras(self) -> list[dict]:
        with self._camera_lock:
            return [
                {"logical_name": name, "note": entry.get("note", ""),
                 "index": entry.get("index"), "last_seen": entry.get("last_seen")}
                for name, entry in sorted(self._cameras.items())
            ]

    def set_camera_note(self, name: str, note: str) -> bool:
        with self._camera_lock:
            if name not in self._cameras:
                self._cameras[name] = {"index": None, "note": "", "last_seen": time.time()}
            self._cameras[name]["note"] = note
        logger.info("摄像头备注已更新: %s → %s", name, note[:40])
        return True

    def list_cameras_note(self, name: str) -> str:
        with self._camera_lock:
            entry = self._cameras.get(name)
            return (entry or {}).get("note", "")

    # === 按需请求 ===

    def create_request(self, focus: str = "", uid: int = 0, camera: str = "") -> str:
        """创建一条 pending 按需视觉请求，返回 request_id。

        :param camera: 目标摄像头逻辑名；"all"/"all_cameras" 表示枚举全部；空=主摄像头。
        """
        request_id = f"vision_req_{uuid.uuid4().hex[:16]}"
        req = {
            "request_id": request_id,
            "uid": uid,
            "focus": focus,
            "camera": camera,
            "event": threading.Event(),
            "frames": {},           # logical_name -> base64 data URL
            "created_at": time.time(),
            "status": "pending",    # pending -> delivered
        }
        with self._lock:
            self._gc()
            self._pending[request_id] = req
        logger.info("视觉按需请求已创建: request_id=%s focus=%s camera=%r",
                    request_id, focus, camera)
        return request_id

    def pending_for_uid(self, uid: int) -> Optional[dict]:
        """查询是否有待响应的 on-demand 请求（uid=0 视为全局，沿用视觉通知约定）。"""
        with self._lock:
            now = time.time()
            for req in self._pending.values():
                if req["status"] != "pending":
                    continue
                if now - req["created_at"] > self.REQUEST_TIMEOUT:
                    continue
                if req["uid"] == 0 or req["uid"] == uid:
                    return {
                        "request_id": req["request_id"],
                        "focus": req["focus"],
                        "camera": req.get("camera", ""),
                        "timeout": int(self.REQUEST_TIMEOUT),
                    }
            return None

    def submit_frame(self, request_id: str, frames: dict[str, str],
                     error: str = "") -> bool:
        """客户端回传帧 → 唤醒阻塞的 look_around。

        :param frames: {logical_name: base64 data URL}，可含多台摄像头。
        :param error: 客户端抓帧失败时的错误信息（此时 frames 为空）。
        """
        with self._lock:
            req = self._pending.get(request_id)
            if not req or req["status"] != "pending":
                return False
            req["frames"].update(frames)
            req["error"] = error
            req["status"] = "delivered"
            req["event"].set()
        if error:
            logger.info("视觉请求已响应(带错误): request_id=%s error=%s", request_id, error[:60])
        else:
            logger.info("视觉帧已回传: request_id=%s (%d 台)", request_id, len(frames))
        return True

    def wait(self, request_id: str, timeout: Optional[float] = None) -> Optional[dict]:
        """阻塞等待客户端回传帧；超时/错误返回 None。返回 {logical_name: data_url}。"""
        with self._lock:
            req = self._pending.get(request_id)
        if not req:
            return None
        if timeout is None:
            timeout = self.REQUEST_TIMEOUT
        req["event"].wait(timeout=timeout)
        with self._lock:
            frames = dict(req.get("frames", {}))
            error = req.get("error", "")
            self._pending.pop(request_id, None)
        if frames:
            logger.info("视觉按需请求已满足: request_id=%s cameras=%s",
                        request_id, list(frames.keys()))
        elif error:
            logger.warning("视觉按需请求返回错误: request_id=%s error=%s",
                           request_id, error[:80])
        else:
            logger.warning("视觉按需请求超时/未响应: request_id=%s", request_id)
        return frames or None

    def wait_with_error(self, request_id: str, timeout: Optional[float] = None) -> tuple[Optional[dict], str]:
        """阻塞等待客户端回传帧，返回 (frames, error)。超时 frames=None error=超时提示。"""
        with self._lock:
            req = self._pending.get(request_id)
        if not req:
            return None, "请求不存在"
        if timeout is None:
            timeout = self.REQUEST_TIMEOUT
        req["event"].wait(timeout=timeout)
        with self._lock:
            frames = dict(req.get("frames", {}))
            error = req.get("error", "")
            self._pending.pop(request_id, None)
        if frames:
            return frames, ""
        if error:
            return None, error
        return None, "客户端未在超时内响应"

    def _gc(self):
        """清理过期请求（调用方须持有 _lock）。"""
        now = time.time()
        stale = [rid for rid, r in self._pending.items()
                 if now - r["created_at"] > self._GC_MAX_AGE]
        for rid in stale:
            r = self._pending.pop(rid, None)
            if r:
                r["event"].set()  # 唤醒可能仍在 wait 的调用方


# ── 认证 ──

@vision_bp.before_request
def _require_auth():
    """复用全局认证，未认证直接拒绝。"""
    if not _auth_manager:
        return jsonify({"error": "Auth unavailable"}), 503
    user = _auth_manager.authenticate(request)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    g.user = user


# ── 路由 ──

def _get_active_vision_plugin():
    """懒查找 ActiveVisionPlugin 实例（由 PluginLoader 注册到 plugin_manager）。"""
    if _engine is None:
        return None
    try:
        pm = getattr(_engine, "plugin_manager", None)
        if not pm:
            return None
        return pm.get("active_vision")
    except Exception:
        logger.warning("查找 ActiveVisionPlugin 失败", exc_info=True)
        return None


@vision_bp.route("/api/vision/observation", methods=["POST"])
def vision_observation():
    """接收本地客户端周期推送的摄像头帧 → 喂给 ActiveVisionPlugin。"""
    data = request.get_json(silent=True) or {}
    image_data = data.get("image_data", "")
    ts = data.get("timestamp", "")
    if not image_data:
        return jsonify({"success": False, "error": "缺少 image_data"}), 400

    plugin = _get_active_vision_plugin()
    if plugin is None:
        return jsonify({"success": False, "error": "ActiveVisionPlugin 未加载"}), 503

    try:
        result = plugin.ingest_observation(image_data, ts)
    except Exception as e:
        logger.error("ingest_observation 失败: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500

    return jsonify(result)


@vision_bp.route("/api/vision/frame", methods=["POST"])
def vision_frame():
    """接收客户端响应 on-demand look_around 请求回传的帧 → 唤醒阻塞的 look_around。

    兼容两种格式:
      1. 新: {"request_id":..., "frames": [{logical_name, image_data}, ...]}
      2. 旧: {"request_id":..., "image_data": "..."}   （视为 logical_name="default"）
    """
    if coordinator is None:
        return jsonify({"success": False, "error": "VisionCoordinator 不可用"}), 503
    data = request.get_json(silent=True) or {}
    request_id = data.get("request_id", "")
    if not request_id:
        return jsonify({"success": False, "error": "缺少 request_id"}), 400

    frames: dict[str, str] = {}
    raw_frames = data.get("frames")
    if isinstance(raw_frames, list):
        for f in raw_frames:
            if isinstance(f, dict) and f.get("image_data"):
                frames[f.get("logical_name") or "default"] = f["image_data"]
    elif data.get("image_data"):
        frames["default"] = data["image_data"]

    error = data.get("error", "")
    if not frames and not error:
        return jsonify({"success": False, "error": "缺少 image_data/frames"}), 400

    ok = coordinator.submit_frame(request_id, frames, error=error)
    return jsonify({"success": ok})


@vision_bp.route("/api/vision/cameras", methods=["POST", "GET"])
def vision_cameras():
    """客户端枚举上报摄像头列表（POST），或后端查询已登记摄像头（GET）。"""
    if coordinator is None:
        return jsonify({"error": "VisionCoordinator 不可用"}), 503
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        cameras = data.get("cameras", [])
        if isinstance(cameras, list):
            coordinator.register_cameras(cameras)
        return jsonify({"success": True, "count": len(cameras)})
    return jsonify({"success": True, "cameras": coordinator.list_cameras()})


@vision_bp.route("/api/vision/note", methods=["POST"])
def vision_note():
    """主 AI 给指定摄像头写备注。body: {logical_name, note}"""
    if coordinator is None:
        return jsonify({"error": "VisionCoordinator 不可用"}), 503
    data = request.get_json(silent=True) or {}
    name = data.get("logical_name", "")
    note = data.get("note", "")
    if not name:
        return jsonify({"error": "缺少 logical_name"}), 400
    coordinator.set_camera_note(name, note)
    return jsonify({"success": True})
