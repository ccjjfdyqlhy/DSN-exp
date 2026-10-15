# apps/dsn_ui/config.py
"""DSN-UI 独立应用配置。"""

from __future__ import annotations

import os
from pathlib import Path


#: 对外 API 的运行模式。
#:
#:   "dsn"         完整 DSN-exp 能力：动态组装系统提示词、话题记忆、情绪
#:                 动力学、人格系统、工具箱。适合本仓库自带的 Web UI。
#:   "passthrough" 完全交给请求方：**不注入任何提示词**，不跑情绪系统，
#:                 不读写记忆/人格。请求里的 messages 原样送进模型，
#:                 适合把 dsn_ui 当作纯 OpenAI 兼容后端给外部客户端用
#:                 （Open WebUI / Continue / LangChain …）。
API_MODE_DSN = "dsn"
API_MODE_PASSTHROUGH = "passthrough"
API_MODES = (API_MODE_DSN, API_MODE_PASSTHROUGH)


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


class UIConfig:
    HOST: str = os.getenv("DSN_UI_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("DSN_UI_PORT", "8888"))
    DEFAULT_SLOTS: int = int(os.getenv("DSN_UI_DEFAULT_SLOTS", "2"))
    PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent

    #: 默认 API 模式（DSN_UI_API_MODE=dsn|passthrough）
    API_MODE: str = (os.getenv("DSN_UI_API_MODE", API_MODE_DSN).strip().lower()
                     or API_MODE_DSN)
    #: 置 true 时忽略请求方的 per-request 覆盖，强制使用上面的 API_MODE。
    #: 部署方用它来保证"这个实例就是纯透传/就是完整 DSN"，不给客户端选择权。
    API_MODE_LOCKED: bool = _env_bool("DSN_UI_API_MODE_LOCKED", "false")

    # ── dsn_ui 自有数据目录（凭据密文 / provider / TTS payload 等都放这里）──
    DATA_DIR: Path = PROJECT_ROOT / "apps" / "dsn_ui" / "data"

    # ── 本地模型接入（onboarding）──
    #: 本地模型 profile 目录。engine._init_default_profiles() 在启动时读取这里的
    #: *.yaml 并注册到 orchestrator，因此「配置新实例」写入这里即可跨重启存活。
    MODEL_PROFILES_DIR: Path = PROJECT_ROOT / "apps" / "dsn" / "model_profiles"
    #: GGUF 扫描根目录（os.pathsep 分隔，支持 ~）。默认只扫 LM Studio 的模型库，
    #: 绝不遍历整个文件系统。DSN_UI_MODEL_ROOTS=/a:/b 可覆盖。
    MODEL_SCAN_ROOTS: tuple = tuple(
        p.strip()
        for p in (os.getenv("DSN_UI_MODEL_ROOTS") or "").split(os.pathsep)
        if p.strip()
    ) or ("~/.lmstudio/models",)
    #: 目录递归深度与结果数上限，避免在大盘上把扫描拖死。
    MODEL_SCAN_MAX_DEPTH: int = _env_int("DSN_UI_MODEL_SCAN_MAX_DEPTH", 6)
    MODEL_SCAN_MAX_RESULTS: int = _env_int("DSN_UI_MODEL_SCAN_MAX_RESULTS", 200)
    #: llama.cpp 可执行文件默认路径（表单默认值）。
    LLAMA_SERVER_BINARY: str = os.getenv(
        "DSN_UI_LLAMA_SERVER", "~/llama.cpp/build/bin/llama-server"
    )

    # ── TTS 默认请求 payload 与「测试请求」──
    #: 每实例的默认 TTS 请求体持久化文件（不写 apps/dsn/TTS_profiles/default.yaml）
    TTS_PAYLOAD_FILE: Path = DATA_DIR / "tts_payload.json"
    #: TTS 合成请求超时（秒）。合成首句可能较慢，给足。
    TTS_REQUEST_TIMEOUT: float = _env_float("DSN_UI_TTS_TIMEOUT", 60.0)
    #: 测试响应里回传的音频 base64 上限（字节）；真实字节数始终以 audio_bytes 报告。
    TTS_TEST_MAX_B64_BYTES: int = _env_int("DSN_UI_TTS_MAX_B64_BYTES", 65536)

    @classmethod
    def resolve_api_mode(cls, requested: "str | None" = None) -> str:
        """决定本次请求实际使用的模式。

        优先级：锁定时的配置值 > 请求方显式指定 > 配置默认值。
        非法值一律回退到配置默认值（不抛错，避免把 API 打挂）。
        """
        if cls.API_MODE_LOCKED:
            return cls.API_MODE if cls.API_MODE in API_MODES else API_MODE_DSN

        if requested:
            mode = str(requested).strip().lower()
            if mode in API_MODES:
                return mode

        return cls.API_MODE if cls.API_MODE in API_MODES else API_MODE_DSN
