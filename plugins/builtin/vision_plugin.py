# plugins/builtin/vision_plugin.py
# 视觉插件 — 检测图片输入 → 多模态转文字 → 注入 message (PRE_PROCESS, priority=28)

from __future__ import annotations

import logging
import re
from typing import Optional

from plugins.base import Plugin, HookPoint, PluginContext

logger = logging.getLogger("VisionPlugin")

DATA_URL_PATTERN = re.compile(r"data:image/\w+;base64,[A-Za-z0-9+/=]+")


class VisionPlugin(Plugin):
    """
    图片输入转换插件。

    PRE_PROCESS 阶段 (priority=28, 在 MemoryPlugin 之后 MODEL_INVOKE 之前):
    1. 检测 ctx.image_data 或 ctx.message 中嵌入的 data URL
    2. 调用 ModelsPlugin.describe_image() → 本地 LMStudio 多模态模型
    3. 将图片文字描述注入 ctx.message，原始 image_data 存入 ctx.extra

    依赖:
    - models_plugin (ModelsPlugin) — 调用 describe_image

    配置 (通过环境变量):
    - VISION_ENABLED: 是否启用 (默认 true)
    - VISION_PROMPT: 图片描述提示词 (默认 "请详细描述这张图片的内容")
    """

    name = "vision"
    description = "图片输入转文字 — 多模态模型描述 → 注入消息上下文"
    hooks = [HookPoint.PRE_PROCESS]
    priority = 28

    def __init__(self, models_plugin=None):
        self._models = models_plugin

    def on_load(self) -> None:
        if self._models is None:
            logger.warning("models_plugin 未注入，VisionPlugin 将跳过图片处理")

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if hook != HookPoint.PRE_PROCESS:
            return ctx
        if self._models is None:
            return ctx

        data_url = self._extract_image(ctx)
        if not data_url:
            return ctx

        logger.info("检测到图片输入 (len=%d), 开始多模态转换", len(data_url))
        try:
            from config import Config
            prompt = getattr(Config, 'VISION_PROMPT', "请详细描述这张图片的内容")
            description = self._models.describe_image(data_url, prompt)
        except Exception as e:
            logger.error("图片描述失败: %s", e)
            ctx.message = f"[无法识别图片: {e}]\n{ctx.message}"
            return ctx

        ctx.message = f"[图片描述: {description}]\n{ctx.message}"
        ctx.extra["image_description"] = description
        ctx.extra["image_data_url"] = data_url
        ctx.image_data = None

        logger.info("图片转换完成 (desc_len=%d)", len(description))
        return ctx

    @staticmethod
    def _extract_image(ctx: PluginContext) -> Optional[str]:
        if ctx.image_data:
            return ctx.image_data

        match = DATA_URL_PATTERN.search(ctx.message)
        if match:
            return match.group(0)

        return None
