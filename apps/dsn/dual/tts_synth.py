# dual/tts_synth.py
# 轻量 TTS 合成器 — 复用 boot 的 TTS 管线，供 Instant 模型回复和进度播报使用

from __future__ import annotations

import base64
import logging
from typing import Optional

from apps.dsn.utils.text_clean import clean_tts_text

logger = logging.getLogger("TTSSynthesizer")


class TTSSynthesizer:
    """同步 TTS 合成器。每行文本 → base64 音频。"""

    def __init__(
        self,
        tts_client=None,
        tts_profile_mgr=None,
        tts_process_model=None,
    ):
        self._tts_client = tts_client
        self._tts_profile_mgr = tts_profile_mgr
        self._tts_process_model = tts_process_model

    @property
    def available(self) -> bool:
        return self._tts_client is not None

    def synthesize(self, text: str) -> list[dict]:
        """
        对文本按行合成 TTS，返回 [{index, total, text, audio_b64}]。
        失败的行 audio_b64 为 None。
        """
        if not text or not self._tts_client:
            return []

        cleaned = clean_tts_text(text)
        if not cleaned:
            return []

        lines = []
        for line in cleaned.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            if not any(c.isalpha() or "\u4e00" <= c <= "\u9fff" for c in stripped):
                continue
            lines.append(stripped)

        if not lines:
            return []

        results = []
        total = len(lines)
        for i, line in enumerate(lines):
            try:
                processed_line = line
                if self._tts_process_model is not None:
                    try:
                        from apps.dsn.config import Config
                        fast_first = bool(Config.TTS_FAST_FIRST_LINE)
                    except Exception:
                        fast_first = True
                    if fast_first:
                        local = getattr(self._tts_process_model, "_local_preprocess", None)
                        processed_line = local(line) if callable(local) else line
                    else:
                        processed_line = self._tts_process_model.process_tts_text(line)

                params = (
                    self._tts_profile_mgr.build_params(processed_line)
                    if self._tts_profile_mgr
                    else {
                        "text": processed_line, "text_lang": "zh",
                        "ref_audio_path": "", "prompt_lang": "en",
                        "prompt_text": "", "media_type": "wav",
                        "streaming_mode": False,
                    }
                )
                audio_bytes = self._tts_client.tts(**params)
                audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
                results.append({
                    "index": i, "total": total,
                    "text": line, "audio_b64": audio_b64,
                })
            except Exception as e:
                logger.warning("TTS 行 %d/%d 失败: %s", i + 1, total, e)
                results.append({
                    "index": i, "total": total,
                    "text": line, "audio_b64": None,
                })
        return results

    def synthesize_first_line_b64(self, text: str) -> Optional[str]:
        """快速合成第一行的 base64 音频。失败返回 None。"""
        results = self.synthesize(text)
        if results and results[0].get("audio_b64"):
            return results[0]["audio_b64"]
        return None
