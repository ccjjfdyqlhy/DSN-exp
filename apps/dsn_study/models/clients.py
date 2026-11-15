# apps/dsn_study/models/clients.py
# 视觉多模态模型客户端 —— 薄封装。
#
# 去重说明（2026-10）：本文件此前**整份拷贝**了 apps/dsn/models/clients.py 里的
# VisionModel 实现（两边方法集只差一个 ocr_md_batch），属于典型的复制分叉。
# 现改为直接复用 infra/orchestrator/vision.py 的唯一实现，
# 本模块只负责「从本应用的 Config 取配置并注入」。

from __future__ import annotations

from infra.orchestrator.vision import (
    LMStudioVisionFallback as _BaseLMStudioVisionFallback,
    OCRModel as _BaseOCRModel,
    VisionModel as _BaseVisionModel,
    image_file_data_url,
)

__all__ = ["VisionModel", "LMStudioVisionFallback", "OCRModel",
           "image_file_data_url"]


class VisionModel(_BaseVisionModel):
    """DSN-Study 的视觉模型客户端：配置取自 apps.dsn_study.config.Config。"""

    def __init__(self, api_key: str = None, base_url: str = None,
                 model_name: str = None, timeout: int = 120):
        from apps.dsn_study.config import Config

        super().__init__(
            api_key=api_key or Config.VISION_API_KEY,
            base_url=base_url or Config.VISION_API_BASE,
            model_name=model_name or Config.VISION_MODEL_NAME,
            timeout=timeout,
        )


class LMStudioVisionFallback(_BaseLMStudioVisionFallback):
    """本地视觉回退：配置取自 apps.dsn_study.config.Config。

    为什么默认模型名**不能取 MAIN_MODEL_NAME**：
    主模型通常是**纯文本模型**（如 deepseek-v4.1-flash），把 image_url
    发给它，它要么被网关 400，要么**凭空编一段画面描述**——后者更糟，
    因为那段幻觉会被当成真实观察结果写进题库/笔记。
    （config.py 的「第六层: 视觉系统」里对此有明文警告。）

    现在只认两个来源：
      1. 显式传入的 model_name（调用方最清楚该用哪个视觉模型）；
      2. Config.VISION_FALLBACK_MODEL_NAME —— 显式配置的本地视觉模型名。
    两者都没有时保持空串（而不是回退到主模型）：让请求在端点处报错，
    好过悄悄把图片喂给一个看不见图的模型。
    """

    def __init__(self, model_name: str = None):
        import os
        from apps.dsn_study.config import Config

        fallback_model = (getattr(Config, "VISION_FALLBACK_MODEL_NAME", "") or "").strip()
        resolved = (model_name or fallback_model or "").strip()
        if not resolved:
            # 没有可用的本地视觉模型名 → 立刻报可执行的错，
            # 而不是发一个 model="" 的请求过去拿一个看不懂的 400。
            raise RuntimeError(
                "未配置本地视觉模型：LMStudioVisionFallback 需要显式传入 "
                "model_name，或设置 VISION_FALLBACK_MODEL_NAME。"
                "**不会**回退到 MAIN_MODEL_NAME —— 主模型可能是纯文本模型，"
                "把图片喂给它会得到凭空编造的描述而不是报错。")
        super().__init__(
            # 只有显式传入才用传入值；否则用显式配置的视觉模型名。
            # **绝不**回退到 Config.MAIN_MODEL_NAME（见上方 docstring）。
            model_name=resolved,
            base_url=(os.environ.get("LMSTUDIO_BASE_URL", "")
                     or Config.LMSTUDIO_BASE_URL),
            timeout=int(os.environ.get("LMSTUDIO_TIMEOUT", "300")),
        )


class OCRModel(_BaseOCRModel):
    """DSN-Study 的 OCR 客户端（deepseek-ocr）：配置取自本应用 Config。

    infra 的唯一实现在 infra/orchestrator/vision.py（迁移计划阶段 5.5 上提），
    本封装只负责从 Config 取 base_url / model_name 并注入。
    """

    def __init__(self, base_url: str = None, model_name: str = None,
                 auto_load: bool = True, managed: bool = False):
        from apps.dsn_study.config import Config

        super().__init__(
            base_url=base_url or Config.OCR_BASE_URL,
            model_name=model_name or Config.OCR_MODEL,
            auto_load=auto_load,
            unload_after_use=getattr(Config, "OCR_UNLOAD_AFTER_USE", True),
        )
