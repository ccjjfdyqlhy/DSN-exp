# apps/dsn_study/models/tts_profile.py
# TTS 音色 Profile 管理器 —— 从 YAML 读取音色参数（移植自 apps/dsn 的 tts_profile.py）。
#
# profile 同时承载两件事：
#   1) 参考音频 + prompt 文本（必须与训练音色对齐，否则音色漂移）
#   2) 推理架构（parallel / serial）—— 决定请求体的字段名与端点
#
# 架构与字段对照（GPT-SoVITS）：
#   parallel → POST {base}/tts，text/text_lang/ref_audio_path/prompt_lang
#   serial   → POST {base}/    ，text/text_language/refer_wav_path/prompt_language

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger("TTSProfile")

DEFAULT_PROFILES_DIR = Path(__file__).resolve().parent.parent / "TTS_profiles"
DEFAULT_CONFIG_FILE = DEFAULT_PROFILES_DIR / "default.yaml"


@dataclass
class TTSProfile:
    """单个 TTS 音色配置。"""

    name: str
    ref_audio_path: str
    prompt_text: str
    prompt_lang: str = "en"
    text_lang: str = "zh"
    media_type: str = "wav"
    streaming_mode: bool = False
    description: str = ""
    extra_params: Dict[str, Any] = field(default_factory=dict)
    architecture: str = "parallel"

    def build_params(self, text: str) -> Dict[str, Any]:
        """按架构构造完整的 TTS 请求参数。"""
        if self.architecture == "serial":
            params: Dict[str, Any] = {
                "text": text,
                "text_language": self.text_lang,
                "refer_wav_path": self.ref_audio_path,
                "prompt_language": self.prompt_lang,
                "prompt_text": self.prompt_text,
                "media_type": self.media_type,
                "streaming_mode": self.streaming_mode,
            }
        else:
            params = {
                "text": text,
                "text_lang": self.text_lang,
                "ref_audio_path": self.ref_audio_path,
                "prompt_lang": self.prompt_lang,
                "prompt_text": self.prompt_text,
                "media_type": self.media_type,
                "streaming_mode": self.streaming_mode,
            }
        params.update(self.extra_params)
        return params

    @classmethod
    def from_dict(cls, name: str, data: dict, base_dir: Path) -> "TTSProfile":
        """从 YAML dict 构建；相对路径按 YAML 所在目录解析。"""
        ref_audio = data.get("ref_audio_path", "")
        if ref_audio and not os.path.isabs(ref_audio):
            ref_audio = str((base_dir / ref_audio).resolve())
        return cls(
            name=name,
            ref_audio_path=ref_audio,
            prompt_text=data.get("prompt_text", ""),
            prompt_lang=data.get("prompt_lang", "en"),
            text_lang=data.get("text_lang", "zh"),
            media_type=data.get("media_type", "wav"),
            streaming_mode=data.get("streaming_mode", False),
            description=data.get("description", ""),
            extra_params=data.get("extra_params", {}) or {},
            architecture=data.get("architecture", "parallel"),
        )

    def __repr__(self) -> str:
        return ("<TTSProfile name=%r ref=%r lang=%s+%s arch=%s>" % (
            self.name, Path(self.ref_audio_path).name, self.text_lang,
            self.prompt_lang, self.architecture))


class TTSProfileManager:
    """TTS 音色配置管理器（多 profile + 默认 profile 切换）。"""

    def __init__(self, config_path: Optional[Path] = None):
        self._config_path = Path(config_path) if config_path else DEFAULT_CONFIG_FILE
        self._profiles: Dict[str, TTSProfile] = {}
        self._default_name = ""
        self._load()

    @property
    def default_name(self) -> str:
        return self._default_name

    @property
    def profiles(self) -> Dict[str, TTSProfile]:
        return dict(self._profiles)

    @property
    def config_path(self) -> Path:
        return self._config_path

    def list_profiles(self) -> List[str]:
        return sorted(self._profiles)

    def get_profile(self, name: Optional[str] = None) -> Optional[TTSProfile]:
        return self._profiles.get(name or self._default_name)

    def build_params(self, text: str, profile_name: Optional[str] = None) -> Dict[str, Any]:
        """按 profile 构造请求参数；profile 缺失时返回空 dict。"""
        profile = self.get_profile(profile_name)
        if profile is None:
            return {}
        return profile.build_params(text)

    def set_default(self, name: str) -> bool:
        if name not in self._profiles:
            return False
        self._default_name = name
        return True

    def reload(self) -> None:
        self._load()

    def _load(self) -> None:
        self._profiles = {}
        self._default_name = ""
        path = self._config_path
        if not path.is_file():
            logger.warning("TTS profile 配置不存在: %s（语音合成将不可用）", path)
            return
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as e:
            logger.warning("TTS profile 配置解析失败: %s", e)
            return
        base_dir = path.parent
        for name, pdata in (data.get("profiles") or {}).items():
            try:
                self._profiles[name] = TTSProfile.from_dict(name, pdata or {}, base_dir)
            except Exception as e:
                logger.warning("TTS profile %r 载入失败: %s", name, e)
        self._default_name = str(data.get("default_profile") or "")
        if self._default_name not in self._profiles:
            self._default_name = next(iter(self._profiles), "")
        if self._profiles:
            logger.info("TTS profile 载入: %d 个（默认 %s）",
                        len(self._profiles), self._default_name)
