# tracking/vision_observe.py
# VisionObservationService — 用户跟踪系统的"主动视觉观察"能力（infra）。
#
# 替代原 plugins/builtin/active_vision_plugin.py，改为与闲时感知语音(AudioListeningMonitor)
# 类似的实现：不依赖插件系统，而是 tracking 子系统内的一个服务。
#
# 职责：
#   1. 接收本地客户端(minimal.py VisionObserver)推送的摄像头帧
#   2. 把照片保存进 tracking 媒体库（MediaManager，按用户/日期/类型分目录）→ record_photo
#   3. 调用 VisionModel 生成画面描述 → record_text 写入文本日志
#   4. 场景变化检测 → 写 task_notifications（保持"主动通知"能力）
#   5. 缓存最新观测，供心跳/按需 look_around 兼容读取
#
# 与闲时感知的区别：闲时感知只记录音频；本服务记录"照片 + 文本描述"两种模态。

from __future__ import annotations

import base64
import json
import logging
import threading
import time
import uuid
from datetime import datetime
from typing import Optional

logger = logging.getLogger("tracking.vision_observe")


class VisionObservationService:
    """主动视觉观察服务（tracking 子系统内，非插件）。

    用法（boot.py）：
        svc = VisionObservationService(tracking_engine=te, db=db)
        app.config["VISION_OBSERVATION_SERVICE"] = svc
        # api/vision.py 的 /api/vision/observation 调用 svc.ingest_observation(...)
    """

    def __init__(self, tracking_engine=None, db=None):
        self._tracking = tracking_engine
        self._db = db
        self._vision_model = None
        self._latest_observation: Optional[dict] = None
        self._observation_lock = threading.Lock()

        # 场景变化追踪（沿用原插件的启发式）
        self._prev_user_present: Optional[bool] = None
        self._prev_light_label: Optional[str] = None
        self._last_notification_ts = 0.0
        self._user_present_since: Optional[float] = None

    # ── 依赖注入 ──
    def set_deps(self, tracking_engine=None, db=None):
        if tracking_engine is not None:
            self._tracking = tracking_engine
        if db is not None:
            self._db = db

    @property
    def tracking(self):
        return self._tracking

    # ── VisionModel ──
    def _get_vision_model(self):
        if self._vision_model is not None:
            return self._vision_model
        try:
            from apps.dsn.models.clients import VisionModel
            self._vision_model = VisionModel()
            return self._vision_model
        except Exception as e:
            logger.error("VisionModel 初始化失败: %s", e)
            return None

    # ── 帧处理 ──
    def ingest_observation(self, data_url: str, timestamp: str = "",
                           user_id: int = 0, camera: str = "") -> dict:
        """接收客户端推送的摄像头帧 → 保存照片 + VisionModel 描述 → 写入跟踪日志。

        :param data_url: "data:image/jpeg;base64,..." 帧
        :param timestamp: 客户端时间戳
        :param user_id: 归属用户（缺省 0=全局，仍会落库为文本日志）
        :param camera: 来源摄像头逻辑名（记录到 meta）
        :return: {success, timestamp, description, image_path, ...}
        """
        from apps.dsn.config import Config
        if not getattr(Config, "ACTIVE_VISION_ENABLED", False):
            return {"success": False, "error": "主动视觉未启用 (ACTIVE_VISION_ENABLED=false)"}

        now = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 1) 保存照片（MediaManager 按用户/日期/类型分目录）
        image_path = self._save_photo(data_url, user_id)
        if not image_path:
            image_path = ""  # 保存失败不阻断分析

        # 2) VisionModel 生成画面描述
        vm = self._get_vision_model()
        description = ""
        if vm is not None:
            prompt = (
                "你是安装在电脑上的AI视觉系统，正在通过摄像头观察周围。"
                "请简洁描述你看到的画面：1) 是否有用户，用户在做什么；"
                "2) 环境光线和场景。控制在40字以内。"
            )
            try:
                description = (vm.ask(data_url, prompt=prompt,
                                      max_tokens=256, temperature=0.1) or "").strip()
            except Exception as e:
                logger.warning("VisionModel 分析失败: %s", e)

        result = {
            "success": True,
            "timestamp": now,
            "description": description,
            "camera": camera,
        }
        if image_path:
            result["image_path"] = image_path

        with self._observation_lock:
            self._latest_observation = result

        # 3) 写入跟踪日志：照片事件 + 文本描述
        if self._tracking is not None:
            try:
                if image_path:
                    self._tracking.record_photo(
                        user_id=user_id or 0, path=image_path, source="active_vision",
                        note=description or "主动视觉抓拍",
                    )
                if description:
                    self._tracking.record_text(
                        user_id=user_id or 0,
                        content=f"【视觉】{description}",
                        source="active_vision",
                        note=f"相机 {camera or 'default'}",
                    )
            except Exception:
                logger.warning("写入 tracking 视觉日志失败", exc_info=True)

        logger.info("主动视觉观察: camera=%s desc=%s", camera or "default", description[:40])

        # 4) 场景变化检测 + 主动通知
        self._check_scene_change(result)
        return result

    def _save_photo(self, data_url: str, user_id: int) -> str:
        """把 base64 data URL 保存为 jpg 到用户媒体库；失败返回空串。"""
        if self._tracking is None:
            return ""
        try:
            header, _, b64 = data_url.partition(",")
            if not b64 and ";" not in header:
                return ""
            raw = base64.b64decode(b64 or data_url)
            path = self._tracking.media.save_file(raw, "vision.jpg", kind="photo", uid=user_id or 0)
            return path or ""
        except Exception as e:
            logger.warning("保存视觉照片失败: %s", e)
            return ""

    # ── 场景变化检测（沿用原插件逻辑）──
    def _check_scene_change(self, observation: dict):
        from apps.dsn.config import Config

        desc = observation.get("description", "")
        now = time.time()
        if not desc:
            return

        user_present = self._infer_user_presence(desc)
        light_label = self._infer_light(desc)

        prev_present = self._prev_user_present
        self._prev_user_present = user_present
        self._prev_light_label = light_label

        if user_present and not prev_present:
            self._user_present_since = now
        elif not user_present and prev_present:
            self._user_present_since = None

        cooldown = getattr(Config, "ACTIVE_VISION_PROACTIVE_COOLDOWN", 600)
        if now - self._last_notification_ts < cooldown:
            return

        should_notify = False
        reason = ""
        if user_present and prev_present is False:
            should_notify, reason = True, "user_appeared"
        elif light_label and self._prev_light_label and light_label != self._prev_light_label:
            should_notify, reason = True, "light_changed"
        if not should_notify and user_present and self._user_present_since:
            session_duration = (now - self._user_present_since) / 60
            periodic_interval = getattr(Config, "ACTIVE_VISION_PERIODIC_NOTIFY_MIN", 30)
            if session_duration >= periodic_interval:
                should_notify, reason = True, "periodic"

        if not should_notify:
            return
        self._write_vision_notification(observation, reason)
        self._last_notification_ts = now
        logger.info("场景变化触发视觉通知: reason=%s desc=%s", reason, desc[:50])

    def _write_vision_notification(self, observation: dict, reason: str):
        if not self._db:
            logger.warning("DB 未注入，无法写入视觉通知")
            return
        try:
            conn = self._db._get_connection()
            task_id = f"vision_{uuid.uuid4().hex[:16]}"
            notif_data = {
                "task_type": "vision",
                "reason": reason,
                "timestamp": observation.get("timestamp", ""),
                "description": observation.get("description", ""),
                "camera": observation.get("camera", ""),
                "params": {},
            }
            conn.execute(
                "INSERT INTO task_notifications (task_id, user_id, chat_id, result, delivered) "
                "VALUES (?, ?, ?, ?, 0)",
                (task_id, 0, 0, json.dumps(notif_data, ensure_ascii=False)),
            )
            conn.commit()
            logger.info("视觉通知已写入: task_id=%s reason=%s", task_id, reason)
        except Exception as e:
            logger.error("写入视觉通知失败: %s", e)

    @staticmethod
    def _infer_user_presence(desc: str) -> bool:
        absence_keywords = ["没有用户", "无人", "没人", "空", "无人在", "empty",
                            "no one", "no person", "nobody", "没有人", "无用户"]
        for kw in absence_keywords:
            if kw in desc.lower():
                return False
        presence_keywords = ["用户", "人在", "一个人", "有人", "person", "user",
                             "someone", "用户坐", "用户在", "用户正在"]
        for kw in presence_keywords:
            if kw in desc:
                return True
        ambient_indicators = ["屏幕", "电脑", "桌子", "书桌", "键盘", "显示器",
                              "desk", "screen", "laptop", "computer", "monitor"]
        if len(desc) > 10:
            for ind in ambient_indicators:
                if ind in desc:
                    return True
        return False

    @staticmethod
    def _infer_light(desc: str) -> Optional[str]:
        desc_lower = desc.lower()
        if any(kw in desc_lower for kw in ["明亮", "亮", "bright", "阳光", "sunlight", "well-lit"]):
            return "bright"
        if any(kw in desc_lower for kw in ["昏暗", "暗", "黑暗", "dim", "dark", "仅屏幕", "只有屏幕"]):
            return "dim"
        if any(kw in desc_lower for kw in ["正常", "normal", "适中", "自然光"]):
            return "normal"
        return None

    # ── 最新观测读取 ──
    def get_observation(self) -> Optional[dict]:
        with self._observation_lock:
            if self._latest_observation is None:
                return None
            return dict(self._latest_observation)
