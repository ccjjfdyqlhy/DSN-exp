# plugins/builtin/tts_plugin.py
# TTS 语音合成插件 — POST_TTS
# UPD v1_260611 — 对接 TTSProfileManager

from __future__ import annotations

import os
import re
import logging
from typing import Optional

from apps.dsn.plugins.base import Plugin, HookPoint, PluginContext
from apps.dsn.plugins.builtin.tts_profile import TTSProfileManager

logger = logging.getLogger("TTSPlugin")


class TTSPlugin(Plugin):
    """
    从 AI 回复中提取纯文本，调用 TTS 服务合成语音。

    音色参数通过 TTSProfileManager 从 YAML 配置文件加载，
    确保 prompt_text 与参考音频完全对齐。

    依赖: tts_client (VocalExp 实例，可选)
    """

    name = "tts"
    description = "TTS 语音合成 — 将 AI 回复转为语音"
    hooks = [HookPoint.POST_TTS]
    priority = 60

    def __init__(
        self,
        tts_client=None,
        *,
        profile_manager: Optional[TTSProfileManager] = None,
        profile_name: Optional[str] = None,
        tts_process_model=None,
        # ---- 旧版 fallback 参数 (当 profile_manager 为 None 时使用) ----
        ref_audio_path: str | None = None,
        prompt_text: str = "Many people may feel lost at times.",
        prompt_lang: str = "en",
    ):
        self._tts = tts_client
        self._profile_manager = profile_manager
        self._profile_name = profile_name
        self._tts_process_model = tts_process_model

        self._fallback_ref_audio = ref_audio_path or os.path.join(
            os.path.dirname(__file__), "..", "..", "tests", "ref.wav"
        )
        self._fallback_prompt_text = prompt_text
        self._fallback_prompt_lang = prompt_lang

    def on_load(self) -> None:
        if self._tts is None:
            logger.warning("TTS 客户端未注入，TTSPlugin 将跳过所有合成")

        if self._profile_manager is None:
            logger.info("TTSProfileManager 未注入，将使用旧版 fallback 参数")
        else:
            logger.info("TTS 使用 profile: %s", self._profile_name or self._profile_manager.default_name)

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if not ctx.tts_enabled:
            logger.debug("ctx.tts_enabled=False，跳过 TTS")
            return ctx

        if not ctx.extra.get("tts_available", True):
            logger.debug("tts_available=False，跳过 TTS")
            return ctx

        if self._tts is None:
            logger.debug("TTS 客户端未配置，跳过")
            return ctx

        tts_text = self._extract_tts_text(ctx.original_reply)
        if not tts_text:
            logger.info("无可用的 TTS 文本，跳过合成")
            return ctx

        if self._tts_process_model is not None:
            tts_text = self._tts_process_model.process_tts_text(tts_text)

        logger.info("进行 TTS 合成，文本: %s...", tts_text[:100])

        try:
            from apps.dsn.audio.infer import TTSRequestError

            params = self._build_params(tts_text)
            ctx.audio = self._tts.tts(**params)
            logger.info("TTS 合成成功")
        except TTSRequestError as e:
            ctx.tts_error = f"TTS 服务请求失败: {e}"
            ctx.extra["tts_available"] = False
            logger.error(ctx.tts_error)
        except Exception as e:
            ctx.tts_error = f"TTS 未知错误: {e}"
            ctx.extra["tts_available"] = False
            logger.exception("TTS 异常")

        return ctx

    # ---- 参数构建 ----

    def _build_params(self, text: str) -> dict:
        if self._profile_manager is not None:
            return self._profile_manager.build_params(text, self._profile_name)

        return {
            "text": text,
            "text_lang": "zh",
            "ref_audio_path": self._fallback_ref_audio,
            "prompt_lang": self._fallback_prompt_lang,
            "prompt_text": self._fallback_prompt_text,
            "media_type": "wav",
            "streaming_mode": False,
        }

    # ---- 内部 ----

    _TEXT_TAG_RE = re.compile(r"<text>(.*?)</text>", re.DOTALL | re.IGNORECASE)
    _TASK_TAG_RE = re.compile(r"<task>.*?</task>", re.DOTALL | re.IGNORECASE)
    _CODE_BLOCK_RE = re.compile(r"```\w*\s*\n.*?```", re.DOTALL | re.IGNORECASE)
    _HELP_TAG_RE = re.compile(r"<help>.*?</help>", re.DOTALL | re.IGNORECASE)
    _HTML_TAG_RE = re.compile(r"<[^>]+>")
    _WHITESPACE_RE = re.compile(r"\s+")

    @classmethod
    def _extract_tts_text(cls, reply: str) -> str:
        """移除所有标签和代码块，只保留纯文本用于 TTS 合成"""
        text = cls._TEXT_TAG_RE.sub("", reply)
        text = cls._TASK_TAG_RE.sub("", text)
        text = cls._CODE_BLOCK_RE.sub("", text)
        text = cls._HELP_TAG_RE.sub("", text)
        text = cls._HTML_TAG_RE.sub("", text)
        text = cls._WHITESPACE_RE.sub(" ", text)
        return text.strip()
