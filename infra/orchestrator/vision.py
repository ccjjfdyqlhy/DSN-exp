# infra/orchestrator/vision.py
# 视觉多模态模型客户端 —— OpenAI 兼容的 vision API。
#
# 下沉说明（2026-10 消除三套模型层）：
#   这份实现此前在 apps/dsn/models/clients.py 与 apps/dsn_study/models/clients.py
#   各存了一份几乎相同的拷贝（两边方法集只差一个 ocr_md_batch，配置来源不同），
#   属于典型的「复制后各自演进」重复。本模块是唯一实现，两个应用改为薄封装：
#       from infra.orchestrator.vision import VisionModel
#   配置（api_key / base_url / model_name）由调用方显式传入，
#   因此 infra 层不依赖任何应用的 Config。

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any, Optional

import requests

logger = logging.getLogger("infra.vision")


#: 显式 MIME 映射（比 mimetypes 更严格，避免把 .jpg 判成 image/jpg 之类）
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
    """按文件后缀推断图片 MIME 类型。"""
    return _IMAGE_MIME_TYPES.get(Path(filename).suffix.lower(), default)


def image_data_url(data: bytes, mime_type: str = "image/png") -> str:
    """把图片字节编码成 Base64 data URL。"""
    return f"data:{mime_type};base64,{base64.b64encode(data).decode('ascii')}"


def image_file_data_url(path: str | Path, mime_type: Optional[str] = None) -> str:
    """读取本地图片并编码成 data URL。"""
    image_path = Path(path)
    if not image_path.is_file():
        raise FileNotFoundError(f"图片文件不存在: {image_path}")
    mime = mime_type or image_mime_type(image_path)
    return image_data_url(image_path.read_bytes(), mime)


def _post_json(session: requests.Session, url: str, headers: dict,
               payload: dict, timeout) -> dict:
    response = session.post(url, headers=headers, json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


class VisionModel:
    """通用视觉多模态模型客户端，兼容 OpenAI 格式的视觉 API（GLM-4.6V / GPT-4V 等）。

    用法：
        vm = VisionModel(api_key="...", base_url="https://.../v4", model_name="glm-4.6v")
        desc = vm.ask(image_data_url, prompt="描述这张图片")

    所有配置均由调用方显式传入，本类不读取任何环境变量或应用配置。
    """

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None,
                 model_name: Optional[str] = None, timeout: int = 120):
        self.api_key = api_key or ""
        self.base_url = (base_url or "").rstrip("/")
        self.model_name = model_name or ""
        self.timeout = timeout
        self.logger = logging.getLogger(self.__class__.__name__)
        self._http_session = requests.Session()

        if not self.api_key:
            self.logger.warning(
                "VISION_API_KEY 未配置，视觉模型请求将无法通过需要认证的 API")

    @staticmethod
    def encode_image(image_path: str | Path, mime_type: Optional[str] = None) -> str:
        """读取本地图片并转为 Base64 data URL。"""
        return image_file_data_url(image_path, mime_type)

    def ask(self, data_url: str, prompt: str = "请详细描述这张图片的内容",
            max_tokens: int = 2048, temperature: float = 0.1,
            extra_body: Optional[dict] = None) -> str:
        """发送图片 + 文本提示到视觉模型，返回回复文本。"""
        if not data_url:
            raise ValueError("data_url 不能为空")

        messages = [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": data_url}},
                {"type": "text", "text": prompt},
            ],
        }]

        payload = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        if extra_body:
            payload.update(extra_body)

        url = f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        self.logger.info(
            "VisionModel 请求: model=%s, prompt=%s",
            self.model_name, prompt[:60] + ("..." if len(prompt) > 60 else ""))

        try:
            result = _post_json(
                self._http_session, url, headers, payload, self.timeout,
            )
        except requests.exceptions.Timeout:
            self.logger.error("VisionModel 请求超时 (%ds)", self.timeout)
            raise
        except requests.exceptions.HTTPError as e:
            self.logger.error(
                "VisionModel HTTP %d: %s",
                e.response.status_code if e.response else 0,
                e.response.text[:500] if e.response else str(e))
            raise
        except Exception as e:
            self.logger.error("VisionModel 请求失败: %s", e)
            raise

        return (result.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()

    def ask_raw(self, messages: list, max_tokens: int = 2048,
                temperature: float = 0.1,
                extra_body: Optional[dict] = None) -> Any:
        """直接发送构造好的 messages，返回原始 JSON。"""
        payload = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        if extra_body:
            payload.update(extra_body)

        url = f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        result = _post_json(
            self._http_session, url, headers, payload, self.timeout,
        )
        return result

    def classify_image(self, data_url: str, max_tokens: int = 100) -> str:
        """对图片做分类，返回简短标签。"""
        return self.ask(
            data_url,
            prompt="用一句话描述这张图片的类别，只输出类别名称。",
            max_tokens=max_tokens, temperature=0.1,
        )

    def ocr_md(self, data_url: str, max_tokens: int = 4096) -> str:
        """把图片转成 Markdown（OCR + 结构化）。"""
        return self.ask(
            data_url,
            prompt="识别图片中的全部文字，按 Markdown 格式输出，保留题目结构与公式。",
            max_tokens=max_tokens, temperature=0.1,
        )

    def ocr_md_batch(self, images: list, max_tokens: int = 4096) -> list:
        """批量 OCR：images 为 [{"data_url": ..., "name": ...}]。"""
        results: list = []
        for item in images or []:
            url = item.get("data_url") if isinstance(item, dict) else item
            name = item.get("name", "") if isinstance(item, dict) else ""
            try:
                text = self.ocr_md(url, max_tokens=max_tokens)
                results.append({"name": name, "success": True, "content": text})
            except Exception as e:  # noqa: BLE001 - 单张失败不影响整批
                self.logger.warning("批量 OCR 单张失败 (%s): %s", name, e)
                results.append({"name": name, "success": False, "error": str(e)})
        return results

    def __repr__(self) -> str:
        return f"<VisionModel model={self.model_name!r} base_url={self.base_url!r}>"


class LMStudioVisionFallback:
    """本地视觉回退：用 OpenAI 兼容端点（LM Studio 等）对图片做描述。

    用于没有配置远程 VISION_API_KEY 时的兜底路径。
    """

    def __init__(self, model_name: Optional[str] = None,
                 base_url: Optional[str] = None, timeout: Optional[int] = None):
        self.base_url = (base_url or "").rstrip("/")
        self.model_name = model_name or ""
        self.timeout = timeout or 300
        self._session = requests.Session()

    def describe_image(self, data_url: str, prompt: str) -> str:
        payload = {
            "model": self.model_name,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": prompt},
                ],
            }],
            "max_tokens": 2048,
            "stream": False,
        }
        result = _post_json(self._session, f"{self.base_url}/chat/completions",
                            {"Content-Type": "application/json"}, payload, self.timeout)
        return (result.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()

    def __repr__(self) -> str:
        return f"<LMStudioVisionFallback model={self.model_name!r}>"
