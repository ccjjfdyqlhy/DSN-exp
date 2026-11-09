# apps/dsn_study/asr.py
# 语音识别门面 —— 把「infra 资源池调度」与「FunASR sidecar 识别」缝合成可调用接口。
#
# 职责边界（与 voice.py 同构）：
#   * 资源调度：完全交给 infra.resources.ResourcePool（取租约 → 服务就绪 → 用完归还）。
#   * 识别请求：本地发 HTTP 到 ASR sidecar（模型跑在 conda 环境里）。
#   * 失败策略：**永不抛错给上层**。语音输入是增强项，失败只降级为"没听清"。
#
# 与参考实现 apps/dsn 的差异：
#   * dsn 在**进程内**直接持有 FunASR AutoModel；宿主 python 没装 torch/funasr，
#     这里改成 HTTP 调 sidecar（见 asr_server.py）。
#   * dsn 的音频归一化在 boot.py（_convert_audio_to_wav）；这里收进本模块，
#     便于单测。

from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Optional

from apps.dsn_study.models.asr_client import ASRClient, ASRRequestError
from apps.dsn_study.models.resource_setup import (
    ASR_RESOURCE,
    get_study_pool,
    setup_study_resources,
)

logger = logging.getLogger("ASRService")


class ASRService:
    """语音识别门面。"""

    def __init__(self, pool=None, client=None):
        self._pool = pool
        self._client = client
        self._last_error = ""
        self._disabled_reason = ""

    # ── 装配 ──

    @classmethod
    def create(cls) -> "ASRService":
        """按 Config 装配语音识别门面（失败时返回不可用实例，不抛错）。"""
        from apps.dsn_study.config import Config

        if not getattr(Config, "ASR_ENABLED", False):
            svc = cls()
            svc._disabled_reason = "ASR_ENABLED=false"
            logger.info("ASR 已禁用（ASR_ENABLED=false）")
            return svc

        try:
            pool = setup_study_resources()
        except Exception as e:
            svc = cls()
            svc._disabled_reason = "资源池初始化失败: %s" % e
            logger.warning("ASR 资源池初始化失败（语音输入不可用）: %s", e)
            return svc

        base_url = getattr(Config, "ASR_BASE_URL", "http://127.0.0.1:9881")
        client = ASRClient(base_url,
                           timeout=getattr(Config, "ASR_REQUEST_TIMEOUT", 180))

        svc = cls(pool=pool, client=client)
        logger.info("语音识别服务就绪: base_url=%s", base_url)
        return svc

    # ── 状态 ──

    @property
    def available(self) -> bool:
        """是否具备识别能力（配置开启 + 客户端就绪）。"""
        if self._disabled_reason:
            return False
        if self._client is None or self._pool is None:
            return False
        return True

    @property
    def disabled_reason(self) -> str:
        return self._disabled_reason

    @property
    def client(self):
        """ASR HTTP 客户端（无则 None）。"""
        return self._client

    @property
    def pool(self):
        """infra 资源池（无则 None）。"""
        return self._pool

    @property
    def last_error(self) -> str:
        return self._last_error

    def status(self) -> dict:
        """语音识别子系统状态（供 REST 查询）。"""
        info: dict = {
            "enabled": self.available,
            "reason": self._disabled_reason,
            "last_error": self._last_error,
            "resource": None,
        }
        pool = self._pool or get_study_pool()
        if pool is not None:
            try:
                res = [r for r in pool.list_resources() if r.get("name") == ASR_RESOURCE]
                info["resource"] = res[0] if res else None
                info["pool"] = pool.status()
            except Exception:
                pass
        if self._client is not None:
            try:
                info["health"] = self._client.health()
            except Exception:
                info["health"] = {}
        return info

    def warmup(self) -> bool:
        """预热：确保 sidecar 已拉起**并**把模型加载起来（供启动时异步调用）。"""
        pool = self._pool or get_study_pool()
        if pool is None:
            return False
        try:
            ok = pool.ensure_running(ASR_RESOURCE)
            if not ok:
                self._last_error = "ASR sidecar 未就绪"
                logger.warning("ASR 预热: sidecar 未就绪")
                return False
        except Exception as e:
            self._last_error = str(e)
            logger.warning("ASR 预热失败: %s", e)
            return False

        if self._client is None:
            return False
        try:
            from apps.dsn_study.config import Config
            timeout = float(getattr(Config, "ASR_LOAD_TIMEOUT", 600))
            loaded = self._client.warmup(timeout=timeout)
            logger.info("ASR 预热: %s", "模型已加载" if loaded else "模型未加载")
            return bool(loaded)
        except Exception as e:
            self._last_error = str(e)
            logger.warning("ASR 模型预热失败: %s", e)
            return False

    # ── 识别 ──

    def transcribe_with_error(self, audio_bytes: bytes) -> tuple[str, list, str]:
        """识别音频，返回 (text, segments, error)。

        与 transcribe 的区别：**能区分"识别失败"与"识别成功但文本为空"**。
        失败时 error 非空、text 为空串 —— 路由层据此回 500（契约要求），
        而不是把失败伪装成"没听清"。
        """
        if not self.available:
            return "", [], self._disabled_reason or "ASR 不可用"
        if not audio_bytes:
            return "", [], "音频为空"

        pool = self._pool or get_study_pool()
        try:
            if pool is not None:
                # 取租约 → 池负责保证服务已就绪（必要时拉起）
                with pool.lease(ASR_RESOURCE):
                    text, segments = self._client.transcribe(audio_bytes)
            else:
                text, segments = self._client.transcribe(audio_bytes)
            return text, segments, ""
        except ASRRequestError as e:
            self._last_error = str(e)
            logger.warning("ASR 识别失败: %s", e)
            return "", [], str(e)
        except Exception as e:
            self._last_error = str(e)
            logger.warning("ASR 识别异常: %s", e, exc_info=True)
            return "", [], str(e)

    def transcribe(self, audio_bytes: bytes) -> tuple[str, list]:
        """识别音频，返回 (text, segments)。不可用或失败时返回 ("", [])。

        **永不抛异常** —— 对话链路用它，失败只降级为"没听清"。
        需要区分失败/空结果时用 transcribe_with_error。
        """
        text, segments, _error = self.transcribe_with_error(audio_bytes)
        return text, segments

    def transcribe_b64(self, audio_b64: str) -> tuple[str, str]:
        """识别 base64 音频，返回 (text, error)。error 为空串表示成功。"""
        import base64

        if not audio_b64:
            return "", "缺少音频"
        try:
            audio_bytes = base64.b64decode(audio_b64)
        except Exception as e:
            return "", "Invalid base64: %s" % e
        text, _segments = self.transcribe(audio_bytes)
        if not text:
            return "", self._last_error or (self._disabled_reason or "ASR 不可用")
        return text, ""

    # ── 音频归一化 ──

    @staticmethod
    def normalize_audio(audio_bytes: bytes) -> bytes:
        """归一化为 16 kHz / 单声道 / 16bit PCM WAV。

        逻辑与参考实现 apps/dsn/boot.py:132-148（_convert_audio_to_wav）一致：
        用 ffmpeg 转码；**ffmpeg 不存在时原样返回**（交给 FunASR 自己兜底）。
        """
        if not audio_bytes:
            return audio_bytes
        from apps.dsn_study.config import Config

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return audio_bytes
        try:
            proc = subprocess.run(
                [ffmpeg, "-y", "-i", "pipe:0", "-f", "wav", "-acodec", "pcm_s16le",
                 "-ar", "16000", "-ac", "1", "pipe:1"],
                input=audio_bytes, capture_output=True,
                timeout=int(getattr(Config, "ASR_CONVERT_TIMEOUT", 15)),
            )
            if proc.returncode == 0 and proc.stdout:
                return proc.stdout
            return audio_bytes
        except Exception as e:
            logger.warning("音频归一化失败（按原样送识别）: %s", e)
            return audio_bytes

    def __repr__(self) -> str:
        return "<ASRService available=%s>" % self.available
