# apps/dsn_study/models/tts_client.py
# GPT-SoVITS HTTP 客户端 —— 极简实现，只保留 dsn_study 需要的合成能力。
#
# 与参考实现 apps/dsn/audio/infer.py 的差异：
#   * 参考版带架构自适应、重试、流式、多套 profile 管理与调试落盘；
#     dsn_study 只需「按 profile 造参数 → POST → 拿音频字节」，故这里只留最小闭环。
#   * 端点由 profile.architecture 决定（parallel → /tts，serial → /）。
#
# 服务端契约（GPT-SoVITS api.py）：
#   POST {base}/tts  body: text / text_lang / ref_audio_path / prompt_lang / prompt_text ...
#   POST {base}/    body: text / text_language / refer_wav_path / prompt_language / prompt_text ...
#   响应：音频二进制（wav / raw / ogg / aac，由 media_type 决定）

from __future__ import annotations

import logging

import requests

logger = logging.getLogger("TTSClient")


class TTSRequestError(Exception):
    """TTS 服务请求失败（网络 / 状态码 / 响应体异常）。"""


class TTSClient:
    """GPT-SoVITS HTTP 客户端。"""

    def __init__(self, base_url: str, timeout: float = 120.0):
        self.base_url = (base_url or "").rstrip("/")
        self.timeout = float(timeout)
        self.session = requests.Session()

    def synthesize(self, params: dict, architecture: str = "parallel") -> bytes:
        """合成语音，返回音频字节。失败抛 TTSRequestError。"""
        if not self.base_url:
            raise TTSRequestError("TTS base_url 未配置")
        if not params or not params.get("text"):
            raise TTSRequestError("待合成文本为空")
        endpoint = "/" if architecture == "serial" else "/tts"
        url = self.base_url + endpoint
        try:
            resp = self.session.post(url, json=params, timeout=self.timeout)
        except requests.exceptions.RequestException as e:
            raise TTSRequestError("请求 TTS 服务失败: %s" % e) from e
        if resp.status_code >= 400:
            raise TTSRequestError("TTS 服务返回 %d: %s" % (
                resp.status_code, (resp.text or "")[:200]))
        audio = resp.content or b""
        if not audio:
            raise TTSRequestError("TTS 服务返回空音频")
        return audio

    def probe(self, timeout: float = 3.0) -> bool:
        """就绪探测：GET base_url。GPT-SoVITS 缺参数时会返回 400，也算已就绪。"""
        if not self.base_url:
            return False
        try:
            resp = self.session.get(self.base_url + "/", timeout=timeout)
        except requests.exceptions.RequestException:
            return False
        return resp.status_code < 500

    def __repr__(self) -> str:
        return "<TTSClient base_url=%s>" % self.base_url
