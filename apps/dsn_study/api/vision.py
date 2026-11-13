# apps/dsn_study/api/vision.py
# 视觉感知协调层（迁移计划阶段 5）—— 桥接边缘客户端（apps/dsn_study_cli）摄像头
# 与后端 VisionModel。请求/响应 JSON 与 apps/dsn/api/vision.py **逐字段对齐**，
# 但**不抄 dsn 的三个已知缺陷**：
#
#   1. dsn 的 `_GC_MAX_AGE=120s` vs `REQUEST_TIMEOUT=8s` —— 废弃请求滞留 2 分钟。
#      本实现 GC 阈值 = REQUEST_TIMEOUT + 缓冲（默认 18s），过期即刻清理。
#   2. dsn 的 look_around 去重缓存是**类级、跨用户共享**（perception.py:36）。
#      本实现的去重缓存按 (uid, camera, focus) 键控，放在技能工具实例里
#      （见 skills/builtin/visual_perception），协调器本身无状态缓存。
#   3. dsn 的本地摄像头 note **只在内存**，重启即丢。本实现把摄像头台账
#      （logical_name / index / note / last_seen）持久化到题库主库的
#      `vision_cameras` 表。
#
# 两条管线（与 dsn 相同）：
#   1. 周期性主动观测:  CLI 定时抓帧 → POST /api/vision/observation → 落盘存档
#   2. 按需 look_around: AI 调 look_around → coordinator.create_request（阻塞等待）
#      → /api/heartbeat 响应携带 vision_request → CLI 抓帧 → POST /api/vision/frame
#      → 唤醒 look_around → VisionModel 描述 → 返回给 AI

from __future__ import annotations

import base64
import logging
import os
import re
import threading
import time
import uuid
from typing import Optional

from flask import Blueprint, request, jsonify, g

logger = logging.getLogger("StudyVision")

vision_bp = Blueprint("vision_api", __name__)

_db = None
_engine = None
_auth_manager = None
_workspace = None

# 模块级单例协调器（init_vision_api 时创建，被技能/heartbeat 懒读取）
coordinator: Optional["VisionCoordinator"] = None
# 实时流帧枢纽（stream-frame 推送入口；heartbeat 据此下发推送配置）
stream_hub: Optional["StreamHub"] = None


def init_vision_api(db=None, engine=None, auth_manager=None, workspace=None):
    """注入依赖并创建单例（boot.py 启动时调用）。"""
    global _db, _engine, _auth_manager, _workspace, coordinator, stream_hub
    _db = db
    _engine = engine
    _auth_manager = auth_manager
    _workspace = workspace
    if coordinator is None:
        coordinator = VisionCoordinator(db=db)
    if stream_hub is None:
        stream_hub = StreamHub()
    logger.info("Vision API 已初始化 (coordinator=%s)", type(coordinator).__name__)


class VisionCoordinator:
    """按需视觉请求的内存协调器（线程安全）。

    桥接同步的 look_around 调用与异步 heartbeat 轮询的边缘客户端：
      - create_request: look_around 注册一条 pending 请求并阻塞 wait
      - pending_for_uid: heartbeat 用来查询是否有待响应请求（下发给客户端）
      - submit_frame: 客户端回传帧后唤醒阻塞的 look_around
      - wait / wait_with_error: look_around 阻塞直到帧到达或超时
    """

    # 修复缺陷 1：等待超时与 GC 阈值同源。dsn 侧等待 8s 但废弃请求滞留 120s，
    # 客户端慢半拍回帧会命中一个早已无人等待的僵尸请求。
    REQUEST_TIMEOUT = 8.0
    _GC_BUFFER = 10.0

    def __init__(self, db=None, request_timeout: Optional[float] = None):
        if request_timeout is not None:
            self.REQUEST_TIMEOUT = float(request_timeout)
        self._db = db
        self._lock = threading.Lock()
        self._pending: dict[str, dict] = {}   # request_id -> {...}
        self._gc_max_age = self.REQUEST_TIMEOUT + self._GC_BUFFER
        self._camera_lock = threading.Lock()
        # 内存台账（启动后从持久层回灌；逻辑名 -> {index, note, last_seen}）
        self._cameras: dict[str, dict] = {}
        self._load_cameras()

    # ── 摄像头台账（修复缺陷 3：持久化，重启不丢） ──

    def _load_cameras(self) -> None:
        """启动时从 vision_cameras 表回灌台账（表不存在则视为首次运行）。"""
        if self._db is None:
            return
        try:
            conn = self._db._get_connection()
            conn.execute(
                "CREATE TABLE IF NOT EXISTS vision_cameras ("
                " logical_name TEXT PRIMARY KEY,"
                " device_index INTEGER,"
                " note TEXT NOT NULL DEFAULT '',"
                " last_seen REAL NOT NULL DEFAULT 0)")
            conn.commit()
            rows = conn.execute(
                "SELECT logical_name, device_index, note, last_seen"
                " FROM vision_cameras").fetchall()
        except Exception:
            logger.warning("摄像头台账回灌失败（将只用内存台账）", exc_info=True)
            return
        with self._camera_lock:
            for r in rows:
                self._cameras[str(r["logical_name"])] = {
                    "index": r["device_index"],
                    "note": r["note"] or "",
                    "last_seen": float(r["last_seen"] or 0),
                }
        if rows:
            logger.info("摄像头台账已回灌: %d 台", len(rows))

    def _persist_camera(self, name: str, entry: dict) -> None:
        """把单台摄像头台账写入持久层（失败不影响内存台账）。"""
        if self._db is None:
            return
        try:
            conn = self._db._get_connection()
            conn.execute(
                "INSERT INTO vision_cameras (logical_name, device_index, note, last_seen)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(logical_name) DO UPDATE SET"
                " device_index=excluded.device_index, note=excluded.note,"
                " last_seen=excluded.last_seen",
                (name, entry.get("index"), entry.get("note", ""),
                 entry.get("last_seen", time.time())))
            conn.commit()
        except Exception:
            logger.warning("摄像头台账持久化失败: %s", name, exc_info=True)

    def _delete_camera_row(self, name: str) -> None:
        """从持久层删除一行台账（失败不影响内存台账）。"""
        if self._db is None:
            return
        try:
            conn = self._db._get_connection()
            conn.execute("DELETE FROM vision_cameras WHERE logical_name = ?",
                         (name,))
            conn.commit()
        except Exception:
            logger.warning("摄像头台账删除失败: %s", name, exc_info=True)

    def register_cameras(self, cameras: list[dict]) -> None:
        """客户端枚举上报摄像头: [{logical_name, index, name, backend}]。

        **按物理设备对账**：同一个 device_index 只允许存在一个逻辑名。
        客户端早期没有 camera_map 时按 cam0/cam1 命名，后来改成
        desk/doc，两套名字会在台账里并存 —— 表现就是「两台摄像头被
        登记了两次」（服务端列出来四台，实际只有两台）。

        规则：客户端上报的名字是**当前真实命名**，同 index 的旧名字
        直接摘掉；旧名字上的备注迁移到新名字（备注描述的是这台物理
        设备，不该随名字一起丢）。
        """
        with self._camera_lock:
            for c in cameras:
                name = c.get("logical_name", "")
                if not name:
                    continue
                index = c.get("index")
                entry = self._cameras.setdefault(
                    name, {"index": None, "note": "", "last_seen": time.time()})
                # 同一物理设备被别的逻辑名占着 → 摘掉旧名（备注迁移）
                if index is not None:
                    for old_name in [n for n, e in self._cameras.items()
                                     if n != name and e.get("index") == index]:
                        old_entry = self._cameras.pop(old_name, None)
                        self._delete_camera_row(old_name)
                        logger.info("摄像头 %s（设备 %s）被 %s 取代，已摘除",
                                    old_name, index, name)
                        # 备注描述的是**这台物理设备**，不该随名字一起丢
                        if (old_entry and not entry.get("note")
                                and old_entry.get("note")):
                            entry["note"] = old_entry["note"]
                entry["index"] = c.get("index", entry.get("index"))
                entry["last_seen"] = time.time()
                self._persist_camera(name, entry)
        logger.info("已登记 %d 个摄像头: %s（台账共 %d 台）",
                    len(cameras), [c.get("logical_name") for c in cameras],
                    len(self._cameras))

    def list_cameras(self) -> list[dict]:
        """列出全部摄像头（study 无远程 webcam 管理器，只有本地物理摄像头）。"""
        with self._camera_lock:
            return [
                {"logical_name": name, "note": entry.get("note", ""),
                 "index": entry.get("index"), "last_seen": entry.get("last_seen"),
                 "kind": "local"}
                for name, entry in sorted(self._cameras.items())
            ]

    def set_camera_note(self, name: str, note: str) -> bool:
        with self._camera_lock:
            entry = self._cameras.setdefault(
                name, {"index": None, "note": "", "last_seen": time.time()})
            entry["note"] = note
            entry["last_seen"] = time.time()
        self._persist_camera(name, entry)
        logger.info("摄像头备注已更新: %s → %s", name, note[:40])
        return True

    def get_camera_note(self, name: str) -> str:
        with self._camera_lock:
            entry = self._cameras.get(name)
            return (entry or {}).get("note", "")

    # ── 按需请求 ──

    def create_request(self, focus: str = "", uid: int = 0,
                       camera: str = "") -> str:
        """创建一条 pending 按需视觉请求，返回 request_id。

        :param camera: 目标摄像头逻辑名；"all"/"all_cameras" 表示枚举全部；
                       空 = 本地主摄像头。
        """
        request_id = f"vision_req_{uuid.uuid4().hex[:16]}"
        req = {
            "request_id": request_id,
            "uid": uid,
            "focus": focus,
            "camera": camera,
            "event": threading.Event(),
            "frames": {},               # logical_name -> base64 data URL
            "created_at": time.time(),
            "status": "pending",        # pending -> delivered
            "errors": {},
        }
        with self._lock:
            self._gc()
            self._pending[request_id] = req
        logger.info("视觉按需请求已创建: request_id=%s focus=%s camera=%r",
                    request_id, focus, camera)
        return request_id

    def pending_for_uid(self, uid: int) -> Optional[dict]:
        """查询是否有待下发给 CLI 的 on-demand 请求（uid=0 视为全局）。"""
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
            if error:
                req["errors"]["_local"] = error
            req["status"] = "delivered"
            req["event"].set()
        if error:
            logger.info("视觉请求已响应(带错误): request_id=%s error=%s",
                        request_id, error[:60])
        else:
            logger.info("视觉帧已回传: request_id=%s (%d 台)",
                        request_id, len(frames))
        return True

    def wait_with_error(self, request_id: str,
                        timeout: Optional[float] = None) -> tuple[Optional[dict], str]:
        """阻塞等待回传帧，返回 (frames, error)。超时 frames=None error=超时提示。"""
        with self._lock:
            req = self._pending.get(request_id)
        if not req:
            return None, "请求不存在"
        if timeout is None:
            timeout = self.REQUEST_TIMEOUT
        req["event"].wait(timeout=timeout)
        with self._lock:
            frames = dict(req.get("frames", {}))
            error = self._aggregate_error(req)
            self._pending.pop(request_id, None)
        if frames:
            logger.info("视觉按需请求已满足: request_id=%s cameras=%s",
                        request_id, list(frames.keys()))
            return frames, ""
        if error:
            return None, error
        return None, "客户端未在超时内响应"

    def wait(self, request_id: str,
             timeout: Optional[float] = None) -> Optional[dict]:
        """阻塞等待客户端回传帧；超时/错误返回 None。返回 {logical_name: data_url}。"""
        frames, _ = self.wait_with_error(request_id, timeout)
        return frames

    def _aggregate_error(self, req: dict) -> str:
        errors = req.get("errors", {}) or {}
        if not errors:
            return ""
        parts = []
        for name, err in sorted(errors.items()):
            label = name if name != "_local" else "本地摄像头"
            parts.append(f"{label}: {err}")
        return "; ".join(parts)[:200]

    def _gc(self):
        """清理过期请求（调用方须持有 _lock）。

        修复缺陷 1：dsn 的 GC 阈值 120s 远大于等待超时 8s，废弃请求滞留
        2 分钟。这里阈值 = REQUEST_TIMEOUT + 10s 缓冲，僵尸请求即刻清理。
        """
        now = time.time()
        stale = [rid for rid, r in self._pending.items()
                 if now - r["created_at"] > self._gc_max_age]
        for rid in stale:
            r = self._pending.pop(rid, None)
            if r:
                r["event"].set()   # 唤醒可能仍在 wait 的调用方

    # ── 供测试 / 运维 ──

    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)


class StreamHub:
    """实时流帧枢纽（dsn VisionStreamingService 的最小 study 版）。

    CLI 的 StreamPusher 周期推帧 → POST /api/vision/stream-frame → 这里按
    逻辑名保留最近一帧（带 TTL）。study 无 webUI 监控页，暂不提供 MJPEG
    输出；保留订阅者计数语义，心跳据此下发 streams 推送配置。
    """

    FRAME_TTL = 10.0

    def __init__(self):
        self._lock = threading.Lock()
        self._latest: dict[str, dict] = {}   # logical_name -> {image_data, ts}
        self._subscribers: set[str] = set()

    # ── 推送入口 ──

    def ingest_frames(self, frames: list[dict]) -> int:
        """接收 [{logical_name, index?, image_data}, ...]，保留最近一帧。"""
        accepted = 0
        now = time.time()
        with self._lock:
            for f in frames:
                if not isinstance(f, dict):
                    continue
                name = f.get("logical_name") or "default"
                if not f.get("image_data"):
                    continue
                self._latest[name] = {
                    "image_data": f["image_data"],
                    "ts": now,
                }
                accepted += 1
            self._evict_locked(now)
        return accepted

    def _evict_locked(self, now: float) -> None:
        stale = [n for n, v in self._latest.items()
                 if now - v.get("ts", 0) > self.FRAME_TTL]
        for n in stale:
            self._latest.pop(n, None)

    def latest_frame(self, logical_name: str = "") -> Optional[dict]:
        """取最近一帧 {logical_name, image_data, ts}；无帧返回 None。"""
        with self._lock:
            self._evict_locked(time.time())
            if logical_name:
                v = self._latest.get(logical_name)
                if v is None:
                    return None
                return {"logical_name": logical_name, **v}
            if not self._latest:
                return None
            name, v = sorted(self._latest.items())[-1]
            return {"logical_name": name, **v}

    def list_frames(self) -> list[dict]:
        with self._lock:
            self._evict_locked(time.time())
            return [{"logical_name": n, "ts": v["ts"]}
                    for n, v in sorted(self._latest.items())]

    # ── 订阅语义（心跳 streams 配置的依据） ──

    def subscribe(self, subscriber_id: str) -> None:
        with self._lock:
            self._subscribers.add(subscriber_id)

    def unsubscribe(self, subscriber_id: str) -> None:
        with self._lock:
            self._subscribers.discard(subscriber_id)

    def has_local_subscribers(self) -> bool:
        with self._lock:
            return bool(self._subscribers)


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


# ── 落盘 ──

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_\-]")


def _save_observation_image(image_data: str, uid: int,
                            logical_name: str = "") -> str:
    """把一帧落盘到工作区 vision 目录，返回文件路径；失败返回空串。

    这是「看到 → 录入」桥的落盘半边：图片有了本地路径，
    只认路径的入库工具（quest_from_image 等）才能消费它。
    """
    try:
        m = re.match(r"data:image/(\w+);base64,(.*)", image_data, re.DOTALL)
        raw = base64.b64decode(m.group(2) if m else image_data)
        if not raw:
            return ""
        ext = (m.group(1) if m else "jpg").lower()
        if ext not in ("jpg", "jpeg", "png", "webp", "bmp"):
            ext = "jpg"
        if _workspace is not None:
            base_dir = _workspace.user_subdir(uid, "vision")
        else:
            base_dir = os.path.join("workspace", f"user_{uid}", "vision")
            os.makedirs(base_dir, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        cam = _SAFE_NAME_RE.sub("", logical_name or "cam")[:16] or "cam"
        path = os.path.join(str(base_dir), f"vision_{cam}_{ts}_{uuid.uuid4().hex[:6]}.{ext}")
        with open(path, "wb") as f:
            f.write(raw)
        return path
    except Exception:
        logger.warning("观测帧落盘失败", exc_info=True)
        return ""


# ── 路由（请求/响应 JSON 与 dsn 逐字段对齐） ──

@vision_bp.route("/api/vision/observation", methods=["POST"])
def vision_observation():
    """接收边缘客户端周期推送的摄像头帧 → 落盘存档（study 版主动观测通道）。

    dsn 版委托 tracking 子系统的 VisionObservationService（保存照片 + 写
    tracking 日志 + 场景变化通知）；study 无该子系统，改为：落盘到工作区 +
    记录内存最近观测。响应保持 {"success": ...} 形状。
    body: {"image_data", "timestamp"?, "camera"?}
    """
    data = request.get_json(silent=True) or {}
    image_data = data.get("image_data", "")
    ts = data.get("timestamp", "")
    camera = data.get("camera", "")
    if not image_data:
        return jsonify({"success": False, "error": "缺少 image_data"}), 400

    uid = 0
    try:
        if getattr(g, "user", None) is not None:
            uid = int(getattr(g.user, "uid", 0) or 0)
    except Exception:
        uid = 0

    try:
        path = _save_observation_image(image_data, uid, camera)
    except Exception as e:
        logger.error("observation 落盘失败: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500

    return jsonify({
        "success": True,
        "path": path,
        "camera": camera,
        "timestamp": ts,
        "saved": bool(path),
    })


@vision_bp.route("/api/vision/stream-frame", methods=["POST"])
def vision_stream_frame():
    """接收 StreamPusher 推送的本地摄像头实时帧 → 写入流帧枢纽。

    与 /api/vision/frame（on-demand 回传）隔离：本端点只服务实时监控，
    不经过 VisionCoordinator，不影响 look_around。
    body: {"frames": [{logical_name, index, image_data}, ...]}
    """
    if stream_hub is None:
        return jsonify({"success": False, "error": "监控流服务不可用"}), 503
    data = request.get_json(silent=True) or {}
    frames = data.get("frames") or []
    if not isinstance(frames, list):
        return jsonify({"success": False, "error": "frames 需为数组"}), 400
    try:
        n = stream_hub.ingest_frames(frames)
    except Exception as e:
        logger.error("接收监控流帧失败: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500
    return jsonify({"success": True, "accepted": n})


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
    # 显式提供 frames 数组（可为空）视为本地抓帧结果：空数组=客户端无摄像头/抓帧失败
    has_explicit_frames = isinstance(data.get("frames"), list)
    if not frames and not error and not has_explicit_frames:
        return jsonify({"success": False, "error": "缺少 image_data/frames"}), 400

    if not frames and not error:
        error = "本地客户端未抓到帧（无摄像头或设备不可用）"
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


@vision_bp.route("/api/vision/webcams", methods=["GET", "POST", "DELETE", "PATCH"])
def vision_webcams():
    """远程摄像头管理（形状与 dsn 对齐；study 无 WebCamManager → 503）。"""
    if coordinator is None or getattr(coordinator, "webcam_manager", None) is None:
        return jsonify({"error": "远程摄像头管理不可用（WebCamManager 未注入）"}), 503
    # 理论上不可达：study 版协调器不接 WebCamManager。保留分支以对齐 dsn 形状。
    return jsonify({"error": "远程摄像头管理不可用"}), 503


@vision_bp.route("/api/vision/webcams/test", methods=["POST"])
def vision_webcam_test():
    """测试远程摄像头连通性（study 无 WebCamManager → 503，形状与 dsn 对齐）。"""
    if coordinator is None or getattr(coordinator, "webcam_manager", None) is None:
        return jsonify({"error": "远程摄像头管理不可用"}), 503
    return jsonify({"error": "远程摄像头管理不可用"}), 503
