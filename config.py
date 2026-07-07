
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
    # ==================== 性能模式 ====================
    # "realtime" — 完整实时流程（World旁白/情绪分析/记忆摘要同步执行）
    # "fastcache" — 快速缓存模式，旁白/情绪/记忆挂起到空闲队列执行
    PERFORMANCE_MODE = _env("PERFORMANCE_MODE", "realtime")

    # ==================== 验证系统 ====================
    LITTLESKIN_CLIENT_ID = _env("LITTLESKIN_CLIENT_ID", "")
    LITTLESKIN_CLIENT_SECRET = _env("LITTLESKIN_CLIENT_SECRET", "")

    # JWT 密钥
    JWT_SECRET = _env("JWT_SECRET", "dsn-exp-auto-secret")

    # ==================== 分层认证系统 ====================
    AUTH_SESSION_DAYS = int(_env("AUTH_SESSION_DAYS", "30"))
    AUTH_PAIRING_DIGITS = int(_env("AUTH_PAIRING_DIGITS", "8"))
    AUTH_PAIRING_TIMEOUT = int(_env("AUTH_PAIRING_TIMEOUT", "300"))
    AUTH_WEBAUTHN_RP_NAME = _env("AUTH_WEBAUTHN_RP_NAME", "DSN-exp")
    AUTH_TOTP_ISSUER = _env("AUTH_TOTP_ISSUER", "DSN-exp")

    # ==================== OpenAI 兼容 API ====================
    OPENAI_API_KEY = _env("OPENAI_API_KEY", required=True)
    OPENAI_API_BASE = _env("OPENAI_API_BASE", "https://api.deepseek.com/v1")
    REASONER_ENABLED = _env("REASONER_ENABLED", "true").lower() == "true"
    REASONER_MODEL = _env("REASONER_MODEL", "deepseek-v4-pro")
    REASONER_TIMEOUT = int(_env("REASONER_TIMEOUT", "1200"))

    # ==================== 本地服务 API ====================
    LMSTUDIO_BASE_URL = _env("LMSTUDIO_BASE_URL", "http://localhost:4501")
    TTS_BASE_URL = _env("TTS_BASE_URL", "http://127.0.0.1:9880")

    # ==================== 主模型配置 ====================
    MAIN_MODEL_TYPE = _env("MAIN_MODEL_TYPE", "openai")
    MAIN_MODEL_NAME = _env("MAIN_MODEL_NAME", "deepseek-v4-flash")
    LMSTUDIO_TEMPERATURE = float(_env("LMSTUDIO_TEMPERATURE", "0.7"))
    LMSTUDIO_MAX_TOKENS = int(_env("LMSTUDIO_MAX_TOKENS", "4096"))
    LMSTUDIO_TIMEOUT = int(_env("LMSTUDIO_TIMEOUT", "300"))

    # ==================== 存储配置 ====================
    DATABASE_PATH = _env("DATABASE_PATH", "DSN_usrdata.db")
    LOG_DIR = _env("LOG_DIR", "logs")

    # ==================== 服务配置 ====================
    SERVER_HOST = _env("SERVER_HOST", "0.0.0.0")
    SERVER_PORT = int(_env("SERVER_PORT", "5000"))
    SERVER_BASE_URL = _env("SERVER_BASE_URL", "")  # 对外访问地址，为空则自动检测
    LOCAL_CALLBACK_PORT = int(_env("LOCAL_CALLBACK_PORT", "5001"))

    # ==================== 记忆与摘要 ====================
    MEMORY_ENABLED = _env("MEMORY_ENABLED", "true").lower() == "true"
    MEMORY_SUMMARY_BACKEND = _env("MEMORY_SUMMARY_BACKEND", "openai")  # "openai" | "lmstudio"
    MEMORY_MODEL = _env("MEMORY_MODEL", "deepseek-v4-flash")
    MEMORY_SUMMARY_LENGTH = int(_env("MEMORY_SUMMARY_LENGTH", "100"))
    MEMORY_CONTEXT_WINDOW_SIZE = int(_env("MEMORY_CONTEXT_WINDOW_SIZE", "80"))
    MEMORY_REPLACE_THRESHOLD_RATIO = float(_env("MEMORY_REPLACE_THRESHOLD_RATIO", "0.7"))
    MEMORY_ASYNC_ENABLED = _env("MEMORY_ASYNC_ENABLED", "true").lower() == "true"

    # ==================== 向量嵌入检索 ====================
    MEMORY_EMBEDDING_ENABLED = _env("MEMORY_EMBEDDING_ENABLED", "false").lower() == "true"
    MEMORY_EMBEDDING_MODEL = _env("MEMORY_EMBEDDING_MODEL", "text-embedding-nomic-embed-text-v1.5@f16")
    MEMORY_EMBEDDING_DIMS = int(_env("MEMORY_EMBEDDING_DIMS", "768"))
    MEMORY_EMBEDDING_WEIGHT = float(_env("MEMORY_EMBEDDING_WEIGHT", "0.6"))

    # ==================== 用户观察日记 ====================
    NOTEBOOK_ENABLED = _env("NOTEBOOK_ENABLED", "true").lower() == "true"  # 是否启用观察日记
    NOTEBOOK_FREQUENCY = int(_env("NOTEBOOK_FREQUENCY", "10"))  # 每 N 轮对话触发一次笔记

    # ==================== TTS 文本预处理 ====================
    TTS_PROCESS_ENABLED = _env("TTS_PROCESS_ENABLED", "true").lower() == "true"
    TTS_PROCESS_MODEL = _env("TTS_PROCESS_MODEL", None) or _env("MEMORY_MODEL", "google/gemma-3-4b")
    TTS_PROCESS_MAX_TOKENS = int(_env("TTS_PROCESS_MAX_TOKENS", "1024"))
    TTS_PROCESS_TEMPERATURE = float(_env("TTS_PROCESS_TEMPERATURE", "0.2"))
    TTS_PROCESS_TIMEOUT = int(_env("TTS_PROCESS_TIMEOUT", "30"))

    # ==================== ASR 配置 ====================
    ASR_ENABLED = _env("ASR_ENABLED", "false").lower() == "true"
    ASR_DEVICE = _env("ASR_DEVICE", "cuda")
    ASR_GPU_ID = _env("ASR_GPU_ID", "")  # 指定 GPU 编号，如 "0"、"1"，留空则用 ASR_DEVICE
    DEBUG_ASR = _env("DEBUG_ASR", "false").lower() == "true"

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
    NARRATIVE_MODEL_TYPE = _env("NARRATIVE_MODEL_TYPE", "lmstudio")
    NARRATIVE_MODEL = _env("NARRATIVE_MODEL", "google/gemma-3-4b")
    NARRATIVE_TEMPERATURE = float(_env("NARRATIVE_TEMPERATURE", "0.9"))
    NARRATIVE_MAX_TOKENS = int(_env("NARRATIVE_MAX_TOKENS", "150"))
    NARRATIVE_KEEP_HISTORY = _env("NARRATIVE_KEEP_HISTORY", "false").lower() in ("1", "true", "yes")
    NARRATIVE_PRE_ENABLED = _env("NARRATIVE_PRE_ENABLED", "true").lower() == "true"

    # ==================== 驻守模型 ====================
    STEWARD_ENABLED = _env("STEWARD_ENABLED", "true").lower() == "true"
    STEWARD_MODEL_TYPE = _env("STEWARD_MODEL_TYPE", "lmstudio")
    STEWARD_MODEL_NAME = _env("STEWARD_MODEL_NAME", "google/gemma-3-4b")
    STEWARD_TIMEOUT = int(_env("STEWARD_TIMEOUT", "300"))

    # ==================== 视觉多模态 ====================
    VISION_ENABLED = _env("VISION_ENABLED", "true").lower() == "true"
    VISION_PROMPT = _env("VISION_PROMPT", "请详细描述这张图片的内容")

    # ==================== 视觉模型 API（通用视觉，如 GLM-4.6V / GPT-4V） ====================
    VISION_API_KEY = _env("VISION_API_KEY", "")
    VISION_API_BASE = _env("VISION_API_BASE", "https://open.bigmodel.cn/api/paas/v4")
    VISION_MODEL_NAME = _env("VISION_MODEL_NAME", "glm-4.6v")
    # 启用后用 VisionModel 接管所有 OCR 及 2md 布局分析，直接生成 .hmd
    VISION_OVERRIDE = _env("VISION_OVERRIDE", "false").lower() == "true"

    # ==================== 主动视觉感知 ====================
    ACTIVE_VISION_ENABLED = _env("ACTIVE_VISION_ENABLED", "false").lower() == "true"
    ACTIVE_VISION_INTERVAL = int(_env("ACTIVE_VISION_INTERVAL", "300"))  # 秒，主动观测间隔
    ACTIVE_VISION_PROACTIVE_COOLDOWN = int(_env("ACTIVE_VISION_PROACTIVE_COOLDOWN", "600"))  # 秒，主动通知冷却
    ACTIVE_VISION_PERIODIC_NOTIFY_MIN = int(_env("ACTIVE_VISION_PERIODIC_NOTIFY_MIN", "30"))  # 分钟，周期性通知间隔
    CAMERA_DEVICE_ID = int(_env("CAMERA_DEVICE_ID", "0"))


    # ==================== OCR 文档处理 ====================
    OCR_MODEL = _env("OCR_MODEL", "deepseek-ocr")
    OCR_BASE_URL = _env("OCR_BASE_URL", "http://localhost:4502")
    OCR_UNLOAD_AFTER_USE = _env("OCR_UNLOAD_AFTER_USE", "true").lower() == "true"

    # ==================== 2md 文档解析 API ====================
    TWO_MD_API = _env("TWO_MD_API", "http://localhost:8000")

    # ==================== 人格系统 v3 ====================
    PERSONALITY_V3_ENABLED = _env("PERSONALITY_V3_ENABLED", "true").lower() == "true"
    PERSONALITY_V3_OVERRIDE_V2 = _env("PERSONALITY_V3_OVERRIDE_V2", "true").lower() == "true"
    PERSONALITY_MODEL_NAME = _env("PERSONALITY_MODEL_NAME", "google/gemma-3-4b")
    PERSONALITY_MODEL_URL = _env("PERSONALITY_MODEL_URL", None) or _env("LMSTUDIO_BASE_URL", "http://localhost:4501")
    DISTILLATION_MODEL = _env("DISTILLATION_MODEL", "openai")  # "openai" | "lmstudio"
    PERSONALITY_V3_DEFAULT_CARD = _env("PERSONALITY_V3_DEFAULT_CARD", "")

    # ==================== 工作区系统 ====================
    WORKSPACE_DIR = _env("WORKSPACE_DIR", ".dsn/workspace")

    # ==================== 模型共存管理 ====================
    MAX_CONCURRENT_LM_MODELS = int(_env("MAX_CONCURRENT_LM_MODELS", "1"))
    MODEL_LOAD_TIMEOUT = int(_env("MODEL_LOAD_TIMEOUT", "180"))
    MODEL_REQUEST_TIMEOUT = int(_env("MODEL_REQUEST_TIMEOUT", "300"))
    TTS_FAST_FIRST_LINE = _env("TTS_FAST_FIRST_LINE", "true").lower() == "true"

    # ==================== Token 消耗定价 (USD / 1M tokens) ====================
    # DeepSeek v4-flash (cache miss)
    DEEPSEEK_FLASH_INPUT_PRICE = 0.14
    DEEPSEEK_FLASH_OUTPUT_PRICE = 0.28
    # DeepSeek v4-pro (cache miss)
    DEEPSEEK_PRO_INPUT_PRICE = 0.435
    DEEPSEEK_PRO_OUTPUT_PRICE = 0.87

    # ==================== 语义缓存系统 ====================
    SEMANTIC_CACHE_ENABLED = _env("SEMANTIC_CACHE_ENABLED", "false").lower() == "true"
    SEMANTIC_CACHE_DIR = _env("SEMANTIC_CACHE_DIR", ".dsn/semantic_cache")
    SEMANTIC_CACHE_SIMILARITY_THRESHOLD = float(_env("SEMANTIC_CACHE_SIMILARITY_THRESHOLD", "0.85"))
    SEMANTIC_CACHE_MAX_ENTRIES = int(_env("SEMANTIC_CACHE_MAX_ENTRIES", "5000"))

    # ==================== 工具调用模式 ====================
    TOOL_CALL_MODE = _env("TOOL_CALL_MODE", "native")  # "native" | "xml" | "auto"
    TOOL_CALL_MODEL = _env("TOOL_CALL_MODEL", "deepseek-v4-pro")

    # ==================== 调试模式 ====================
    DEBUG_PLAY_AS_MODEL = _env("DEBUG_PLAY_AS_MODEL", "false").lower() == "true"
    DEBUG_PLAY_AS_MODEL_PORT = int(_env("DEBUG_PLAY_AS_MODEL_PORT", "5050"))

    @classmethod
    def load_skill_configs(cls):
        """扫描所有 skills 目录下的 skill.env，加载到 Config 和环境变量"""
        import logging
        _log = logging.getLogger("Config")
        from dotenv import load_dotenv as _load_dotenv
        for _base_key in ("builtin", "custom"):
            _base_dir = Path(__file__).parent / "skills" / _base_key
            if not _base_dir.exists():
                continue
            for _skill_dir in sorted(_base_dir.iterdir()):
                _env_file = _skill_dir / "skill.env"
                if not _env_file.exists():
                    continue
                _load_dotenv(_env_file)
                _count = 0
                for _line in _env_file.read_text(encoding="utf-8").splitlines():
                    _line = _line.strip()
                    if not _line or _line.startswith("#") or "=" not in _line:
                        continue
                    _key, _val = _line.split("=", 1)
                    _key = _key.strip()
                    _val = _val.strip()
                    _env_val = os.environ.get(_key, _val)
                    try:
                        if _val.lower() in ("true", "false"):
                            _env_val = _env_val.lower() == "true"
                        elif "." in _val:
                            _env_val = float(_env_val)
                        else:
                            _env_val = int(_env_val)
                    except ValueError:
                        pass
                    setattr(cls, _key, _env_val)
                    _count += 1
                _log.info("skill.env: %s (%d 项)", _skill_dir.name, _count)
