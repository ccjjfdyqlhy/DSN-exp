# models/clients.py
# 视觉多模态模型客户端 — 自参考实现 models/clients.py 移植的 VisionModel。
#
# 仅保留 dsn_study 用到的部分: ask / ask_raw / classify_image / ocr_md /
# encode_image，以及 quest_from_image 技能回退用的 LMStudioVisionFallback。

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path

import requests

logger = logging.getLogger("VisionModel")

_MIME_MAP = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
}


def _post_json(session: requests.Session, url: str, headers: dict,
               payload: dict, timeout) -> dict:
    response = session.post(url, headers=headers, json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def image_file_data_url(path, mime_type: str = None) -> str:
    """读取本地图片并编码为 base64 data URL。"""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"图片文件不存在: {p}")
    mime = mime_type or _MIME_MAP.get(p.suffix.lower(), "image/png")
    b64 = base64.b64encode(p.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


class VisionModel:
    """通用视觉多模态模型客户端，兼容 OpenAI 格式的视觉 API（GLM-4.6V/GPT-4V 等）。

    配置: VISION_API_KEY / VISION_API_BASE / VISION_MODEL_NAME
    """

    def __init__(self, api_key: str = None, base_url: str = None,
                 model_name: str = None, timeout: int = 120):
        from apps.dsn_study.config import Config

        self.api_key = api_key or Config.VISION_API_KEY
        self.base_url = (base_url or Config.VISION_API_BASE).rstrip("/")
        self.model_name = model_name or Config.VISION_MODEL_NAME
        self.timeout = timeout
        self.logger = logging.getLogger(self.__class__.__name__)
        self._http_session = requests.Session()

        if not self.api_key:
            self.logger.warning("VISION_API_KEY 未配置，视觉模型请求将无法通过需要认证的 API")

    @staticmethod
    def encode_image(image_path, mime_type: str = None) -> str:
        return image_file_data_url(image_path, mime_type)

    def ask(self, data_url: str, prompt: str = "请详细描述这张图片的内容",
            max_tokens: int = 2048, temperature: float = 0.1,
            extra_body: dict = None) -> str:
        """发送图片 + 文本提示到视觉模型，返回回复文本。"""
        if not data_url:
            raise ValueError("data_url 不能为空")

        payload = {
            "model": self.model_name,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": prompt},
                ],
            }],
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

        self.logger.info("VisionModel 请求: model=%s, prompt=%s",
                         self.model_name, prompt[:60] + ("..." if len(prompt) > 60 else ""))
        try:
            result = _post_json(self._http_session, url, headers, payload, self.timeout)
        except requests.exceptions.Timeout:
            self.logger.error("VisionModel 请求超时 (%ds)", self.timeout)
            raise
        except requests.exceptions.HTTPError as e:
            self.logger.error("VisionModel HTTP %d: %s",
                              e.response.status_code if e.response else 0,
                              e.response.text[:500] if e.response else str(e))
            raise
        except Exception as e:
            self.logger.error("VisionModel 请求失败: %s", e)
            raise

        if result.get("choices"):
            text = result["choices"][0]["message"]["content"].strip()
            self.logger.info("VisionModel 回复: %s", text[:80] + ("..." if len(text) > 80 else ""))
            return text
        self.logger.error("VisionModel 响应格式异常: %s", str(result)[:300])
        raise ValueError("视觉模型响应格式异常")

    def ask_raw(self, messages: list, max_tokens: int = 2048,
                temperature: float = 0.1, extra_body: dict = None) -> dict:
        """低级接口：直接发送自定义消息列表，返回完整 API 响应。"""
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
        return _post_json(self._http_session, url, headers, payload, self.timeout)

    # ── OCR / 文档分类（VISION_OVERRIDE 模式用） ──

    def classify_image(self, data_url: str, max_tokens: int = 100) -> str:
        """判断图片类型: document / photo / mixed。"""
        if not data_url:
            return "document"
        prompt = (
            "这张图片是文档（试卷、合同、书本、笔记等）还是照片（风景、人物、物品实拍等）？"
            "只回答一个词：document / photo / mixed"
        )
        try:
            text = self.ask(data_url, prompt=prompt, max_tokens=max_tokens, temperature=0)
            text = text.strip().lower()
            if "mixed" in text:
                return "mixed"
            if "photo" in text or "照片" in text:
                return "photo"
            return "document"
        except Exception:
            return "document"

    def ocr_md(self, data_url: str, max_tokens: int = 4096) -> str:
        """将图片转为 Markdown 文本。"""
        if not data_url:
            return ""
        prompt = (
            "请完整提取这张文档图片中的所有文字内容，输出为 Markdown 格式。"
            "保留原始排版结构（标题、列表、表格等），不要遗漏任何文字。"
        )
        try:
            return self.ask(data_url, prompt=prompt, max_tokens=max_tokens, temperature=0)
        except Exception as e:
            self.logger.error("ocr_md 失败: %s", e)
            return ""

    def __repr__(self):
        return f"<VisionModel base_url={self.base_url} model={self.model_name}>"


class LMStudioVisionFallback:
    """本地视觉回退：用 OpenAI 兼容端点（LMStudio 等）对图片做描述。

    quest_from_image 在未配置 VISION_API_KEY 时的兜底路径。
    """

    def __init__(self, model_name: str = None):
        from apps.dsn_study.config import Config
        self.base_url = (os.environ.get("LMSTUDIO_BASE_URL", "") or Config.LMSTUDIO_BASE_URL).rstrip("/")
        self.model_name = model_name or Config.MAIN_MODEL_NAME
        self.timeout = int(os.environ.get("LMSTUDIO_TIMEOUT", "300"))
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
        return result["choices"][0]["message"]["content"].strip()
