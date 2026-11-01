# apps/dsn_study/document/inputs.py
# 多来源文档输入归一化（移植自参考实现 DSN-exp document/inputs.py）。
#
# 差异：utils.media.image_file_data_url → infra.orchestrator.vision.image_file_data_url
#       （media 工具层未下沉到 infra，改用同实现的 vision 侧导出）。

from __future__ import annotations

import os
from typing import Any

from infra.orchestrator.vision import image_file_data_url


def normalize_document_inputs(inputs: list[Any]) -> list[dict]:
    """Normalize file paths and scanner result dictionaries into file records."""
    normalized: list[dict] = []
    for item in inputs:
        if isinstance(item, str):
            normalized.append({
                "filename": os.path.basename(item),
                "filepath": item,
                "size": os.path.getsize(item) if os.path.isfile(item) else 0,
            })
        elif isinstance(item, dict):
            normalized.append(dict(item))
    return normalized


def load_document_image(record: dict) -> tuple[str, str, str]:
    """Return a normalized image record's filename, path, and data URL."""
    filepath = record.get("filepath", "")
    filename = record.get("filename") or os.path.basename(filepath)
    if not filepath or not os.path.isfile(filepath):
        raise FileNotFoundError(filepath or filename)
    return filename, filepath, image_file_data_url(filepath)
