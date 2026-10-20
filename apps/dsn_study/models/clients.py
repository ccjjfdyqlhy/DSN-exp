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
    VisionModel as _BaseVisionModel,
    image_file_data_url,
)

__all__ = ["VisionModel", "LMStudioVisionFallback", "image_file_data_url"]


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
    """本地视觉回退：配置取自 apps.dsn_study.config.Config。"""

    def __init__(self, model_name: str = None):
        import os
        from apps.dsn_study.config import Config

        super().__init__(
            model_name=model_name or Config.MAIN_MODEL_NAME,
            base_url=(os.environ.get("LMSTUDIO_BASE_URL", "")
                     or Config.LMSTUDIO_BASE_URL),
            timeout=int(os.environ.get("LMSTUDIO_TIMEOUT", "300")),
        )
