# api/vision.py
# 视觉感知协调层 — 桥接本地客户端(minimal.py)摄像头与后端 VisionModel/场景变化逻辑。
#
# 摄像头抓帧已迁移到本地客户端 minimal.py(本地 cv2)，后端只保留:
#   - VisionModel 多模态分析
#   - 场景变化检测 + 主动通知(task_notifications)
#   - 主动视觉观察服务（tracking/vision_observe.py，基于用户跟踪系统）
#
# 多摄像头: 所有摄像头都连接在本地客户端上。首次视觉请求（camera="all"）
# 由客户端枚举+逐台抓帧，回传多帧；后端逐张给视觉模型，返回逻辑名+描述列表。
# 主 AI 可用 set_camera_note 给各摄像头写备注，之后可按逻辑名单独 look_around。
#
# 两条管线:
#   1. 周期性主动视觉:
#        minimal.py 定时 cv2 抓帧 → POST /api/vision/observation
#        → VisionObservationService.ingest_observation
#          (保存照片 + VisionModel 描述 → 写入 tracking 日志 + 场景变化 + task_notifications)
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
# 模块级实时监控流服务（webUI MJPEG 流；heartbeat 据此下发本地推送配置）
stream_service = None


def init_vision_api(db=None, engine=None, auth_manager=None, webcams=None):
    """注入依赖并创建 VisionCoordinator 单例（boot.py 启动时调用）。

    :param webcams: 可选 WebCamManager 实例；提供后远程网络摄像头
                    与本地物理摄像头统一编目，AI 可同样调用。
    """
    global _db, _engine, _auth_manager, coordinator, stream_service
    _db = db
    _engine = engine
    _auth_manager = auth_manager
    if coordinator is None:
        coordinator = VisionCoordinator()
    if webcams is not None:
        coordinator.register_webcam_manager(webcams)
    # 实时监控流服务：webUI 监控页的 MJPEG 流 + 本地客户端推送帧入口
    if stream_service is None:
        from apps.dsn.api.stream import VisionStreamingService
        stream_service = VisionStreamingService(coordinator)
        stream_service.start()
    logger.info("Vision API 已初始化 (coordinator=%s, webcams=%s)",
                type(coordinator).__name__,
                webcams.count() if webcams is not None else "N/A")


# 1x1 PNG（预热用极小图片，避免真实摄像头参与）
_TINY_PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
             "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def warmup_vision_model():
    """后台预热 VLM：启动时发一次低 token dummy 请求，摊薄首次 look_around 的冷启动推理。

    在独立 daemon 线程中运行，不阻塞启动流程；失败静默忽略。
    """
    try:
        from apps.dsn.config import Config
        if not getattr(Config, "VISION_WARMUP", True):
            return
        if not getattr(Config, "VISION_ENABLED", True):
            return
        from apps.dsn.models.clients import VisionModel
        vm = VisionModel()
        vm.ask(
            data_url=_TINY_PNG,
            prompt="这是一张 1x1 测试图。请只回复一个词：ok。",
            max_tokens=8,
            temperature=0.0,
        )
        logger.info("VisionModel 预热完成 (model=%s)", vm.model_name)
    except Exception as e:
        logger.debug("VisionModel 预热失败（不影响运行）: %s", e)


def spawn_vision_warmup():
    """以后台线程方式启动 VLM 预热（幂等）。"""
    import threading
    t = threading.Thread(target=warmup_vision_model, daemon=True,
                         name="vision-warmup")
    t.start()


class VisionCoordinator:
    """按需视觉请求的内存协调器（线程安全）。

    桥接同步的 look_around 调用与异步 heartbeat 轮询的本地客户端：
      - create_request: look_around 注册一条 pending 请求并阻塞 wait
      - pending_for_uid: heartbeat 用来查询是否有待响应请求（下发给客户端）
      - submit_frame: 客户端回传帧后唤醒阻塞的 look_around
      - wait: look_around 阻塞直到帧到达或超时
    """

    REQUEST_TIMEOUT = 8.0     # look_around 阻塞等待客户端帧的超时秒数（客户端离线时快速兜底）
    _GC_MAX_AGE = 120.0        # 过期请求清理阈值

    def __init__(self):
        self._lock = threading.Lock()
        self._pending: dict[str, dict] = {}  # request_id -> {...}
        # 摄像头元数据: logical_name -> {index, note, last_seen, kind}
        self._cameras: dict[str, dict] = {}
        self._camera_lock = threading.Lock()
        # 远程网络摄像头（WebCamManager，可为 None）
        self._webcams = None

    # === 远程 webcam 接入 ===

    def register_webcam_manager(self, manager) -> None:
        """注入 WebCamManager。webcam 与本地物理摄像头统一编目、同样可被调用。"""
        self._webcams = manager
        logger.info("VisionCoordinator: 已接入远程摄像头管理器 (%d 台)",
                    manager.count() if manager is not None else 0)

    @property
    def webcam_manager(self):
        return self._webcams

    def _is_webcam(self, name: str) -> bool:
        """判断逻辑名是否指向远程摄像头（而不是本地物理摄像头）。"""
        return bool(self._webcams and self._webcams.is_webcam(name))

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
        """列出全部摄像头（本地物理 + 远程 webcam），统一编目。"""
        with self._camera_lock:
            result = [
                {"logical_name": name, "note": entry.get("note", ""),
                 "index": entry.get("index"), "last_seen": entry.get("last_seen"),
                 "kind": "local"}
                for name, entry in sorted(self._cameras.items())
            ]
        # 合并远程摄像头
        if self._webcams is not None:
            for item in self._webcams.list():
                result.append({
                    "logical_name": item["logical_name"],
                    "note": item.get("note", ""),
                    "index": item.get("index"),
                    "last_seen": None,
                    "kind": "webcam",
                    "url": item.get("redacted_url", item.get("url", "")),
                    "enabled": item.get("enabled", True),
                })
        return result

    def set_camera_note(self, name: str, note: str) -> bool:
        # 远程摄像头备注写入持久化配置
        if self._webcams is not None and self._webcams.is_webcam(name):
            res = self._webcams.set_note(name, note)
            logger.info("远程摄像头备注已更新: %s → %s", name, note[:40])
            return bool(res.get("ok"))
        with self._camera_lock:
            if name not in self._cameras:
                self._cameras[name] = {"index": None, "note": "", "last_seen": time.time()}
            self._cameras[name]["note"] = note
        logger.info("摄像头备注已更新: %s → %s", name, note[:40])
        return True

    def list_cameras_note(self, name: str) -> str:
        if self._webcams is not None and self._webcams.is_webcam(name):
            cam = self._webcams.get(name)
            return (cam.note if cam else "") or ""
        with self._camera_lock:
            entry = self._cameras.get(name)
            return (entry or {}).get("note", "")

    # === 按需请求 ===

    def create_request(self, focus: str = "", uid: int = 0, camera: str = "") -> str:
        """创建一条 pending 按需视觉请求，返回 request_id。

        :param camera: 目标摄像头逻辑名；"all"/"all_cameras" 表示枚举全部（本地+远程）；
                       空=本地主摄像头；也可以是远程 webcam 逻辑名。
        远程 webcam 由后端直接抓帧（网络可达，无需经过 minimal.py），
        本地物理摄像头仍通过心跳下发给客户端抓帧回传。
        """
        request_id = f"vision_req_{uuid.uuid4().hex[:16]}"
        webcam_names, local_needed = self._plan_cameras(camera)
        req = {
            "request_id": request_id,
            "uid": uid,
            "focus": focus,
            "camera": camera,
            "event": threading.Event(),
            "frames": {},               # logical_name -> base64 data URL
            "created_at": time.time(),
            "status": "pending",        # pending -> delivered
            # 完成条件追踪：
            "webcam_names": webcam_names,   # 需要后端直抓的 webcam 逻辑名
            "failed_webcams": set(),        # 抓帧失败的 webcam
            "webcam_done": False,           # webcam 部分是否全部有结果
            "local_needed": local_needed,   # 是否需要 minimal.py 抓帧（本地物理摄像头）
            "local_done": False,            # 客户端是否已回传（成功或失败）
            "errors": {},                   # logical_name -> error 提示
        }
        with self._lock:
            self._gc()
            self._pending[request_id] = req
        if webcam_names:
            self._spawn_webcam_grab(request_id, webcam_names)
        logger.info("视觉按需请求已创建: request_id=%s focus=%s camera=%r "
                    "(webcam=%s local=%s)",
                    request_id, focus, camera, webcam_names, local_needed)
        return request_id

    def _plan_cameras(self, camera: str) -> tuple[list[str], bool]:
        """把 camera 参数解析为 {需后端直抓的 webcam 列表, 是否需要本地客户端抓帧}。"""
        manager = self._webcams
        has_webcams = manager is not None and manager.has_webcams()
        if not has_webcams:
            return [], True
        if camera in ("all", "all_cameras"):
            return list(manager.names()), True   # 全部 webcam + 本地物理摄像头
        if camera in ("", "default"):
            return [], True                      # 本地主摄像头
        if manager.is_webcam(camera):
            return [camera], False               # 纯远程，无需客户端
        return [], True                          # 本地物理逻辑名

    def _spawn_webcam_grab(self, request_id: str, names: list[str]) -> None:
        """后台线程抓取全部 webcam 帧（并行），完成后唤醒等待方。"""
        def _work():
            try:
                frames, failed = self._webcams.capture_frames(names)
                self._submit_webcam_results(request_id, frames, failed)
            except Exception as e:
                logger.warning("webcam 抓帧线程异常: %s", e)
                self._submit_webcam_results(request_id, {}, list(names))
        t = threading.Thread(target=_work, daemon=True,
                             name="vision-webcam-grab")
        t.start()

    def _submit_webcam_results(self, request_id: str, frames: dict[str, str],
                               failed: list[str]) -> None:
        """汇总 webcam 抓帧结果（后端直抓线程调用）。"""
        with self._lock:
            req = self._pending.get(request_id)
            if not req or req["status"] != "pending":
                return
            req["frames"].update(frames)
            for name in failed:
                req["failed_webcams"].add(name)
                req["errors"][name] = "远程摄像头抓帧失败"
            req["webcam_done"] = True
            self._maybe_complete(req)
        if frames or failed:
            logger.info("webcam 帧已就绪: request_id=%s ok=%d fail=%d",
                        request_id, len(frames), len(failed))

    def pending_for_uid(self, uid: int) -> Optional[dict]:
        """查询是否有待下发给 minimal.py 的 on-demand 请求（uid=0 视为全局）。

        纯 webcam 请求由后端直抓，不在此下发；仅下发需要本地客户端抓帧的请求。
        """
        with self._lock:
            now = time.time()
            for req in self._pending.values():
                if req["status"] != "pending":
                    continue
                if now - req["created_at"] > self.REQUEST_TIMEOUT:
                    continue
                if not req["local_needed"]:
                    continue   # 纯 webcam 请求，后端已直抓
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
        """客户端回传帧 → 标记本地部分完成 → 全部就绪后唤醒阻塞的 look_around。

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
            req["local_done"] = True
            self._maybe_complete(req)
        if error:
            logger.info("视觉请求已响应(带错误): request_id=%s error=%s", request_id, error[:60])
        else:
            logger.info("视觉帧已回传: request_id=%s (%d 台)", request_id, len(frames))
        return True

    def _maybe_complete(self, req: dict) -> None:
        """完成判定：webcam 部分全部有结果 && (本地部分完成或不需要本地)。"""
        if req["webcam_names"]:
            all_wc = all(n in req["frames"] or n in req["failed_webcams"]
                         for n in req["webcam_names"])
            if not all_wc:
                return
        if req["local_needed"] and not req["local_done"]:
            return
        req["status"] = "delivered"
        req["event"].set()

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
            error = self._aggregate_error(req)
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
            return frames, ""
        if error:
            return None, error
        return None, "客户端未在超时内响应"

    def _aggregate_error(self, req: dict) -> str:
        """汇总请求的错误信息（本地 + 各 webcam），有帧时也返回附带提示。"""
        errors = req.get("errors", {}) or {}
        if not errors:
            return ""
        parts = []
        for name, err in sorted(errors.items()):
            label = name if name != "_local" else "本地摄像头"
            parts.append(f"{label}: {err}")
        return "; ".join(parts)[:200]

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

def _get_vision_service():
    """懒获取 VisionObservationService（tracking 子系统内，boot.py 注入到 app.config）。"""
    try:
        from flask import current_app
        return current_app.config.get("VISION_OBSERVATION_SERVICE")
    except Exception:
        return None


@vision_bp.route("/api/vision/observation", methods=["POST"])
def vision_observation():
    """接收本地客户端周期推送的摄像头帧 → 主动视觉观察服务。

    服务会保存照片 + VisionModel 描述 → 写入 tracking 日志（基于用户跟踪系统）。
    """
    data = request.get_json(silent=True) or {}
    image_data = data.get("image_data", "")
    ts = data.get("timestamp", "")
    camera = data.get("camera", "")
    if not image_data:
        return jsonify({"success": False, "error": "缺少 image_data"}), 400

    svc = _get_vision_service()
    if svc is None:
        return jsonify({"success": False, "error": "VisionObservationService 未初始化"}), 503

    uid = 0
    try:
        if getattr(g, "user", None) is not None:
            uid = int(getattr(g.user, "uid", 0) or 0)
    except Exception:
        uid = 0

    try:
        result = svc.ingest_observation(image_data, ts, user_id=uid, camera=camera)
    except Exception as e:
        logger.error("ingest_observation 失败: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500

    return jsonify(result)


@vision_bp.route("/api/vision/stream-frame", methods=["POST"])
def vision_stream_frame():
    """接收 minimal.py StreamPusher 推送的本地摄像头实时帧 → 写入监控流会话。

    与 /api/vision/frame（on-demand 回传）隔离：本端点只服务 webUI 实时监控，
    不经过 VisionCoordinator，不影响 look_around。
    body: {"frames": [{logical_name, index, image_data}, ...]}
    """
    global stream_service
    if stream_service is None:
        return jsonify({"success": False, "error": "监控流服务不可用"}), 503
    data = request.get_json(silent=True) or {}
    frames = data.get("frames") or []
    if not isinstance(frames, list):
        return jsonify({"success": False, "error": "frames 需为数组"}), 400
    try:
        n = stream_service.ingest_frames(frames)
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


# ── 远程 webcam 管理（REST 版；亦可使用后端控制台 /webcam 命令）──

@vision_bp.route("/api/vision/webcams", methods=["GET", "POST", "DELETE", "PATCH"])
def vision_webcams():
    """远程摄像头管理：

    GET        列出全部远程摄像头
    POST       {url, name?, note?, test?}  添加（默认先测试连通性）
    DELETE     {name}                      删除
    PATCH      {name, note?|enabled?}      改备注 / 启停
    """
    if coordinator is None or coordinator.webcam_manager is None:
        return jsonify({"error": "远程摄像头管理不可用（WebCamManager 未注入）"}), 503
    mgr = coordinator.webcam_manager

    if request.method == "GET":
        return jsonify({"success": True, "cameras": mgr.list(), "count": mgr.count()})

    data = request.get_json(silent=True) or {}
    if request.method == "POST":
        res = mgr.add(
            url=data.get("url", ""),
            name=data.get("name", ""),
            note=data.get("note", ""),
            test=bool(data.get("test", True)),
        )
        if not res.get("ok"):
            return jsonify({"success": False, "error": res.get("error", "添加失败")}), 400
        return jsonify({"success": True, "logical_name": res["logical_name"]})

    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "缺少 name"}), 400

    if request.method == "DELETE":
        res = mgr.remove(name)
        if not res.get("ok"):
            return jsonify({"success": False, "error": res.get("error", "删除失败")}), 404
        return jsonify({"success": True})

    # PATCH
    res = {"ok": True}
    if "note" in data:
        res = mgr.set_note(name, str(data.get("note", "")))
    elif "enabled" in data:
        res = mgr.set_enabled(name, bool(data.get("enabled")))
    else:
        return jsonify({"error": "PATCH 需提供 note 或 enabled"}), 400
    if not res.get("ok"):
        return jsonify({"success": False, "error": res.get("error", "更新失败")}), 404
    return jsonify({"success": True, "logical_name": name})


@vision_bp.route("/api/vision/webcams/test", methods=["POST"])
def vision_webcam_test():
    """测试远程摄像头连通性。body: {url}"""
    if coordinator is None or coordinator.webcam_manager is None:
        return jsonify({"error": "远程摄像头管理不可用"}), 503
    data = request.get_json(silent=True) or {}
    url = data.get("url", "")
    if not url:
        return jsonify({"error": "缺少 url"}), 400
    res = coordinator.webcam_manager.test(url)
    return jsonify({"success": bool(res.get("ok")), **res})
