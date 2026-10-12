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
