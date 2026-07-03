# plugins/builtin/active_vision_plugin.py
# 主动视觉感知插件 v2 — 后台定时观测摄像头 + 场景变化检测 + 主动说话通知
#
# 双管线:
#   1. 被动注入: PRE_PROCESS 注入 "[视觉感知]" 到 system_prompt (保持原有)
#   2. 主动通知: 场景变化 → 写 task_notifications → 前端心跳拉取 → 主LLM决策 → 主动说话
#
# Pipeline 2 完整路径:
#   CameraWatcher 后台线程定时抓帧
#     → VisionModel 语义描述
#     → 场景变化检测 (用户出现/离开/光线突变/周期性)
#     → 写 task_notifications DB (delivered=0, task_type='vision')
#     → 前端心跳 POST /api/heartbeat 拉取
#     → 构造 prompt, 调 engine.chat() 让主LLM决策是否说话
#     → 返回 reply + TTS → 前端显示/播放

from __future__ import annotations

import json
import logging
import threading
import time
import base64
import uuid
from datetime import datetime
from typing import Optional

from plugins.base import Plugin, HookPoint, PluginContext

logger = logging.getLogger("ActiveVisionPlugin")


class ActiveVisionPlugin(Plugin):
    """
    主动视觉感知插件 v2。

    职责:
    - 后台线程定时抓取摄像头画面，调用 VisionModel 分析
    - 最新观测结果缓存 + PRE_PROCESS 注入 (被动)
    - 场景变化检测 + 写 task_notifications (主动通知)
    - 提供 get_observation() 供外部获取最新观测

    配置 (config.py):
    - ACTIVE_VISION_ENABLED: 是否启用 (默认 false)
    - ACTIVE_VISION_INTERVAL: 主动观测间隔秒数 (默认 300 = 5分钟)
    - CAMERA_DEVICE_ID: 摄像头设备 ID (默认 0)
    - VISION_API_KEY / VISION_API_BASE / VISION_MODEL_NAME: VisionModel 配置
    """

    name = "active_vision"
    description = "主动视觉感知 — 后台定时观测 → 注入系统提示词 + 场景变化主动通知"
    hooks = [HookPoint.PRE_PROCESS]
    priority = 26  # 在 MemoryPlugin(27) 之前，ModelPlugin(50) 之前

    def __init__(self, db=None):
        self._vision_model = None
        self._latest_observation: Optional[dict] = None
        self._observation_lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_observe_ts = 0.0
        self._db = db

        # 场景变化追踪
        self._prev_user_present: Optional[bool] = None
        self._prev_light_label: Optional[str] = None
        self._last_notification_ts = 0.0
        self._user_present_since: Optional[float] = None

    def set_db(self, db):
        """注入 DB 引用 (启动时调用)"""
        self._db = db

    def on_load(self) -> None:
        from config import Config
        if not Config.ACTIVE_VISION_ENABLED:
            logger.info("主动视觉感知未启用 (ACTIVE_VISION_ENABLED=false)")
            return
        logger.info("ActiveVisionPlugin 已加载, 启动观测线程 (interval=%ds)",
                     Config.ACTIVE_VISION_INTERVAL)
        self._running = True
        self._thread = threading.Thread(target=self._observation_loop, daemon=True)
        self._thread.start()

    def on_unload(self) -> None:
        self._running = False

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if hook != HookPoint.PRE_PROCESS:
            return ctx
        from config import Config
        if not Config.ACTIVE_VISION_ENABLED:
            return ctx

        observation = self._get_latest()
        if not observation:
            return ctx

        description = observation.get("description", "")
        if not description:
            return ctx

        # 注入到 system_prompt — 第一人称"你看到"
        ts = observation.get("timestamp", "")
        vision_block = (
            f"\n\n[视觉感知 — 你刚才看到 ({ts})]\n"
            f"{description}\n"
            f"（这是你通过摄像头实时看到的画面，是你的视觉感知）"
        )
        ctx.system_prompt += vision_block
        ctx.extra["active_vision_observation"] = observation

        return ctx

    # ── 内部: 观测循环 ──

    def _observation_loop(self):
        """后台观测线程：定时抓帧 → VisionModel 分析 → 缓存 + 场景变化检测"""
        from config import Config
        interval = Config.ACTIVE_VISION_INTERVAL
        camera_id = Config.CAMERA_DEVICE_ID

        while self._running:
            try:
                result = self._observe_once(camera_id)
                with self._observation_lock:
                    self._latest_observation = result
                    self._last_observe_ts = time.time()

                if result.get("success"):
                    desc = result.get("description", "")[:60]
                    logger.info("主动视觉观测完成: %s", desc)
                    # 场景变化检测 + 主动通知
                    self._check_scene_change(result)
                else:
                    logger.warning("主动视觉观测失败: %s", result.get("error", "未知错误"))
            except Exception as e:
                logger.error("主动视觉观测异常: %s", e)

            time.sleep(interval)

    def _check_scene_change(self, observation: dict):
        """
        检测场景变化 → 需要主动通知? → 写 task_notifications。
        触发条件:
          - 用户首次出现 (从无到有)
          - 用户离开后回来 (离开>5min 后重现)
          - 光线突变 (bright↔dim)
          - 距上次通知 > VISION_PROACTIVE_COOLDOWN (默认 600s)
        """
        from config import Config

        desc = observation.get("description", "")
        now = time.time()

        # 从描述中推断用户是否在场 (启发式)
        user_present = self._infer_user_presence(desc)
        light_label = self._infer_light(desc)

        prev_present = self._prev_user_present
        self._prev_user_present = user_present
        self._prev_light_label = light_label

        # 用户状态变化追踪
        if user_present and not prev_present:
            self._user_present_since = now
        elif not user_present and prev_present:
            self._user_present_since = None

        # ---- 判断是否需要触发通知 ----
        cooldown = getattr(Config, "ACTIVE_VISION_PROACTIVE_COOLDOWN", 600)
        if now - self._last_notification_ts < cooldown:
            return  # 冷却中

        should_notify = False
        reason = ""

        # 条件1: 用户首次出现
        if user_present and prev_present is False:
            should_notify = True
            reason = "user_appeared"

        # 条件2: 用户离开后回来 (离开了一段时间)
        elif user_present and prev_present is False:
            should_notify = True
            reason = "user_returned"

        # 条件3: 光线突变
        elif light_label and self._prev_light_label and light_label != self._prev_light_label:
            should_notify = True
            reason = "light_changed"

        # 条件4: 用户持续在场超过阈值，周期性提醒
        if not should_notify and user_present and self._user_present_since:
            session_duration = (now - self._user_present_since) / 60
            periodic_interval = getattr(Config, "ACTIVE_VISION_PERIODIC_NOTIFY_MIN", 30)
            if session_duration >= periodic_interval:
                should_notify = True
                reason = "periodic"

        if not should_notify:
            return

        # 写入 task_notifications
        self._write_vision_notification(observation, reason)
        self._last_notification_ts = now
        logger.info("场景变化触发视觉通知: reason=%s desc=%s", reason, desc[:50])

    def _write_vision_notification(self, observation: dict, reason: str):
        """写 vision 通知到 task_notifications 表，供心跳接口拉取"""
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
                "image_url": observation.get("image_url", ""),
                "params": {},
            }
            conn.execute(
                "INSERT INTO task_notifications "
                "(task_id, user_id, chat_id, result, delivered) "
                "VALUES (?, ?, ?, ?, 0)",
                (
                    task_id,
                    0,  # user_id=0 表示全局，心跳按 uid 查时会匹配
                    0,  # chat_id=0
                    json.dumps(notif_data, ensure_ascii=False),
                ),
            )
            conn.commit()
            logger.info("视觉通知已写入: task_id=%s reason=%s", task_id, reason)
        except Exception as e:
            logger.error("写入视觉通知失败: %s", e)

    @staticmethod
    def _infer_user_presence(desc: str) -> bool:
        """从 VisionModel 描述中推断用户是否在场"""
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
        # 默认: 如果描述长度>10 且提到"屏幕"/"电脑"/"桌子"等，假设用户在
        ambient_indicators = ["屏幕", "电脑", "桌子", "书桌", "键盘", "显示器",
                              "desk", "screen", "laptop", "computer", "monitor"]
        if len(desc) > 10:
            for ind in ambient_indicators:
                if ind in desc:
                    return True
        return False  # 保守默认

    @staticmethod
    def _infer_light(desc: str) -> Optional[str]:
        """从描述中提取光线标签"""
        desc_lower = desc.lower()
        if any(kw in desc_lower for kw in ["明亮", "亮", "bright", "阳光", "sunlight", "well-lit"]):
            return "bright"
        if any(kw in desc_lower for kw in ["昏暗", "暗", "黑暗", "dim", "dark", "仅屏幕", "只有屏幕"]):
            return "dim"
        if any(kw in desc_lower for kw in ["正常", "normal", "适中", "自然光"]):
            return "normal"
        return None

    def _observe_once(self, camera_id: int) -> dict:
        """单次观测：抓帧 → VisionModel 分析"""
        import cv2

        cap = cv2.VideoCapture(camera_id)
        if not cap.isOpened():
            return {"success": False, "error": "摄像头不可用"}

        ret, frame = cap.read()
        cap.release()
        if not ret:
            return {"success": False, "error": "无法读取画面"}

        # JPEG 编码
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, 70]
        success, buf = cv2.imencode(".jpg", frame, encode_params)
        if not success:
            return {"success": False, "error": "JPEG 编码失败"}

        b64 = base64.b64encode(buf).decode("utf-8")
        data_url = f"data:image/jpeg;base64,{b64}"

        # VisionModel 分析
        vm = self._get_vision_model()
        if vm is None:
            return {"success": False, "error": "VisionModel 不可用"}

        prompt = (
            "你是安装在电脑上的AI视觉系统，正在通过摄像头观察周围。"
            "请简洁描述你看到的画面：1) 是否有用户，用户在做什么；"
            "2) 环境光线和场景。控制在40字以内。"
        )

        try:
            description = vm.ask(data_url, prompt=prompt, max_tokens=256, temperature=0.1)
        except Exception as e:
            return {"success": False, "error": f"VisionModel 分析失败: {e}"}

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return {
            "success": True,
            "timestamp": now,
            "description": description.strip(),
            "image_url": data_url,
        }

    def _get_vision_model(self):
        """获取/缓存 VisionModel 实例"""
        if self._vision_model is not None:
            return self._vision_model
        try:
            from models.clients import VisionModel
            self._vision_model = VisionModel()
            return self._vision_model
        except Exception as e:
            logger.error("VisionModel 初始化失败: %s", e)
            return None

    def _get_latest(self) -> Optional[dict]:
        """线程安全获取最新观测"""
        with self._observation_lock:
            if self._latest_observation is None:
                return None
            return dict(self._latest_observation)

    def get_observation(self) -> Optional[dict]:
        """公开接口：获取最新观测结果"""
        return self._get_latest()
