# apps/dsn_study/models/asr_client.py
# ASR 旁路服务 HTTP 客户端 —— 对标 models/tts_client.py 的最小闭环。
#
# 服务端契约（apps/dsn_study/asr_server.py）：
#   GET  {base}/health  → 200 {"ready":true,"loaded":bool,"model":...,"device":...}
#   POST {base}/warmup  → 200 {"loaded":true,...}
#   POST {base}/asr     → 200 {"text":"...","segments":[...],"elapsed":0.12}
#                          body: 原始音频字节（application/octet-stream）
#
# 与参考实现 apps/dsn/models/asr_engine.py 的差异：
#   * 参考版在**进程内**直接持有 FunASR AutoModel 对象（宿主 python 装不了 torch）；
#     这里改成 HTTP 调 sidecar，模型跑在 conda 环境里。
#   * 参考版直接调 model.generate()；这里转成一次 HTTP POST。

from __future__ import annotations

import logging

import requests

logger = logging.getLogger("ASRClient")


class ASRRequestError(Exception):
    """ASR 服务请求失败（网络 / 状态码 / 响应体异常）。"""


class ASRClient:
    """ASR 旁路服务 HTTP 客户端。"""

    def __init__(self, base_url: str, timeout: float = 120.0):
        self.base_url = (base_url or "").rstrip("/")
        self.timeout = float(timeout)
        self.session = requests.Session()

    def transcribe(self, audio_bytes: bytes) -> tuple[str, list]:
        """识别音频，返回 (text, segments)。失败抛 ASRRequestError。"""
        if not self.base_url:
            raise ASRRequestError("ASR base_url 未配置")
        if not audio_bytes:
            raise ASRRequestError("音频为空")
        url = self.base_url + "/asr"
        try:
            resp = self.session.post(
                url,
                data=audio_bytes,
                headers={"Content-Type": "application/octet-stream"},
                timeout=self.timeout,
            )
        except requests.exceptions.RequestException as e:
            raise ASRRequestError("请求 ASR 服务失败: %s" % e) from e
        if resp.status_code >= 400:
            detail = ""
            try:
                detail = (resp.json() or {}).get("error", "")
            except Exception:  # noqa: BLE001 —— 错误体不是 JSON 时按原文截断
                detail = (resp.text or "")[:200]
            raise ASRRequestError("ASR 服务返回 %d: %s" % (resp.status_code, detail))
        try:
            payload = resp.json() or {}
        except Exception as e:
            raise ASRRequestError("ASR 服务响应不是合法 JSON: %s" % e) from e
        text = (payload.get("text") or "").strip()
        segments = payload.get("segments") or []
        if not isinstance(segments, list):
            segments = []
        return text, segments

    def probe(self, timeout: float = 3.0) -> bool:
        """就绪探测：GET {base}/health。服务活着即视为就绪。"""
        if not self.base_url:
            return False
        try:
            resp = self.session.get(self.base_url + "/health", timeout=timeout)
        except requests.exceptions.RequestException:
            return False
        return resp.status_code < 500

    def health(self, timeout: float = 3.0) -> dict:
        """拉取完整健康信息（模型是否已加载等）。失败返回 {}。"""
        if not self.base_url:
            return {}
        try:
            resp = self.session.get(self.base_url + "/health", timeout=timeout)
        except requests.exceptions.RequestException:
            return {}
        if resp.status_code >= 400:
            return {}
        try:
            return resp.json() or {}
        except Exception:  # noqa: BLE001
            return {}

    def warmup(self, timeout: float = 600.0) -> bool:
        """请求服务端加载模型（阻塞）。成功返回 True。"""
        if not self.base_url:
            return False
        try:
            resp = self.session.post(self.base_url + "/warmup", timeout=timeout)
        except requests.exceptions.RequestException as e:
            raise ASRRequestError("ASR 预热请求失败: %s" % e) from e
        return resp.status_code < 400

    def __repr__(self) -> str:
        return "<ASRClient base_url=%s>" % self.base_url
