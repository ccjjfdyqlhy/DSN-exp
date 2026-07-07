"""
ASR Step — 接收音频 → ASR 识别 → 输出文本

封装了从原始音频字节到识别文本的完整流程：
  1. base64 解码（可选）
  2. ffmpeg 转 WAV（16kHz, mono, PCM16）
  3. FunASR 模型推理（VAD + Paraformer + 标点恢复）
  4. 文本后处理（去首尾空格）
  5. ASR 内容过滤（可选，LMFilterModel FORWARD/HOLD）

用法:
    asr = ASRStep(device="cuda")
    text = asr.recognize(audio_bytes)
    # 或从 base64 输入
    text = asr.recognize_b64("base64...encoded...audio...")
"""

from __future__ import annotations

import base64
import logging
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("steps.ASR")


class ASRStep:
    """
    ASR 步骤: 音频字节 → 识别文本。

    FunASR 模型在首次调用 recognize() 时惰性加载。
    """

    MODEL_NAME = "paraformer-zh"
    MODEL_REVISION = "v2.0.4"
    VAD_MODEL = "fsmn-vad"
    VAD_REVISION = "v2.0.4"
    PUNC_MODEL = "ct-punc-c"
    PUNC_REVISION = "v2.0.4"

    def __init__(
        self,
        device: str = "cuda",
        model_dir: Optional[str] = None,
        debug_audio_dir: Optional[str] = None,
        filter_model: object = None,
    ):
        """
        :param device: 推理设备，如 "cuda" 或 "cpu"
        :param model_dir: FunASR 模型缓存目录，默认自动
        :param debug_audio_dir: 调试音频保存目录，None 表示不保存
        :param filter_model: LMFilterModel 实例（可选），用于 FORWARD/HOLD 过滤
        """
        self._device = device
        self._model_dir = model_dir
        self._debug_audio_dir = debug_audio_dir
        self._filter = filter_model
        self._model = None

    # ── 公共方法 ──

    def recognize(self, audio_bytes: bytes, use_filter: bool = False) -> str:
        """
        对原始音频字节执行 ASR 识别，返回文本。

        :param audio_bytes: 任意格式的音频字节
        :param use_filter: 是否启用 LMFilterModel 内容过滤
        :returns: 识别文本（空串表示无语音）
        """
        self._lazy_load_model()

        if self._debug_audio_dir:
            self._save_debug(audio_bytes)

        wav_bytes = self.convert_to_wav(audio_bytes)
        text = self._infer(wav_bytes)

        if use_filter and self._filter is not None and text:
            decision = self._filter.filter_input(text)
            if decision == "HOLD":
                logger.info("ASR 过滤: HOLD — %r", text)
                return ""

        return text

    def recognize_b64(self, audio_b64: str, use_filter: bool = False) -> str:
        """
        对 base64 编码的音频执行 ASR 识别。

        :param audio_b64: base64 编码的音频字符串
        :param use_filter: 是否启用 LMFilterModel 内容过滤
        :returns: 识别文本
        """
        audio_bytes = base64.b64decode(audio_b64)
        return self.recognize(audio_bytes, use_filter=use_filter)

    # ── 音频转换 ──

    @staticmethod
    def convert_to_wav(audio_bytes: bytes) -> bytes:
        """
        用 ffmpeg 将任意格式音频转为 16kHz mono PCM16 WAV。

        转换参数:
          -ar 16000   采样率 16kHz
          -ac 1       单声道
          -acodec pcm_s16le  16 位有符号小端 PCM

        ffmpeg 不可用时原样返回。
        """
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            logger.warning("ffmpeg 未安装，跳过音频格式转换")
            return audio_bytes
        try:
            proc = subprocess.run(
                [ffmpeg, "-y", "-i", "pipe:0", "-f", "wav", "-acodec", "pcm_s16le",
                 "-ar", "16000", "-ac", "1", "pipe:1"],
                input=audio_bytes, capture_output=True, timeout=15,
            )
            if proc.returncode == 0 and proc.stdout:
                return proc.stdout
            logger.warning("ffmpeg 转换返回非零 (%d)，使用原始音频", proc.returncode)
            return audio_bytes
        except subprocess.TimeoutExpired:
            logger.warning("ffmpeg 转换超时，使用原始音频")
            return audio_bytes
        except Exception as e:
            logger.warning("ffmpeg 转换异常: %s，使用原始音频", e)
            return audio_bytes

    # ── 内部方法 ──

    def _lazy_load_model(self):
        if self._model is not None:
            return
        logger.info("加载 FunASR 模型 (device=%s)...", self._device)
        from funasr import AutoModel

        kwargs = dict(
            model=self.MODEL_NAME,
            model_revision=self.MODEL_REVISION,
            vad_model=self.VAD_MODEL,
            vad_model_revision=self.VAD_REVISION,
            punc_model=self.PUNC_MODEL,
            punc_model_revision=self.PUNC_REVISION,
            device=self._device,
            disable_update=True,
            disable_pbar=True,
        )
        if self._model_dir:
            kwargs["model_dir"] = self._model_dir

        self._model = AutoModel(**kwargs)
        logger.info("FunASR 模型加载完成")

    def _infer(self, wav_bytes: bytes) -> str:
        if not wav_bytes:
            return ""
        try:
            res = self._model.generate(
                input=wav_bytes,
                use_itn=True,
                batch_size_s=60,
                language="zh",
            )
            text = res[0].get("text", "").strip() if res else ""
            if text:
                logger.info("ASR 识别结果: %s", text)
            return text
        except Exception as e:
            logger.error("ASR 推理失败: %s", e)
            return ""

    def _save_debug(self, audio_bytes: bytes):
        if not self._debug_audio_dir:
            return
        path = Path(self._debug_audio_dir)
        path.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        dst = path / f"{ts}.webm"
        try:
            dst.write_bytes(audio_bytes)
            logger.debug("调试音频已保存 → %s (%d bytes)", dst, len(audio_bytes))
        except Exception as e:
            logger.warning("调试音频保存失败: %s", e)


# ── 快捷函数 ──

_default_asr: ASRStep | None = None


def get_default(device: str = "cuda") -> ASRStep:
    """获取/创建全局默认 ASRStep 实例（惰性加载）。"""
    global _default_asr
    if _default_asr is None:
        _default_asr = ASRStep(device=device)
    return _default_asr


def recognize(audio_bytes: bytes, device: str = "cuda") -> str:
    """便捷函数: 音频字节 → 文本。"""
    return get_default(device).recognize(audio_bytes)


def recognize_b64(audio_b64: str, device: str = "cuda") -> str:
    """便捷函数: base64 音频 → 文本。"""
    return get_default(device).recognize_b64(audio_b64)
