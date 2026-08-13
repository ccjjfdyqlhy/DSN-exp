# plugins/builtin/tts_profile.py
# TTS 音色 Profile 管理器 — 通过 YAML 配置文件管理 TTS 参数
# UPD v1_260611

from __future__ import annotations

import os
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

DEFAULT_PROFILES_DIR = Path(__file__).parent.parent.parent / "TTS_profiles"
DEFAULT_CONFIG_FILE = DEFAULT_PROFILES_DIR / "default.yaml"


@dataclass
class TTSProfile:
    """单个 TTS 音色配置，包含推理所需的全部参数"""

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
        """
        根据此 profile 和给定文本构造完整的 TTS 请求参数字典。
        :param text: 待合成的文本
        """
        if self.architecture == "serial":
            return self._build_serial_params(text)
        return self._build_parallel_params(text)

    def _build_parallel_params(self, text: str) -> Dict[str, Any]:
        params: Dict[str, Any] = {
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

    def _build_serial_params(self, text: str) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "text": text,
            "text_language": self.text_lang,
            "refer_wav_path": self.ref_audio_path,
            "prompt_language": self.prompt_lang,
            "prompt_text": self.prompt_text,
            "media_type": self.media_type,
            "streaming_mode": self.streaming_mode,
        }
        params.update(self.extra_params)
        return params

    @classmethod
    def from_dict(cls, name: str, data: dict, base_dir: Path) -> TTSProfile:
        """
        从 YAML dict 和基准目录构建 TTSProfile。
        :param base_dir: 用于解析相对路径的基准目录（YAML 文件所在目录）
        """
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
            extra_params=data.get("extra_params", {}),
            architecture=data.get("architecture", "parallel"),
        )

    def __repr__(self) -> str:
        return (
            f"<TTSProfile name={self.name!r} ref={Path(self.ref_audio_path).name!r} "
            f"lang={self.text_lang}+{self.prompt_lang}>"
        )


class TTSProfileManager:
    """
    TTS 音色配置管理器。

    从 YAML 配置文件加载多个 profile，支持按名称切换，
    并提供 build_params() 快速生成 TTS 请求参数。

    用法::

        mgr = TTSProfileManager()
        params = mgr.build_params("你好世界")         # 使用默认 profile
        params = mgr.build_params("你好", "voice_2")  # 使用指定 profile
        mgr.set_default("voice_2")                     # 切换默认 profile
        mgr.reload()                                   # 重新加载配置文件
    """

    def __init__(self, config_path: Optional[Path] = None):
        self._profiles: Dict[str, TTSProfile] = {}
        self._default_name: str = ""
        self._config_path: Path = config_path or DEFAULT_CONFIG_FILE

        if self._config_path.exists():
            self._load()
        else:
            logger.warning("TTS 配置文件不存在: %s，将使用内置回退", self._config_path)
            self._ensure_fallback()

    # ---- 公共 API ----

    def get_profile(self, name: Optional[str] = None) -> Optional[TTSProfile]:
        """获取指定 profile，name 为 None 则返回当前默认。"""
        name = name or self._default_name
        return self._profiles.get(name)

    def build_params(self, text: str, profile_name: Optional[str] = None) -> Dict[str, Any]:
        """快捷方法：获取指定 profile 并根据文本构建 TTS 参数。"""
        profile = self.get_profile(profile_name)
        if not profile:
            raise ValueError(
                f"未找到 TTS profile: {profile_name or self._default_name!r}，"
                f"可用: {list(self._profiles.keys())}"
            )
        return profile.build_params(text)

    def set_default(self, name: str) -> bool:
        """切换默认 profile，若不存在返回 False。"""
        if name not in self._profiles:
            logger.error("切换失败: profile %r 不存在，可用: %s", name, list(self._profiles.keys()))
            return False
        self._default_name = name
        logger.info("默认 TTS profile 已切换为: %s", name)
        return True

    def reload(self) -> None:
        """重新加载配置文件。"""
        if self._config_path.exists():
            self._load()
        else:
            logger.warning("配置文件不存在，reload 跳过: %s", self._config_path)

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
        return list(self._profiles.keys())

    # ---- 内部 ----

    def _load(self) -> None:
        base_dir = self._config_path.parent.resolve()
        logger.info("加载 TTS 配置文件: %s", self._config_path)

        with open(self._config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        if not isinstance(config, dict):
            raise ValueError(f"TTS 配置文件格式错误: {self._config_path}")

        self._default_name = config.get("default_profile", "")
        profiles_raw = config.get("profiles", {})

        self._profiles.clear()
        for name, data in profiles_raw.items():
            try:
                self._profiles[name] = TTSProfile.from_dict(name, data, base_dir)
                logger.debug("已加载 profile: %s", name)
            except Exception as e:
                logger.warning("加载 profile %r 失败: %s", name, e)

        if not self._default_name and self._profiles:
            self._default_name = next(iter(self._profiles))
            logger.debug("未指定 default_profile，使用第一个: %s", self._default_name)

        if self._default_name not in self._profiles:
            logger.warning("默认 profile %r 不存在，可用: %s", self._default_name, self.list_profiles())

        logger.info("TTS Profile 加载完成: %d 个 profile, 默认=%s", len(self._profiles), self._default_name)

    def _ensure_fallback(self) -> None:
        """当配置文件不存在时，创建一个内置回退 profile。"""
        root = Path(__file__).parent.parent.parent  # DSN-exp 根目录
        ref_path = str(root / "tests" / "ref.wav")

        fallback = TTSProfile(
            name="fallback",
            description="内置回退 profile — 配置文件丢失时的备用",
            ref_audio_path=ref_path,
            prompt_text="Many people may feel lost at times. After all, it's impossible for "
                        "everything to happen according to your own wishes.",
            prompt_lang="en",
            text_lang="zh",
        )
        self._profiles["fallback"] = fallback
        self._default_name = "fallback"
        logger.warning("已启用内置回退 profile: %s", fallback)
