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
import re
from typing import Iterator, Optional

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

    # ── 流式合成 ──

    #: 分句标点：GPT-SoVITS 的流式是按 cut_punc 切句后逐句合成，
    #: 不传 cut_punc 会把整段当一句（chunks=1，流式形同虚设）。
    DEFAULT_CUT_PUNC = "，。？；！"

    def synthesize_stream(
        self,
        params: dict,
        architecture: str = "parallel",
        *,
        cut_punc: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Iterator[bytes]:
        """流式合成：按句产出音频块（generator）。

        服务端契约：GPT-SoVITS 以 ``-sm normal`` 启动时，响应为
        ``Transfer-Encoding: chunked`` 的音频流，每句一个 chunk。
        本方法把 chunk 逐个 yield 给上层，从而做到「第一句合成完就能播」。

        ⚠️ 必须传 ``cut_punc``：不传时服务端不切句，只回 1 个 chunk，
        首包延迟等于整段合成时间（实测 3.9~4.5s vs 切句后 1.15~1.35s）。

        ⚠️ 服务端若以 ``-sm close``（默认）启动，本方法仍能工作，但
        只会有 1 个 chunk —— 调用方应通过 :meth:`probe_streaming` 预先确认。
        """
        if not self.base_url:
            raise TTSRequestError("TTS base_url 未配置")
        if not params or not params.get("text"):
            raise TTSRequestError("待合成文本为空")

        endpoint = "/" if architecture == "serial" else "/tts"
        url = self.base_url + endpoint
        body = dict(params)
        body.setdefault("cut_punc", cut_punc or self.DEFAULT_CUT_PUNC)
        # serial 架构（GPT-SoVITS 原生 api.py）只认 text_language 这一套键名
        if architecture == "serial":
            body.pop("text_lang", None)
            body.pop("ref_audio_path", None)
            body.pop("prompt_lang", None)
            body.setdefault("text_language", params.get("text_lang", "zh"))
            if "refer_wav_path" not in body and params.get("ref_audio_path"):
                body["refer_wav_path"] = params["ref_audio_path"]
            if "prompt_language" not in body and params.get("prompt_lang"):
                body["prompt_language"] = params["prompt_lang"]

        eff_timeout = float(timeout if timeout is not None else self.timeout)
        try:
            resp = self.session.post(url, json=body, timeout=eff_timeout,
                                     stream=True)
        except requests.exceptions.RequestException as e:
            raise TTSRequestError("请求 TTS 流式服务失败: %s" % e) from e

        if resp.status_code >= 400:
            detail = ""
            try:
                detail = (resp.text or "")[:200]
            except Exception:
                pass
            resp.close()
            raise TTSRequestError("TTS 服务返回 %d: %s"
                                  % (resp.status_code, detail))

        def _iter() -> Iterator[bytes]:
            try:
                for chunk in resp.iter_content(chunk_size=None):
                    if chunk:
                        yield chunk
            except Exception as e:   # noqa: BLE001 - 流中断按请求失败处理
                raise TTSRequestError("TTS 流式读取中断: %s" % e) from e
            finally:
                try:
                    resp.close()
                except Exception:
                    pass

        return _iter()

    def probe_streaming(self, params: Optional[dict] = None,
                        architecture: str = "serial",
                        timeout: float = 30.0) -> bool:
        """探测服务端是否为流式模式（``-sm normal``）。

        判据：用一段**多句**文本请求，看是否返回 >1 个 chunk。
        流式模式下 GPT-SoVITS 每句一个 chunk；close 模式下整段一个。

        ``params`` 必须带**真实参考音频**（``refer_wav_path`` /
        ``ref_audio_path`` + ``prompt_text``）—— GPT-SoVITS 在没有默认参考
        音频时会直接返回 400「未指定参考音频且接口无预设」，空参数探测会
        恒定得到 False（实测踩过：TTS 明明是流式，探测却说不是）。

        注意：本探测会真实合成一小段语音（约 1~3s），只应在启动自检时调用一次。
        """
        if not self.base_url:
            return False
        body = dict(params or {})
        if not body:
            return False
        body["text"] = "测试。测试。"
        body.setdefault("cut_punc", self.DEFAULT_CUT_PUNC)
        try:
            n = 0
            for _chunk in self.synthesize_stream(body, architecture,
                                                 timeout=timeout):
                n += 1
                if n > 1:
                    return True
            return False
        except Exception:
            return False

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
