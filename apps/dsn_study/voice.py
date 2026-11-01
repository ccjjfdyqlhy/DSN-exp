# apps/dsn_study/voice.py
# 语音门面 —— 把「infra 资源池调度」与「GPT-SoVITS 合成」缝合成一个可调用接口。
#
# 职责边界：
#   * 资源调度：完全交给 infra.resources.ResourcePool（取租约 → 服务就绪 → 用完归还）。
#   * 合成请求：本地发 HTTP 到 GPT-SoVITS，参数由 profile 决定。
#   * 失败策略：**永不抛错给上层**。语音是增强项，失败只降级为纯文本。
#
# 不提供 AI 主动合成入口（无 speak 工具）——语音只跟随对话回复自动生成。

from __future__ import annotations

import base64
import logging
import re
from typing import Optional

from apps.dsn_study.models.resource_setup import (
    TTS_RESOURCE,
    get_study_pool,
    setup_study_resources,
)
from apps.dsn_study.models.tts_client import TTSClient, TTSRequestError
from apps.dsn_study.models.tts_profile import TTSProfileManager

logger = logging.getLogger("VoiceService")

#: 需要从朗读文本中剔除的内容（与参考实现 tts_plugin 的清洗一致）
_CODE_BLOCK_RE = re.compile(r"```\w*\s*\n.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`]*)`")
_TAG_RE = re.compile(r"<[^>]+>")
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_WHITESPACE_RE = re.compile(r"\s+")
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]+")


class VoiceService:
    """语音合成门面。"""

    def __init__(self, pool=None, client=None, profiles=None):
        self._pool = pool
        self._client = client
        self._profiles = profiles
        self._last_error = ""
        self._disabled_reason = ""

    # ── 装配 ──

    @classmethod
    def create(cls) -> "VoiceService":
        """按 Config 装配语音门面（失败时返回不可用实例，不抛错）。"""
        from apps.dsn_study.config import Config

        if not getattr(Config, "TTS_ENABLED", False):
            svc = cls()
            svc._disabled_reason = "TTS_ENABLED=false"
            logger.info("TTS 已禁用（TTS_ENABLED=false）")
            return svc

        try:
            pool = setup_study_resources()
        except Exception as e:
            svc = cls()
            svc._disabled_reason = "资源池初始化失败: %s" % e
            logger.warning("TTS 资源池初始化失败（语音合成不可用）: %s", e)
            return svc

        base_url = getattr(Config, "TTS_BASE_URL", "http://127.0.0.1:9880")
        client = TTSClient(base_url, timeout=getattr(Config, "TTS_REQUEST_TIMEOUT", 180))

        profile_dir = getattr(Config, "TTS_PROFILE_DIR", "") or ""
        profiles = TTSProfileManager()
        if profile_dir:
            try:
                import pathlib
                profiles = TTSProfileManager(
                    pathlib.Path(profile_dir) / "default.yaml")
            except Exception as e:
                logger.warning("TTS profile 目录加载失败，改用内置默认: %s", e)

        profile_name = getattr(Config, "TTS_PROFILE_NAME", "") or ""
        if profile_name:
            profiles.set_default(profile_name)

        svc = cls(pool=pool, client=client, profiles=profiles)
        logger.info("语音服务就绪: base_url=%s profile=%s",
                    base_url, profiles.default_name)
        return svc

    # ── 状态 ──

    @property
    def available(self) -> bool:
        """是否具备合成能力（配置开启 + 客户端就绪 + profile 可用）。"""
        if self._disabled_reason:
            return False
        if self._client is None or self._pool is None:
            return False
        if self._profiles is None or not self._profiles.list_profiles():
            return False
        return True

    @property
    def disabled_reason(self) -> str:
        return self._disabled_reason

    @property
    def profiles(self):
        """音色 profile 管理器（无则 None）。"""
        return self._profiles

    @property
    def client(self):
        """GPT-SoVITS HTTP 客户端（无则 None）。"""
        return self._client

    @property
    def pool(self):
        """infra 资源池（无则 None）。"""
        return self._pool

    @property
    def last_error(self) -> str:
        return self._last_error

    def status(self) -> dict:
        """语音子系统状态（供 REST 查询）。"""
        info: dict = {
            "enabled": self.available,
            "reason": self._disabled_reason,
            "last_error": self._last_error,
            "profiles": [],
            "default_profile": "",
            "resource": None,
        }
        if self._profiles is not None:
            info["profiles"] = self._profiles.list_profiles()
            info["default_profile"] = self._profiles.default_name
        pool = self._pool or get_study_pool()
        if pool is not None:
            try:
                res = [r for r in pool.list_resources() if r.get("name") == TTS_RESOURCE]
                info["resource"] = res[0] if res else None
                info["pool"] = pool.status()
            except Exception:
                pass
        return info

    def warmup(self) -> bool:
        """后台预热：确保 TTS 服务已拉起（供启动时异步调用）。"""
        pool = self._pool or get_study_pool()
        if pool is None:
            return False
        try:
            ok = pool.ensure_running(TTS_RESOURCE)
            logger.info("TTS 预热: %s", "已就绪" if ok else "未就绪")
            return bool(ok)
        except Exception as e:
            self._last_error = str(e)
            logger.warning("TTS 预热失败: %s", e)
            return False

    # ── 合成 ──

    def synthesize(self, text: str) -> Optional[bytes]:
        """合成语音，返回音频字节；不可用或失败时返回 None。"""
        if not self.available:
            return None
        cleaned = self._clean_text(text)
        if not cleaned:
            return None

        profile = self._profiles.get_profile()
        if profile is None:
            self._last_error = "无可用 TTS profile"
            return None
        params = profile.build_params(cleaned)

        pool = self._pool or get_study_pool()
        try:
            if pool is not None:
                # 取租约 → 池负责保证服务已就绪（必要时拉起）
                with pool.lease(TTS_RESOURCE):
                    return self._client.synthesize(params, profile.architecture)
            return self._client.synthesize(params, profile.architecture)
        except TTSRequestError as e:
            self._last_error = str(e)
            logger.warning("TTS 合成失败: %s", e)
            return None
        except Exception as e:
            self._last_error = str(e)
            logger.warning("TTS 合成异常: %s", e, exc_info=True)
            return None

    def synthesize_b64(self, text: str) -> tuple[Optional[str], str]:
        """合成并返回 (audio_b64, error)。error 为空串表示成功。"""
        audio = self.synthesize(text)
        if audio is None:
            return None, self._last_error or (self._disabled_reason or "TTS 不可用")
        return base64.b64encode(audio).decode("ascii"), ""

    # ── 文本清洗 ──

    @staticmethod
    def _clean_text(text: str) -> str:
        """去掉代码块、标签、markdown 记号与 emoji，只留适合朗读的自然语言。"""
        if not text:
            return ""
        out = _CODE_BLOCK_RE.sub(" ", text)
        out = _INLINE_CODE_RE.sub(r"\1", out)
        out = _TAG_RE.sub(" ", out)
        out = _MD_BOLD_RE.sub(r"\1", out)
        out = _EMOJI_RE.sub(" ", out)
        out = out.replace("#", "").replace("*", "").replace("`", "")
        out = _WHITESPACE_RE.sub(" ", out).strip()
        # 超长文本截断：GPT-SoVITS 对超长输入慢且容易漂移
        return out[:1200]
