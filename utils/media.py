# utils/media.py
# Shared image data URL helpers for vision and document ingestion.

from __future__ import annotations

import base64
from pathlib import Path


_IMAGE_MIME_TYPES = {
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".webp": "image/webp",
}


def image_mime_type(filename: str | Path, default: str = "image/png") -> str:
    """Return the data URL MIME type inferred from an image filename."""
    return _IMAGE_MIME_TYPES.get(Path(filename).suffix.lower(), default)


def image_data_url(data: bytes, mime_type: str = "image/png") -> str:
    """Encode image bytes as a base64 data URL."""
    encoded = base64.b64encode(data).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def image_file_data_url(path: str | Path, mime_type: str | None = None) -> str:
    """Read an image file and encode it as a base64 data URL."""
    image_path = Path(path)
    if not image_path.is_file():
        raise FileNotFoundError(f"图片文件不存在: {image_path}")
    return image_data_url(
        image_path.read_bytes(),
        mime_type or image_mime_type(image_path),
    )
