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
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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

    # 短时去重缓存: "camera|focus" -> (ts, result)。短时间内重复 look_around 直接复用，
    # 避免同一轮 agent 循环内重复触发昂贵的"抓帧 + 多摄像头 VLM 推理"。
    _look_cache: dict[str, tuple[float, dict]] = {}
    _look_cache_lock = threading.Lock()

    def __init__(self):
        pass

    # ── 公开方法（被 SkillRegistry 调用） ──

    def look_around(self, focus: str = "", camera: str = "") -> dict[str, Any]:
        """
        观察周围环境。
        :param focus: 关注焦点 ("user" / "environment" / "" 全面)
        :param camera: 目标摄像头逻辑名（如 cam0 / front）。空或 "all" 时枚举全部摄像头，
                       逐台抓帧并分别描述，返回 逻辑名+描述 列表。
        :return: dict with success, description, cameras[{logical_name, description, note}]
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

        # 首次/全部: 枚举全部摄像头；否则按逻辑名抓单台
        request_camera = camera if camera not in ("", "all", "all_cameras") else "all"

        # 短时去重：同一 focus+camera 在去重窗口内重复观察 → 直接复用上次结果
        cached = self._get_look_cache(request_camera, focus)
        if cached is not None:
            logger.info("look_around: 命中短时去重缓存 (camera=%r, focus=%r)，直接复用",
                        request_camera, focus or "全面")
            return cached

        # 发起 on-demand 请求并阻塞等待客户端回传帧
        request_id = coord.create_request(focus=focus, uid=0, camera=request_camera)
        logger.info("look_around: 已发起视觉请求 %s (camera=%r), 阻塞等待客户端帧...",
                    request_id, request_camera)
        try:
            frames, wait_error = coord.wait_with_error(request_id)
        except AttributeError:
            # 旧协调器兼容
            frames = coord.wait(request_id)
            wait_error = "客户端未在超时内回传帧" if not frames else ""

        if not frames:
            logger.warning("look_around: %s", wait_error or "客户端未响应")
            return {
                "success": False,
                "error": wait_error or "客户端未在超时内回传帧",
                "description": f"（{wait_error or '视觉系统暂不可用'}）",
                "focus": focus or "全面",
                "camera": request_camera,
            }

        # 逐台抓帧交给视觉模型描述（多摄像头并行推理，按逻辑名保序）
        prompt = self._build_vision_prompt(focus)
        cameras_desc = self._describe_frames_parallel(frames, prompt, coord)

        # 单摄像头时保持向后兼容的顶层字段；多摄像头时返回列表
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        result = {
            "success": True,
            "timestamp": now,
            "focus": focus or "全面",
            "camera": request_camera,
            "cameras": cameras_desc,
        }
        if len(cameras_desc) == 1:
            c = cameras_desc[0]
            result["description"] = c["description"]
            result["image_url"] = frames.get(c["logical_name"])
        else:
            parts = [f"{c['logical_name']}: {c['description']}" for c in cameras_desc]
            result["description"] = "\n".join(parts)

        visual_prompt = self._build_visual_prompt(result, now)
        result["visual_prompt"] = visual_prompt
        self._store_look_cache(request_camera, focus, result)
        logger.info("视觉感知完成: %d 台摄像头", len(cameras_desc))
        return result

    def set_camera_note(self, logical_name: str, note: str) -> dict[str, Any]:
        """给指定摄像头写备注，便于后续调用时识别其用途/位置。"""
        coord = self._get_coordinator()
        if coord is None:
            return {"success": False, "error": "VisionCoordinator 不可用"}
        ok = coord.set_camera_note(logical_name, note)
        return {"success": ok, "logical_name": logical_name, "note": note}

    def list_cameras(self) -> dict[str, Any]:
        """列出已登记摄像头及其备注。"""
        coord = self._get_coordinator()
        if coord is None:
            return {"success": False, "error": "VisionCoordinator 不可用", "cameras": []}
        return {"success": True, "cameras": coord.list_cameras()}

    def _describe_frame(self, data_url: str, prompt: str, logical_name: str) -> str:
        """给一张帧调用视觉模型，返回描述；失败返回兜底文本。"""
        try:
            vm = self._get_vision_model()
            return vm.ask(data_url=data_url, prompt=prompt, max_tokens=512, temperature=0.1)
        except Exception as e:
            logger.error("VisionModel 分析失败 (camera=%s): %s", logical_name, e)
            return "（视觉分析失败）"

    def _describe_camera(self, data_url: str, prompt: str, logical_name: str,
                         coord) -> dict[str, Any]:
        """描述单台摄像头 + 附带备注（供并行调用）。"""
        description = self._describe_frame(data_url, prompt, logical_name)
        note = ""
        try:
            note = coord.list_cameras_note(logical_name)
        except Exception:
            pass
        return {
            "logical_name": logical_name,
            "description": description,
            "note": note,
        }

    def _describe_frames_parallel(self, frames: dict[str, str], prompt: str, coord
                                  ) -> list[dict[str, Any]]:
        """并行描述多台摄像头帧，按逻辑名保序返回。"""
        items = sorted(frames.items())
        if len(items) <= 1:
            return [self._describe_camera(data_url, prompt, ln, coord) for ln, data_url in items]
        results: list[dict[str, Any]] = []
        workers = min(len(items), 4)
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="vision-vlm") as ex:
            futures = {
                ex.submit(self._describe_camera, data_url, prompt, ln, coord): ln
                for ln, data_url in items
            }
            for fut in as_completed(futures):
                try:
                    results.append(fut.result())
                except Exception as e:
                    ln = futures[fut]
                    logger.error("并行视觉描述失败 (camera=%s): %s", ln, e)
                    results.append({
                        "logical_name": ln,
                        "description": "（视觉分析失败）",
                        "note": "",
                    })
        results.sort(key=lambda c: c["logical_name"])
        return results

    def _get_look_cache(self, camera: str, focus: str) -> dict | None:
        """命中短时去重缓存则返回结果副本，否则 None。窗口由 Config 控制。"""
        try:
            from config import Config
            window = float(getattr(Config, "VISION_LOOK_AROUND_DEDUP", 10))
        except Exception:
            window = 10.0
        if window <= 0:
            return None
        key = f"{camera}|{focus or ''}"
        with self._look_cache_lock:
            entry = self._look_cache.get(key)
            if not entry:
                return None
            ts, result = entry
            if time.time() - ts > window:
                self._look_cache.pop(key, None)
                return None
            return dict(result)

    def _store_look_cache(self, camera: str, focus: str, result: dict) -> None:
        with self._look_cache_lock:
            self._look_cache[f"{camera}|{focus or ''}"] = (time.time(), result)

    def _build_visual_prompt(self, result: dict, now: str) -> str:
        """构建第一人称"你看到"提示，注入主模型。"""
        desc = result.get("description", "")
        if result.get("cameras") and len(result["cameras"]) > 1:
            lines = []
            for c in result["cameras"]:
                note = f"（备注: {c['note']}）" if c.get("note") else ""
                lines.append(f"- {c['logical_name']}: {c['description']}{note}")
            desc = "\n".join(lines)
        return (
            "你刚才通过摄像头看到了以下画面。这是你真实的眼睛看到的内容，"
            "不是文字描述，是你自己的视觉感知。你可以基于这些画面信息来理解当前环境。"
            f"\n\n画面分析结果（{now}）：\n{desc}"
        )

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
