# visual_perception 技能工具 —— AI 可调用的视觉入口（迁移计划阶段 5.4）。
#
# look_around 的完整链路:
#   本工具 → VisionCoordinator.create_request（阻塞等待）
#        → /api/heartbeat 下发 vision_request 给边缘客户端
#        → 客户端抓帧 → POST /api/vision/frame 回传
#        → 唤醒本工具 → VisionModel 逐帧描述 → 返回给 AI
#
# dsn 缺陷修复（对照 apps/dsn/models/perception.py:36）：
#   dsn 的 look_around 去重缓存是**类级、跨用户共享** —— 用户 A 刚看过，
#   用户 B 在缓存窗口内问「你看到了什么」会拿到 A 的画面描述。
#   这里按 (uid, camera, focus) 键控，缓存存实例字段。

from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger("skill.visual_perception")


class VisualPerceptionTool:

    def __init__(self):
        self._coordinator = None      # VisionCoordinator（boot 注入）
        self._models = None           # LLMService（describe_image 契约）
        self._uid = 1
        # 去重缓存: (uid, camera, focus) -> (ts, result_dict)
        self._look_cache: dict[tuple, tuple] = {}

    # ── 工具 ──

    def look_around(self, camera: str = "", focus: str = "") -> dict:
        """让客户端抓帧并描述画面。超时/无摄像头时明确报错，不返回编造内容。"""
        if self._coordinator is None:
            return {"success": False, "error": "视觉系统未就绪（协调器未装配）"}
        if self._models is None:
            return {"success": False, "error": "视觉模型未就绪"}

        from apps.dsn_study.config import Config
        dedup_secs = float(getattr(Config, "VISION_LOOK_AROUND_DEDUP", 10) or 0)

        key = (self._uid, camera or "", focus or "")
        if dedup_secs > 0:
            cached = self._look_cache.get(key)
            if cached and time.time() - cached[0] < dedup_secs:
                result = dict(cached[1])
                result["cached"] = True
                return result

        request_id = self._coordinator.create_request(
            focus=focus, uid=self._uid, camera=camera or "")
        frames, error = self._coordinator.wait_with_error(request_id)
        if error and not frames:
            return {"success": False, "error": error}

        note = self._coordinator.get_camera_note(camera) if camera else ""
        observations = []
        errors = {}
        for name, data_url in frames.items():
            cam_note = self._coordinator.get_camera_note(name) or note
            prompt = getattr(Config, "VISION_PROMPT", "请详细描述这张图片的内容")
            if cam_note:
                prompt = f"（这台摄像头：{cam_note}）{prompt}"
            if focus:
                prompt = f"{prompt}\n（用户关注点：{focus}）"
            try:
                desc = self._models.describe_image(data_url, prompt)
                observations.append({"logical_name": name, "description": desc})
            except Exception as exc:
                logger.warning("画面描述失败 cam=%s: %s", name, exc)
                errors[name] = f"画面描述失败: {exc}"

        result = {
            "success": bool(observations),
            "observations": observations,
            "count": len(observations),
        }
        if errors:
            result["errors"] = errors
        if not observations and error:
            result["error"] = error
        if observations:
            self._look_cache[key] = (time.time(), result)
        return result

    def set_camera_note(self, logical_name: str, note: str) -> dict:
        """给摄像头写备注（持久化到 vision_cameras 表，重启不丢）。"""
        if self._coordinator is None:
            return {"success": False, "error": "视觉系统未就绪"}
        ok = self._coordinator.set_camera_note(logical_name, note)
        return {"success": bool(ok), "logical_name": logical_name, "note": note}

    def list_cameras(self) -> dict:
        """列出已登记摄像头。"""
        if self._coordinator is None:
            return {"success": False, "error": "视觉系统未就绪"}
        cameras = self._coordinator.list_cameras()
        return {"success": True, "cameras": cameras, "count": len(cameras)}

    # ── 供 boot 注入 uid（对齐 LocalAuthManager 单用户形态） ──

    def set_uid(self, uid: int) -> None:
        self._uid = int(uid)
