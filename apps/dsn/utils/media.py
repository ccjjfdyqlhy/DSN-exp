# apps/dsn/utils/media.py
# 图片 data URL 辅助函数 —— 兼容再导出层。
#
# 去重说明（2026-10）：本模块此前自己实现了一份 image_mime_type / image_data_url /
# image_file_data_url，与 infra/orchestrator/vision.py 的同名实现重复（仅 MIME 映射表
# 来源不同：这里用固定表，那里用 mimetypes 推断）。现统一到 infra，本模块只做再导出，
# 保持 `from apps.dsn.utils.media import image_file_data_url` 的旧写法可用。

from __future__ import annotations

from infra.orchestrator.vision import (
    image_data_url,
    image_file_data_url,
    image_mime_type,
)

__all__ = ["image_mime_type", "image_data_url", "image_file_data_url"]
