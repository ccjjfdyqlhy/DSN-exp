# visual_perception 技能工具 —— AI 可调用的视觉入口（迁移计划阶段 5.4）。
#
# look_around 的完整链路:
#   本工具 → VisionCoordinator.create_request（阻塞等待）
#        → /api/heartbeat 下发 vision_request 给边缘客户端
#        → 客户端抓帧 → POST /api/vision/frame 回传
#        → 唤醒本工具 → **把画面交给模型** → 返回给 AI
#
# 「交给模型」有两条路，按主模型能不能直接看图来选:
#   直发主模型（mode="direct"）:
#     画面原样作为图片附到本轮上下文里，模型看到的是**原图**而不是
#     别人的转述。返回 dict 的 images 字段带 data URL，由
#     harness/agent/adapters.py 的 build_round 摘出来转成 content parts
#     （图片必须放 role="user" —— tool 消息的 content 在协议上是字符串，
#      Anthropic 路径还会被 str() 拍平）。
#   VLM 转述（mode="vlm"）:
#     另起一次调用，让专用视觉模型把画面描述成文字再喂给模型。
#     主模型是纯文本模型时**只有这条路能走**。
#
# 选路依据是「主模型是否支持图片输入」的判定（apps/dsn_study/vision_support.py）：
#   显式配置 > 判别式探测（发一张写着 4 位数字的图，看它答不答得对）> 保守回退。
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
        # 主模型 chat_client（boot 注入）—— 用来判定主模型能不能直接看图。
        # 没有它就只走 VLM 转述（老路）。
        self._chat_client = None
        self._uid = 1
        # 去重缓存: (uid, camera, focus) -> (ts, result_dict)
        self._look_cache: dict[tuple, tuple] = {}

    # ── 工具 ──

    def _direct_to_main(self) -> bool:
        """本次是否走「把图直接发给主模型」。

        三道闸（任一不过就走 VLM 转述）：
          ① VISION_DIRECT_TO_MAIN 不为 off；
          ② 拿到了主模型 chat_client（没有就无从判定）；
          ③ 主模型经判定支持图片输入。
        判定本身在 apps/dsn_study/vision_support.py：显式配置优先，
        否则发一张写着 4 位数字的图看它答不答得对（纯文本模型答不对）。
        """
        try:
            from apps.dsn_study.vision_support import (
                direct_to_main_enabled, main_model_supports_images,
            )
            from apps.dsn_study.config import Config
        except Exception:   # noqa: BLE001 - 判定模块不可用时保守回退
            return False
        if not direct_to_main_enabled():
            return False
        if self._chat_client is None:
            return False
        try:
            return bool(main_model_supports_images(
                self._chat_client,
                model_name=getattr(Config, "MAIN_MODEL_NAME", ""),
                base_url=getattr(Config, "OPENAI_API_BASE", "")))
        except Exception as exc:   # noqa: BLE001
            logger.warning("主模型图片能力判定失败，回退 VLM 转述: %s", exc)
            return False

    def look_around(self, camera: str = "", focus: str = "") -> dict:
        """让客户端抓帧并把画面交给模型。超时/无摄像头时明确报错，不返回编造内容。

        返回的 dict 里，``mode`` 说明走的是哪条路:
          * ``"direct"`` —— 画面已作为图片直接附在上下文里（``images`` 字段
            带 data URL，由 harness 的 build_round 转成 content parts）；
          * ``"vlm"``    —— 画面已由视觉模型描述成文字（``observations`` 里
            带 description）。
        """
        if self._coordinator is None:
            return {"success": False, "error": "视觉系统未就绪（协调器未装配）"}

        from apps.dsn_study.config import Config
        dedup_secs = float(getattr(Config, "VISION_LOOK_AROUND_DEDUP", 10) or 0)

        # 先定模式再去查缓存：两种模式的产物形态不同（图片 vs 文字），
        # 混用会让后一次拿到另一种形态的结果。
        direct = self._direct_to_main()
        mode = "direct" if direct else "vlm"
        if not direct and self._models is None:
            return {"success": False, "error": "视觉模型未就绪"}

        key = (self._uid, camera or "", focus or "", mode)
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
        image_urls: list[str] = []
        for name, data_url in frames.items():
            cam_note = self._coordinator.get_camera_note(name) or note
            if direct:
                # 直发：画面原样交给主模型，不做任何文字转述。
                image_urls.append(data_url)
                obs = {"logical_name": name, "description": "",
                       "image_attached": True}
                if cam_note:
                    obs["camera_note"] = cam_note
                if focus:
                    obs["focus"] = focus
                observations.append(obs)
                continue
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

        logger.info("look_around: mode=%s cams=%s frames=%d",
                    mode, list(frames), len(frames))
        result = {
            "success": bool(observations),
            "observations": observations,
            "count": len(observations),
            "mode": mode,
        }
        if direct and image_urls:
            # data URL 放在**顶层** images 字段：harness 的 build_round 会把
            # 它摘出来转成 image_url 内容块，同时从回喂给模型的 JSON 里
            # 删掉 —— 否则几 MB 的 base64 会当文本灌进上下文。
            result["images"] = image_urls
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
