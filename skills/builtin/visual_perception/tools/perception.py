# skills/builtin/visual_perception/tools/perception.py
# 视觉感知工具 — 摄像头抓帧已迁移到本地客户端(minimal.py)。
#
# look_around 流程:
#   Agent 调 look_around → VisionCoordinator.create_request (阻塞等待)
#     → /api/heartbeat 响应携带 vision_request
#     → minimal.py 本地 cv2 抓帧 → POST /api/vision/frame
#     → 唤醒 look_around → VisionModel 多模态分析 → 返回"你看到"的描述
#
# 客户端离线/超时则返回兜底描述。

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger("skill.visual_perception")


class VisualPerceptionTool:
    """
    视觉感知工具。
    摄像头抓帧由本地客户端(minimal.py)完成；本工具通过 VisionCoordinator
    向客户端请求一帧 → 经 VisionModel 多模态分析 → 返回结构化视觉描述。
    描述以第一人称"你看到..."呈现，让主模型感知这是它自己的视觉。
    """

    _ctx: dict = {}  # 运行时注入

    def __init__(self):
        pass

    # ── 公开方法（被 SkillRegistry 调用） ──

    def look_around(self, focus: str = "") -> dict[str, Any]:
        """
        观察周围环境。
        :param focus: 关注焦点 ("user" / "environment" / "" 全面)
        :return: dict with success, description, image_url, visual_prompt
        """
        from config import Config
        if not getattr(Config, "CAMERA_ENABLED", True):
            return {
                "success": False,
                "error": "摄像头功能未启用 (CAMERA_ENABLED=false)",
                "description": "（摄像头已关闭，无法获取画面）",
            }

        coord = self._get_coordinator()
        if coord is None:
            logger.error("VisionCoordinator 不可用，无法发起按需视觉请求")
            return {
                "success": False,
                "error": "VisionCoordinator 不可用",
                "description": "（视觉协调器不可用，无法获取画面）",
            }

        # 发起 on-demand 请求并阻塞等待客户端回传帧
        request_id = coord.create_request(focus=focus, uid=0)
        logger.info("look_around: 已发起视觉请求 %s, 阻塞等待客户端帧...", request_id)
        data_url = coord.wait(request_id)

        if not data_url:
            logger.warning("look_around: 客户端未在超时内回传帧, 返回兜底描述")
            return {
                "success": False,
                "error": "客户端未在超时内回传帧",
                "description": "（视觉系统暂不可用，客户端未响应）",
                "focus": focus or "全面",
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

    def _get_coordinator(self):
        """获取 VisionCoordinator 实例（优先用注入的，否则懒读 api.vision 模块单例）。

        注意: 必须每次调用时重新读取模块属性，而非 `from api.vision import coordinator`，
        因为该变量在 init_vision_api 时才被赋值，模块顶部导入会捕获到 None。
        """
        coord = self._ctx.get("coordinator")
        if coord is not None:
            return coord
        try:
            import api.vision as _vmod
            return getattr(_vmod, "coordinator", None)
        except Exception as e:
            logger.error("读取 api.vision.coordinator 失败: %s", e)
            return None

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

    @classmethod
    def set_context(cls, vision_model=None, coordinator=None, **kwargs):
        if vision_model is not None:
            cls._ctx["vision_model"] = vision_model
        if coordinator is not None:
            cls._ctx["coordinator"] = coordinator
