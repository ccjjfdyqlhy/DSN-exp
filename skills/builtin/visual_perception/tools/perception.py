# skills/builtin/visual_perception/tools/perception.py
# 视觉感知工具 — 摄像头抓帧 → VisionModel 分析 → 返回"你看到"的描述

from __future__ import annotations

import base64
import logging
import io
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger("skill.visual_perception")


class VisualPerceptionTool:
    """
    视觉感知工具。
    通过 OpenCV 抓取摄像头画面 → VisionModel 多模态分析 → 返回结构化视觉描述。
    描述以第一人称"你看到..."呈现，让主模型感知这是它自己的视觉。
    """

    _ctx: dict = {}  # 运行时注入

    def __init__(self):
        self._cap = None

    # ── 公开方法（被 SkillRegistry 调用） ──

    def look_around(self, focus: str = "") -> dict[str, Any]:
        """
        观察周围环境。
        :param focus: 关注焦点 ("user" / "environment" / "" 全面)
        :return: dict with success, description, ... 
        """
        from config import Config
        if not Config.CAMERA_ENABLED:
            return {
                "success": False,
                "error": "摄像头功能未启用 (CAMERA_ENABLED=false)",
                "description": "（摄像头已关闭，无法获取画面）",
            }
        try:
            frame, data_url = self._capture_frame()
        except Exception as e:
            logger.error("摄像头抓帧失败: %s", e)
            return {
                "success": False,
                "error": f"摄像头不可用: {e}",
                "description": "（视觉系统故障，无法获取画面）",
            }

        # 构造给 VisionModel 的提示词
        prompt = self._build_vision_prompt(focus)
        try:
            vm = self._get_vision_model()
            description = vm.ask(
                data_url=data_url,
                prompt=prompt,
                max_tokens=512,
                temperature=0.1,
            )
            logger.info("视觉感知完成: %s", description[:80])
        except Exception as e:
            logger.error("VisionModel 分析失败: %s", e)
            description = "（视觉分析失败）"

        # 构建回复 — 第一人称"你看到"，让主模型感觉这是自己的视觉
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        result = {
            "success": True,
            "timestamp": now,
            "description": description.strip(),
            "focus": focus or "全面",
            "image_url": data_url,  # 原始画面 data URL，供支持多模态的主模型直接"看到"
            "visual_prompt": (
                "你刚才通过摄像头看到了以下画面。这是你真实的眼睛看到的内容，"
                "不是文字描述，是你自己的视觉感知。你可以基于这个画面信息来理解当前环境。"
                f"\n\n画面分析结果（{now}）：\n{description.strip()}"
            ),
        }
        return result

    # ── 内部方法 ──

    def _capture_frame(self):
        """OpenCV 抓取一帧 → JPEG base64 data URL"""
        import cv2
        cap = cv2.VideoCapture(self._get_camera_id())
        if not cap.isOpened():
            raise RuntimeError("无法打开摄像头")

        ret, frame = cap.read()
        cap.release()
        if not ret:
            raise RuntimeError("无法读取摄像头画面")

        # JPEG 压缩（平衡质量与大小）
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, 75]
        success, buf = cv2.imencode(".jpg", frame, encode_params)
        if not success:
            raise RuntimeError("JPEG 编码失败")

        b64 = base64.b64encode(buf).decode("utf-8")
        data_url = f"data:image/jpeg;base64,{b64}"
        return frame, data_url

    def _build_vision_prompt(self, focus: str) -> str:
        base = (
            "你是一个视觉感知系统，正在通过摄像头观察周围环境。"
            "请用自然语言描述你看到的画面。"
        )
        if focus == "user":
            base += "请重点关注画面中是否有用户，用户在做什么（如打字、看书、离开座位等），用户的面部朝向和状态。"
        elif focus == "environment":
            base += "请重点关注环境状态：光线明暗、房间类型、桌面物品、窗外的光线情况等。"
        else:
            base += (
                "请描述：1) 是否有用户在画面中，用户在做什么；"
                "2) 环境光线、场景类型；"
                "3) 任何值得注意的细节。"
            )
        base += " 控制在50字以内，简洁直接。"
        return base

    def _get_vision_model(self):
        """获取 VisionModel 实例（优先使用已注入的，否则新建）"""
        vm = self._ctx.get("vision_model")
        if vm is not None:
            return vm
        # 懒加载
        from models.clients import VisionModel
        return VisionModel()

    def _get_camera_id(self) -> int:
        """获取摄像头设备 ID"""
        from config import Config
        return getattr(Config, "CAMERA_DEVICE_ID", 0)

    @classmethod
    def set_context(cls, vision_model=None, **kwargs):
        if vision_model is not None:
            cls._ctx["vision_model"] = vision_model
