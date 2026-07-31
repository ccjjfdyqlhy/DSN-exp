
# DSN-exp/config.py
# 所有配置均从环境变量或 .env 文件读取，切勿在此文件中硬编码密钥。

import os
from pathlib import Path

# 加载 .env 文件（如果存在）
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    pass


def _env(key: str, default=None, required: bool = False):
    val = os.environ.get(key, default)
    if required and not val:
        raise EnvironmentError(
            f"缺少必需的环境变量: {key}\n请参考 .env.example 创建 .env 文件。"
        )
    return val


def _env_bool(key: str, default: str = "false") -> bool:
    return str(_env(key, default)).lower() in ("1", "true", "yes", "on")


class Config:
    # ═══════════════════════════════════════════════════════════════════════
    # 第一层: 必需配置 — 不填系统无法运行
    # ═══════════════════════════════════════════════════════════════════════

    # 主对话模型
    MAIN_MODEL_TYPE = _env("MAIN_MODEL_TYPE", "openai")         # "openai" | "lmstudio"
    MAIN_MODEL_NAME = _env("MAIN_MODEL_NAME", "deepseek-v4-flash")

    # OpenAI 兼容 API；主模型使用 openai 后端时 API Key 必填。
    OPENAI_API_KEY = _env(
        "OPENAI_API_KEY",
        "",
        required=MAIN_MODEL_TYPE == "openai",
    )
    OPENAI_API_BASE = _env("OPENAI_API_BASE", "https://api.deepseek.com/v1")

    # ═══════════════════════════════════════════════════════════════════════
    # 第二层: 服务与存储
    # ═══════════════════════════════════════════════════════════════════════

    # ── 服务 ──
    SERVER_HOST = _env("SERVER_HOST", "0.0.0.0")
    SERVER_PORT = int(_env("SERVER_PORT", "5000"))
    SERVER_BASE_URL = _env("SERVER_BASE_URL", "")               # 对外访问地址，为空则自动检测
    LOCAL_CALLBACK_PORT = int(_env("LOCAL_CALLBACK_PORT", "5001"))

    # ── 存储 ──
    DATABASE_PATH = _env("DATABASE_PATH", "DSN_usrdata.db")
    LOG_DIR = _env("LOG_DIR", "logs")
    LOG_MAX_BYTES = max(1024, int(_env("LOG_MAX_BYTES", str(10 * 1024 * 1024))))
    LOG_BACKUP_COUNT = max(0, int(_env("LOG_BACKUP_COUNT", "30")))
    LOG_BUFFER_SIZE = max(1, int(_env("LOG_BUFFER_SIZE", "200")))
    LOG_LEVEL = _env("LOG_LEVEL", "INFO")

    # ── 安全 ──
    JWT_SECRET = _env("JWT_SECRET", "dsn-exp-auto-secret")

    # ═══════════════════════════════════════════════════════════════════════
    # 第三层: 模型基础设施
    # ═══════════════════════════════════════════════════════════════════════

    # ── 主模型参数（LMStudio 后端专用）──
    LMSTUDIO_ENABLED = _env("LMSTUDIO_ENABLED", "true").lower() == "true"
    LMSTUDIO_BASE_URL = _env("LMSTUDIO_BASE_URL", "http://localhost:4501")
    LMSTUDIO_TEMPERATURE = float(_env("LMSTUDIO_TEMPERATURE", "0.7"))
    LMSTUDIO_MAX_TOKENS = int(_env("LMSTUDIO_MAX_TOKENS", "4096"))
    LMSTUDIO_TIMEOUT = int(_env("LMSTUDIO_TIMEOUT", "300"))

    # ── 推理模型 ──
    REASONER_ENABLED = _env("REASONER_ENABLED", "true").lower() == "true"
    REASONER_MODEL = _env("REASONER_MODEL", "deepseek-v4-pro")
    REASONER_TIMEOUT = int(_env("REASONER_TIMEOUT", "1200"))

    # ── 模型共存管理 ──
    MAX_CONCURRENT_LM_MODELS = int(_env("MAX_CONCURRENT_LM_MODELS", "1"))
    MODEL_LOAD_TIMEOUT = int(_env("MODEL_LOAD_TIMEOUT", "180"))
    MODEL_REQUEST_TIMEOUT = int(_env("MODEL_REQUEST_TIMEOUT", "300"))

    # ── Token 消耗定价 (USD / 1M tokens) ──
    TOKEN_PRICE_FLASH_INPUT = float(_env("TOKEN_PRICE_FLASH_INPUT", "0.14"))
    TOKEN_PRICE_FLASH_OUTPUT = float(_env("TOKEN_PRICE_FLASH_OUTPUT", "0.28"))
    TOKEN_PRICE_PRO_INPUT = float(_env("TOKEN_PRICE_PRO_INPUT", "0.435"))
    TOKEN_PRICE_PRO_OUTPUT = float(_env("TOKEN_PRICE_PRO_OUTPUT", "0.87"))
    DEEPSEEK_FLASH_INPUT_PRICE = TOKEN_PRICE_FLASH_INPUT
    DEEPSEEK_FLASH_OUTPUT_PRICE = TOKEN_PRICE_FLASH_OUTPUT
    DEEPSEEK_PRO_INPUT_PRICE = TOKEN_PRICE_PRO_INPUT
    DEEPSEEK_PRO_OUTPUT_PRICE = TOKEN_PRICE_PRO_OUTPUT

    # ═══════════════════════════════════════════════════════════════════════
    # 第四层: 子系统
    # ═══════════════════════════════════════════════════════════════════════

    # ── 记忆与摘要 ──
    MEMORY_ENABLED = _env("MEMORY_ENABLED", "true").lower() == "true"
    MEMORY_SUMMARY_BACKEND = _env("MEMORY_SUMMARY_BACKEND", "openai")    # "openai" | "lmstudio"
    MEMORY_MODEL = _env("MEMORY_MODEL", "deepseek-v4-flash")
    MEMORY_SUMMARY_LENGTH = int(_env("MEMORY_SUMMARY_LENGTH", "100"))
    MEMORY_CONTEXT_WINDOW_SIZE = int(_env("MEMORY_CONTEXT_WINDOW_SIZE", "80"))
    MEMORY_REPLACE_THRESHOLD_RATIO = float(_env("MEMORY_REPLACE_THRESHOLD_RATIO", "0.7"))
    MEMORY_ASYNC_ENABLED = _env("MEMORY_ASYNC_ENABLED", "true").lower() == "true"
    MEMORY_SEARCH_THRESHOLD = min(1.0, max(0.0, float(_env("MEMORY_SEARCH_THRESHOLD", "0.5"))))
    MEMORY_DETAIL_CHARS_PER_ROUND = max(1, int(_env("MEMORY_DETAIL_CHARS_PER_ROUND", "4000")))
    MEMORY_TOTAL_DETAIL_CHARS = max(1, int(_env("MEMORY_TOTAL_DETAIL_CHARS", "16000")))
    MEMORY_QUERY_LIMIT = max(1, int(_env("MEMORY_QUERY_LIMIT", "50")))

    # 摘要模型参数
    SUMMARY_RETRY_COUNT = max(0, int(_env("SUMMARY_RETRY_COUNT", "3")))
    SUMMARY_RETRY_BACKOFF_SECONDS = max(0.0, float(_env("SUMMARY_RETRY_BACKOFF_SECONDS", "1.0")))
    SUMMARY_CONTEXT_SIZE = max(0, int(_env("SUMMARY_CONTEXT_SIZE", "10")))
    SUMMARY_TEMPERATURE = min(2.0, max(0.0, float(_env("SUMMARY_TEMPERATURE", "0.1"))))
    SUMMARY_TIMEOUT = max(1, int(_env("SUMMARY_TIMEOUT", "60")))

    # ── 向量嵌入检索 ──
    MEMORY_EMBEDDING_ENABLED = _env("MEMORY_EMBEDDING_ENABLED", "false").lower() == "true"
    MEMORY_EMBEDDING_MODEL = _env("MEMORY_EMBEDDING_MODEL", "text-embedding-nomic-embed-text-v1.5@f16")
    MEMORY_EMBEDDING_DIMS = int(_env("MEMORY_EMBEDDING_DIMS", "768"))
    MEMORY_EMBEDDING_WEIGHT = float(_env("MEMORY_EMBEDDING_WEIGHT", "0.6"))

    # ── 人格系统 V3 ──
    PERSONALITY_V3_ENABLED = _env("PERSONALITY_V3_ENABLED", "true").lower() == "true"
    PERSONALITY_V3_OVERRIDE_V2 = _env("PERSONALITY_V3_OVERRIDE_V2", "true").lower() == "true"
    PERSONALITY_MODEL_NAME = _env("PERSONALITY_MODEL_NAME", "google/gemma-3-4b")
    PERSONALITY_MODEL_URL = _env("PERSONALITY_MODEL_URL", None) or _env("LMSTUDIO_BASE_URL", "http://localhost:4501")
    DISTILLATION_MODEL = _env("DISTILLATION_MODEL", "openai")
    PERSONALITY_V3_DEFAULT_CARD = _env("PERSONALITY_V3_DEFAULT_CARD", "")

    # ── 叙事世界模型 ──
    WORLD_ENABLED = _env("WORLD_ENABLED", "true").lower() in ("1", "true", "yes")
    WORLD_PRESET = _env("WORLD_PRESET", "default")
    WORLD_UPDATE_INTERVAL = int(_env("WORLD_UPDATE_INTERVAL", "60"))

    NARRATIVE_ENABLED = _env("NARRATIVE_ENABLED", "true").lower() in ("1", "true", "yes")
    NARRATIVE_MODEL_TYPE = _env("NARRATIVE_MODEL_TYPE", "lmstudio")
    NARRATIVE_MODEL = _env("NARRATIVE_MODEL", "google/gemma-3-4b")
    NARRATIVE_TEMPERATURE = float(_env("NARRATIVE_TEMPERATURE", "0.9"))
    NARRATIVE_MAX_TOKENS = int(_env("NARRATIVE_MAX_TOKENS", "150"))
    NARRATIVE_KEEP_HISTORY = _env("NARRATIVE_KEEP_HISTORY", "false").lower() in ("1", "true", "yes")
    NARRATIVE_PRE_ENABLED = _env("NARRATIVE_PRE_ENABLED", "true").lower() == "true"

    # ── 工具调用 ──
    TOOL_CALL_MODE = _env("TOOL_CALL_MODE", "native")          # "native" | "xml" | "auto"
    TOOL_CALL_MODEL = _env("TOOL_CALL_MODEL", "deepseek-v4-pro")
    TOOLBOX_ENABLED = _env("TOOLBOX_ENABLED", "true") == "true"

    # ── 文件操作限制 ──
    FILE_READ_MAX_SIZE_MB = max(1, int(_env("FILE_READ_MAX_SIZE_MB", "1")))

    # ═══════════════════════════════════════════════════════════════════════
    # 第五层: 语音系统
    # ═══════════════════════════════════════════════════════════════════════

    # ── ASR ──
    ASR_ENABLED = _env("ASR_ENABLED", "false").lower() == "true"
    ASR_DEVICE = _env("ASR_DEVICE", "cuda")
    ASR_GPU_ID = _env("ASR_GPU_ID", "")
    ASR_BATCH_SIZE_SECONDS = max(1, int(_env("ASR_BATCH_SIZE_SECONDS", "60")))
    ASR_CONVERT_TIMEOUT = max(1, int(_env("ASR_CONVERT_TIMEOUT", "15")))
    DEBUG_ASR = _env("DEBUG_ASR", "false").lower() == "true"

    # ── ASR 过滤器 ──
    ASR_FILTER_ENABLED = _env("ASR_FILTER_ENABLED", "false").lower() == "true"
    FILTER_MODEL = _env("FILTER_MODEL", "llama-3.2-1b-instruct")

    # ── TTS ──
    TTS_ENABLED = _env("TTS_ENABLED", "true").lower() == "true"
    TTS_BASE_URL = _env("TTS_BASE_URL", "http://127.0.0.1:9880")
    TTS_PROBE_TIMEOUT = max(0.1, float(_env("TTS_PROBE_TIMEOUT", "3.0")))
    TTS_PROBE_ATTEMPTS = max(1, int(_env("TTS_PROBE_ATTEMPTS", _env("TTS_PROBE_RETRIES", "4"))))
    TTS_PROBE_RETRIES = TTS_PROBE_ATTEMPTS
    TTS_PROBE_BACKOFF_BASE = max(0.0, float(_env("TTS_PROBE_BACKOFF_BASE", "2.0")))
    TTS_PROBE_BACKOFF_MAX = max(TTS_PROBE_BACKOFF_BASE, float(_env("TTS_PROBE_BACKOFF_MAX", "8.0")))
    TTS_FAST_FIRST_LINE = _env("TTS_FAST_FIRST_LINE", "true").lower() == "true"

    # ── TTS 文本预处理 ──
    TTS_PROCESS_ENABLED = _env("TTS_PROCESS_ENABLED", "true").lower() == "true"
    TTS_PROCESS_MODEL = _env("TTS_PROCESS_MODEL", None) or _env("MEMORY_MODEL", "google/gemma-3-4b")
    TTS_PROCESS_MAX_TOKENS = int(_env("TTS_PROCESS_MAX_TOKENS", "1024"))
    TTS_PROCESS_TEMPERATURE = float(_env("TTS_PROCESS_TEMPERATURE", "0.2"))
    TTS_PROCESS_TIMEOUT = int(_env("TTS_PROCESS_TIMEOUT", "30"))

    # ═══════════════════════════════════════════════════════════════════════
    # 第六层: 视觉系统
    # ═══════════════════════════════════════════════════════════════════════

    # ── 视觉模型（GLM-4.6V / GPT-4V 等）──
    VISION_ENABLED = _env("VISION_ENABLED", "true").lower() == "true"
    VISION_PROMPT = _env("VISION_PROMPT", "请详细描述这张图片的内容")
    VISION_API_KEY = _env("VISION_API_KEY", "")
    VISION_API_BASE = _env("VISION_API_BASE", "https://open.bigmodel.cn/api/paas/v4")
    VISION_MODEL_NAME = _env("VISION_MODEL_NAME", "glm-4.6v")
    VISION_OVERRIDE = _env("VISION_OVERRIDE", "false").lower() == "true"

    # ── OCR ──
    OCR_MODEL = _env("OCR_MODEL", "deepseek-ocr")
    OCR_BASE_URL = _env("OCR_BASE_URL", "http://localhost:4502")
    OCR_UNLOAD_AFTER_USE = _env("OCR_UNLOAD_AFTER_USE", "true").lower() == "true"

    # ── 文档解析 ──
    TWO_MD_API = _env("TWO_MD_API", "http://localhost:8000")

    # ── 摄像头 ──
    CAMERA_ENABLED = _env("CAMERA_ENABLED", "true").lower() == "true"
    CAMERA_DEVICE_ID = int(_env("CAMERA_DEVICE_ID", "0"))

    # ── 主动视觉感知 ──
    ACTIVE_VISION_ENABLED = _env("ACTIVE_VISION_ENABLED", "false").lower() == "true"
    ACTIVE_VISION_INTERVAL = int(_env("ACTIVE_VISION_INTERVAL", "300"))
    ACTIVE_VISION_CAMERA = _env("ACTIVE_VISION_CAMERA", "")   # 周期观察用哪台摄像头(逻辑名), 空=主摄像头
    ACTIVE_VISION_PROACTIVE_COOLDOWN = int(_env("ACTIVE_VISION_PROACTIVE_COOLDOWN", "600"))
    ACTIVE_VISION_PERIODIC_NOTIFY_MIN = int(_env("ACTIVE_VISION_PERIODIC_NOTIFY_MIN", "30"))

    # ═══════════════════════════════════════════════════════════════════════
    # 第七层: 高级功能
    # ═══════════════════════════════════════════════════════════════════════

    # ── 认证 ──
    AUTH_SESSION_DAYS = int(_env("AUTH_SESSION_DAYS", "30"))
    AUTH_PAIRING_DIGITS = int(_env("AUTH_PAIRING_DIGITS", "8"))
    AUTH_PAIRING_TIMEOUT = int(_env("AUTH_PAIRING_TIMEOUT", "300"))
    AUTH_WEBAUTHN_RP_NAME = _env("AUTH_WEBAUTHN_RP_NAME", "DSN-exp")
    AUTH_TOTP_ISSUER = _env("AUTH_TOTP_ISSUER", "DSN-exp")

    # ── 任务管理 ──
    TASK_MANAGER_ENABLED = _env("TASK_MANAGER_ENABLED", "true").lower() == "true"
    TASK_MAX_WORKERS = int(_env("TASK_MAX_WORKERS", "5"))
    TASK_COMPLEXITY_THRESHOLD = float(_env("TASK_COMPLEXITY_THRESHOLD", "0.4"))
    REMINDER_CHECK_INTERVAL = int(_env("REMINDER_CHECK_INTERVAL", "60"))
    REMINDER_LIST_LIMIT = max(1, int(_env("REMINDER_LIST_LIMIT", "50")))
    TASK_NOTIFICATION_ENABLED = _env("TASK_NOTIFICATION_ENABLED", "true").lower() == "true"
    ACTION_TIMEOUT = int(_env("ACTION_TIMEOUT", "300"))

    # ── Agent 循环 ──
    AGENT_MAX_STEPS = max(1, int(_env("AGENT_MAX_STEPS", "10")))
    AGENT_TOKEN_BUDGET = max(1, int(_env("AGENT_TOKEN_BUDGET", "1000000")))
    AGENT_TIMEOUT_SECONDS = max(1.0, float(_env("AGENT_TIMEOUT_SECONDS", "120")))

    # ── 双模协同 ──
    DUAL_ENABLED = _env_bool("DUAL_ENABLED", "false")
    INSTANT_MODEL = _env("INSTANT_MODEL", "google/gemma-3-4b")
    INSTANT_MODEL_URL = _env("INSTANT_MODEL_URL", None) or _env("LMSTUDIO_BASE_URL", "http://localhost:4501")
    INSTANT_TEMPERATURE = float(_env("INSTANT_TEMPERATURE", "0.6"))
    INSTANT_MAX_TOKENS = int(_env("INSTANT_MAX_TOKENS", "512"))
    INSTANT_TIMEOUT = max(1, int(_env("INSTANT_TIMEOUT", "15")))
    DUAL_MAIN_WORKERS = max(1, int(_env("DUAL_MAIN_WORKERS", "3")))
    INSTANT_CONTEXT_MAX_MESSAGES = max(4, int(_env("INSTANT_CONTEXT_MAX_MESSAGES", "30")))
    INSTANT_CONTEXT_COMPRESS_THRESHOLD = max(6, int(_env("INSTANT_CONTEXT_COMPRESS_THRESHOLD", "40")))

    # ── 售后维护 ──
    MAINTENANCE_ENABLED = _env("MAINTENANCE_ENABLED", "true").lower() == "true"
    MAINTENANCE_IDLE_TIMEOUT_MINUTES = int(_env("MAINTENANCE_IDLE_TIMEOUT_MINUTES", "60"))
    MAINTENANCE_SCHEDULE_STRATEGY = _env("MAINTENANCE_SCHEDULE_STRATEGY", "predictive")
    MAINTENANCE_FIXED_HOUR = int(_env("MAINTENANCE_FIXED_HOUR", "4"))
    MAINTENANCE_SCHEDULE_CHECK_INTERVAL = int(_env("MAINTENANCE_SCHEDULE_CHECK_INTERVAL", "60"))
    HIBERNATE_MAX_QUEUE = int(_env("HIBERNATE_MAX_QUEUE", "100"))
    MAINTENANCE_PREDICTIVE_MIN_FREE_HOURS = int(_env("MAINTENANCE_PREDICTIVE_MIN_FREE_HOURS", "3"))
    MAINTENANCE_PREDICTIVE_MAX_HOUR = int(_env("MAINTENANCE_PREDICTIVE_MAX_HOUR", "8"))
    MAINTENANCE_PREDICTIVE_IDLE_TRIGGER_MINUTES = int(_env("MAINTENANCE_PREDICTIVE_IDLE_TRIGGER_MINUTES", "60"))
    MAINTENANCE_PREDICTIVE_MIN_DATA_SAMPLES = int(_env("MAINTENANCE_PREDICTIVE_MIN_DATA_SAMPLES", "50"))
    MAINTENANCE_RETRY_ON_FAILURE = _env_bool("MAINTENANCE_RETRY_ON_FAILURE", "true")
    MAINTENANCE_RETRY_DELAY_MINUTES = int(_env("MAINTENANCE_RETRY_DELAY_MINUTES", "30"))
    MAINTENANCE_ESTIMATE_PER_TASK_SECONDS = int(_env("MAINTENANCE_ESTIMATE_PER_TASK_SECONDS", "300"))
    MAINTENANCE_TASK_TIMEOUT_SECONDS = int(_env("MAINTENANCE_TASK_TIMEOUT_SECONDS", "600"))

    # ── 驻守模型 ──
    STEWARD_ENABLED = _env("STEWARD_ENABLED", "true").lower() == "true"
    STEWARD_MODEL_TYPE = _env("STEWARD_MODEL_TYPE", "openai")
    STEWARD_MODEL_NAME = _env("STEWARD_MODEL_NAME", "google/gemma-3-4b")
    STEWARD_TIMEOUT = int(_env("STEWARD_TIMEOUT", "300"))
    STEWARD_TEMPERATURE = float(_env("STEWARD_TEMPERATURE", "0.5"))
    STEWARD_MAX_TOKENS = int(_env("STEWARD_MAX_TOKENS", "2048"))
    STEWARD_HISTORY_LIMIT = int(_env("STEWARD_HISTORY_LIMIT", "40"))

    # ── 语义缓存 ──
    SEMANTIC_CACHE_ENABLED = _env("SEMANTIC_CACHE_ENABLED", "false").lower() == "true"
    SEMANTIC_CACHE_DIR = _env("SEMANTIC_CACHE_DIR", ".dsn/semantic_cache")
    SEMANTIC_CACHE_SIMILARITY_THRESHOLD = float(_env("SEMANTIC_CACHE_SIMILARITY_THRESHOLD", "0.85"))
    SEMANTIC_CACHE_MAX_ENTRIES = int(_env("SEMANTIC_CACHE_MAX_ENTRIES", "5000"))

    # ── 性能模式 ──
    PERFORMANCE_MODE = _env("PERFORMANCE_MODE", "realtime")    # "realtime" | "fastcache"

    # ── 观察日记 ──
    NOTEBOOK_ENABLED = _env("NOTEBOOK_ENABLED", "true").lower() == "true"
    NOTEBOOK_FREQUENCY = int(_env("NOTEBOOK_FREQUENCY", "10"))

    # ── 工作区 ──
    WORKSPACE_DIR = _env("WORKSPACE_DIR", ".dsn/workspace")

    # ── 外部验证 ──
    LITTLESKIN_CLIENT_ID = _env("LITTLESKIN_CLIENT_ID", "")
    LITTLESKIN_CLIENT_SECRET = _env("LITTLESKIN_CLIENT_SECRET", "")

    # ── 调试 ──
    DEBUG_PLAY_AS_MODEL = _env("DEBUG_PLAY_AS_MODEL", "false").lower() == "true"
    DEBUG_PLAY_AS_MODEL_PORT = int(_env("DEBUG_PLAY_AS_MODEL_PORT", "5050"))

    # ── 可选客户端 / 管理端 ──
    WEB_ADMIN_ENABLED = _env_bool("WEB_ADMIN_ENABLED", "false")
    WEB_ADMIN_HOST = _env("WEB_ADMIN_HOST", "127.0.0.1")
    WEB_ADMIN_PORT = int(_env("WEB_ADMIN_PORT", "8008"))
    WEB_ADMIN_PASSWORD = _env("WEB_ADMIN_PASSWORD", "")
    DSN_BASE_URL = _env("DSN_BASE_URL", "http://127.0.0.1:5000")
    DSN_AGENT_TIMEOUT = int(_env("DSN_AGENT_TIMEOUT", "300"))
    DSN_HOST = _env("DSN_HOST", "127.0.0.1")
    DSN_PORT = int(_env("DSN_PORT", "5000"))
    PSYCHOSCOPE_HOST = _env("PSYCHOSCOPE_HOST", "127.0.0.1")
    PSYCHOSCOPE_PORT = int(_env("PSYCHOSCOPE_PORT", "5000"))
    PSYCHOSCOPE_DEBUG = _env_bool("PSYCHOSCOPE_DEBUG", "false")

    @classmethod
    def load_skill_configs(cls):
        """加载 skills/*/skill.env，让技能能声明自己的环境配置。"""
        try:
            from dotenv import load_dotenv as _load_dotenv
        except ImportError:
            return
        import logging

        logger = logging.getLogger("Config")
        for base_key in ("builtin", "custom"):
            base_dir = Path(__file__).parent / "skills" / base_key
            if not base_dir.exists():
                continue
            for skill_dir in sorted(base_dir.iterdir()):
                env_file = skill_dir / "skill.env"
                if not env_file.exists():
                    continue
                _load_dotenv(env_file)
                count = 0
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#") or "=" not in stripped:
                        continue
                    key, raw = stripped.split("=", 1)
                    key = key.strip()
                    raw = raw.strip()
                    value = os.environ.get(key, raw)
                    try:
                        if raw.lower() in ("true", "false"):
                            value = value.lower() == "true"
                        elif "." in raw:
                            value = float(value)
                        else:
                            value = int(value)
                    except (TypeError, ValueError):
                        pass
                    setattr(cls, key, value)
                    count += 1
                logger.info("skill.env: %s (%d 项)", skill_dir.name, count)
