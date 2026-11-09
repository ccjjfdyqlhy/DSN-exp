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
import threading
from pathlib import Path
from typing import Any, Optional

import requests

from infra.orchestrator.lmstudio import is_no_model_error

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


class OCRModel:
    """deepseek-ocr 客户端。纯视觉 → markdown 模型，无文本提示。

    下沉说明（迁移计划阶段 5.5）：此前这份实现在 apps/dsn/models/clients.py
    一份独苗（唯一没被下沉的模型客户端），与 dsn 的 ModelScheduler 耦合。
    本模块是唯一实现：配置显式传入、加载/卸载走 infra.models 层的
    LMStudio 助手，调度（managed）由调用方注入 use() 上下文管理器完成 ——
    infra 层不依赖任何应用的 Config 或调度器。

    用法:
        ocr = OCRModel(base_url="http://localhost:4502", model_name="deepseek-ocr")
        md = ocr.ocr(data_url)          # 单张 → markdown
        results = ocr.ocr_batch([...])  # 批量 → [{filename, markdown}]
        ocr.unload()                    # 手动卸载
    """

    def __init__(self, base_url: str = "", model_name: str = "",
                 auto_load: bool = True, unload_after_use: bool = True,
                 scheduler: Optional[Any] = None, timeout: int = 300):
        self.base_url = (base_url or "").rstrip("/")
        self.model_name = model_name or ""
        self.unload_after_use = bool(unload_after_use)
        self.timeout = timeout
        self.logger = logging.getLogger(self.__class__.__name__)
        self._http_session = requests.Session()
        self._load_lock = threading.Lock()
        self._model_ready = threading.Event()

        # 调度器（可选）：提供 use(model_name) 上下文管理器的对象
        # （如 ModelScheduler）。注入后按需换入换出由调度器接管。
        self._scheduler = scheduler
        if not self._scheduler and auto_load and self.model_name:
            self._ensure_loaded()

    # ── 公开 API ──

    def ocr(self, data_url: str, max_tokens: int = 4096) -> str:
        """对单张图片执行 OCR，返回 markdown 文本。"""
        results = self.ocr_batch([{"filename": "image", "data_url": data_url}],
                                 max_tokens)
        return results[0]["markdown"] if results else ""

    def ocr_batch(self, images: list, max_tokens: int = 4096) -> list:
        """批量 OCR。

        :param images: [{filename, data_url}, ...]
        :return: [{filename, markdown}, ...]

        非 scheduler 托管且 unload_after_use=true 时，完成全部处理后自动卸载。
        """
        results = []
        for img in images:
            filename = img.get("filename", "unknown")
            text = self._ocr_single(img.get("data_url", ""), max_tokens)
            results.append({"filename": filename, "markdown": text})
        self.logger.info("OCR 完成: %d 张 → %d 条结果", len(images), len(results))
        if not self._scheduler and self.unload_after_use:
            self.logger.info("unload_after_use=true，卸载模型")
            self.unload()
        return results

    def unload(self) -> bool:
        """卸载 LMStudio 端的模型。"""
        from infra.orchestrator.lmstudio import unload_lmstudio_model
        self._model_ready.clear()
        return unload_lmstudio_model(self.base_url, self.model_name)

    # ── 内部 ──

    def _ensure_loaded(self) -> bool:
        from infra.orchestrator.lmstudio import load_lmstudio_model
        with self._load_lock:
            if self._model_ready.is_set():
                return True
            ok = load_lmstudio_model(self.base_url, self.model_name,
                                     "OCR 模型", timeout=300)
            if ok:
                self._model_ready.set()
            return ok

    def _ocr_single(self, data_url: str, max_tokens: int) -> str:
        if not data_url:
            return ""

        messages = [{
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": data_url}}],
        }]
        payload = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0,
            "stream": False,
        }
        url = f"{self.base_url}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}

        def _do_request() -> str:
            result = _post_json(self._http_session, url, headers, payload,
                                self.timeout)
            if "choices" in result and result["choices"]:
                return result["choices"][0]["message"]["content"].strip()
            return ""

        # 调度路径：由调度器确保模型已加载
        if self._scheduler:
            with self._scheduler.use(self.model_name, timeout=self.timeout,
                                     immediate=True):
                return _do_request()

        # 传统路径：手动管理加载/卸载
        if self._model_ready.is_set():
            try:
                return _do_request()
            except requests.exceptions.HTTPError as e:
                if is_no_model_error(e.response):
                    self._model_ready.clear()
                else:
                    self.logger.error("OCR 请求失败: %s", e)
                    return ""

        with self._load_lock:
            if self._model_ready.is_set():
                return _do_request()
            try:
                result = _do_request()
                self._model_ready.set()
                return result
            except requests.exceptions.HTTPError as e:
                if is_no_model_error(e.response):
                    if self._ensure_loaded():
                        self._model_ready.set()
                        try:
                            return _do_request()
                        except Exception as e2:
                            self.logger.error("OCR 重试失败: %s", e2)
                            return ""
                self.logger.error("OCR 请求失败: %s", e)
                return ""
            except Exception as e:
                self.logger.error("OCR 请求失败: %s", e)
                return ""

    def __repr__(self) -> str:
        return f"<OCRModel model={self.model_name!r} base_url={self.base_url!r}>"
