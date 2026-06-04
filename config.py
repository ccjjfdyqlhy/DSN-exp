
# DSN-exp/config.py
# 所有敏感配置均从环境变量或 .env 文件读取，切勿在此文件中硬编码密钥。

import os
from pathlib import Path

# 加载 .env 文件（如果存在）
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    print('[WARN] 没有检测到.env文件或没有安装dotenv库')
    pass


def _env(key: str, default=None, required: bool = False):
    """读取环境变量，若 required=True 且未设置则抛出异常。"""
    val = os.environ.get(key, default)
    if required and not val:
        raise EnvironmentError(
            f"缺少必需的环境变量: {key}\n"
            f"请参考 .env.example 创建 .env 文件，或直接设置环境变量。"
        )
    return val


class Config:
    # ==================== 验证系统 ====================
    LITTLESKIN_CLIENT_ID = _env("LITTLESKIN_CLIENT_ID", "")
    LITTLESKIN_CLIENT_SECRET = _env("LITTLESKIN_CLIENT_SECRET", required=True)

    # JWT 密钥
    JWT_SECRET = _env("JWT_SECRET", required=True)

    # ==================== DeepSeek API ====================
    DEEPSEEK_API_KEY = _env("DEEPSEEK_API_KEY", required=True)
    REASONER_ENABLED = _env("REASONER_ENABLED", "true").lower() == "true"
    REASONER_MODEL = _env("REASONER_MODEL", "deepseek-v4-pro")
    REASONER_TIMEOUT = int(_env("REASONER_TIMEOUT", "1200"))

    # ==================== 本地服务 API ====================
    LMSTUDIO_BASE_URL = _env("LMSTUDIO_BASE_URL", "http://localhost:4501")
    TTS_BASE_URL = _env("TTS_BASE_URL", "http://127.0.0.1:9880")

    # ==================== 主模型配置 ====================
    MAIN_MODEL_TYPE = _env("MAIN_MODEL_TYPE", "deepseek")
    MAIN_MODEL_NAME = _env("MAIN_MODEL_NAME", "deepseek-v4-flash")
    LMSTUDIO_TEMPERATURE = float(_env("LMSTUDIO_TEMPERATURE", "0.7"))
    LMSTUDIO_MAX_TOKENS = int(_env("LMSTUDIO_MAX_TOKENS", "4096"))
    LMSTUDIO_TIMEOUT = int(_env("LMSTUDIO_TIMEOUT", "300"))

    # ==================== 存储配置 ====================
    DATABASE_PATH = _env("DATABASE_PATH", "chats.db")
    LOG_DIR = _env("LOG_DIR", "logs")

    # ==================== 服务配置 ====================
    SERVER_HOST = _env("SERVER_HOST", "0.0.0.0")
    SERVER_PORT = int(_env("SERVER_PORT", "5000"))
    SERVER_BASE_URL = _env("SERVER_BASE_URL", "")  # 对外访问地址，为空则自动检测
    LOCAL_CALLBACK_PORT = int(_env("LOCAL_CALLBACK_PORT", "5001"))

    # ==================== 记忆与摘要 ====================
    MEMORY_ENABLED = _env("MEMORY_ENABLED", "true").lower() == "true"
    MEMORY_SUMMARY_BACKEND = _env("MEMORY_SUMMARY_BACKEND", "deepseek")  # "deepseek" | "lmstudio"
    MEMORY_MODEL = _env("MEMORY_MODEL", "deepseek-v4-flash")
    MEMORY_SUMMARY_LENGTH = int(_env("MEMORY_SUMMARY_LENGTH", "100"))
    MEMORY_CONTEXT_WINDOW_SIZE = int(_env("MEMORY_CONTEXT_WINDOW_SIZE", "80"))
    MEMORY_REPLACE_THRESHOLD_RATIO = float(_env("MEMORY_REPLACE_THRESHOLD_RATIO", "0.7"))
    MEMORY_ASYNC_ENABLED = _env("MEMORY_ASYNC_ENABLED", "true").lower() == "true"

    # ==================== ASR 配置 ====================
    ASR_ENABLED = _env("ASR_ENABLED", "false").lower() == "true"
    ASR_DEVICE = _env("ASR_DEVICE", "cuda")

    # ==================== ASR 过滤 ====================
    ASR_FILTER_ENABLED = _env("ASR_FILTER_ENABLED", "false").lower() == "true"
    FILTER_MODEL = _env("FILTER_MODEL", "llama-3.2-1b-instruct")

    # ==================== 任务管理 ====================
    TASK_MANAGER_ENABLED = _env("TASK_MANAGER_ENABLED", "true").lower() == "true"
    TASK_MAX_WORKERS = int(_env("TASK_MAX_WORKERS", "5"))
    TASK_COMPLEXITY_THRESHOLD = float(_env("TASK_COMPLEXITY_THRESHOLD", "0.4"))
    REMINDER_CHECK_INTERVAL = int(_env("REMINDER_CHECK_INTERVAL", "60"))
    TASK_NOTIFICATION_ENABLED = _env("TASK_NOTIFICATION_ENABLED", "true").lower() == "true"
    ACTION_TIMEOUT = int(_env("ACTION_TIMEOUT", "300"))

    # ==================== Agent 循环 ====================
    AGENT_MAX_STEPS = int(_env("AGENT_MAX_STEPS", "10"))

    # ==================== 叙事世界模型 ====================
    WORLD_ENABLED = _env("WORLD_ENABLED", "true").lower() in ("1", "true", "yes")
    WORLD_PRESET = _env("WORLD_PRESET", "default")
    WORLD_UPDATE_INTERVAL = int(_env("WORLD_UPDATE_INTERVAL", "60"))

    NARRATIVE_ENABLED = _env("NARRATIVE_ENABLED", "true").lower() in ("1", "true", "yes")
    NARRATIVE_MODEL = _env("NARRATIVE_MODEL", "deepseek-v4-flash")
    NARRATIVE_TEMPERATURE = float(_env("NARRATIVE_TEMPERATURE", "0.9"))
    NARRATIVE_MAX_TOKENS = int(_env("NARRATIVE_MAX_TOKENS", "150"))
    NARRATIVE_KEEP_HISTORY = _env("NARRATIVE_KEEP_HISTORY", "false").lower() in ("1", "true", "yes")
