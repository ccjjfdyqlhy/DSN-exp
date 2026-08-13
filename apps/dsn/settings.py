# apps/dsn/settings.py
# 把 DSN 的环境变量绑定到 harness 命名空间化配置。
#
# 现有 config.Config 继续作为兼容门面（import 时快照 + 运行时可变类属性），
# 本模块额外提供"命名空间化"视图，供新代码与 AppBundle 使用。
# 二者读取同一份 .env，长期共存。

from __future__ import annotations

from harness.settings import Settings

# attr -> (env_key, default, converter)
_BOOL = "bool"
_INT = "int"
_FLOAT = "float"
_STR = "str"


def _bind(ns, attr, env_key, default=None, kind=_STR):
    if kind == "bool":
        ns.bind_bool(attr, env_key, default=bool(default))
    elif kind == "int":
        ns.bind_int(attr, env_key, default=int(default or 0))
    elif kind == "float":
        ns.bind_float(attr, env_key, default=float(default or 0.0))
    else:
        ns.bind(attr, env_key, default=default)


def bind_dsn_settings(settings: Settings) -> Settings:
    """绑定 DSN 各子系统的配置命名空间。"""

    # ── 模型 ──
    model = settings.namespace("model")
    _bind(model, "main_model_type", "MAIN_MODEL_TYPE", "openai")
    _bind(model, "main_model_name", "MAIN_MODEL_NAME", "deepseek-v4-flash")
    _bind(model, "api_key", "OPENAI_API_KEY", "")
    _bind(model, "api_base", "OPENAI_API_BASE", "https://api.deepseek.com/v1")
    _bind(model, "max_history", "MODEL_MAX_HISTORY", 12, _INT)
    _bind(model, "agent_max_steps", "AGENT_MAX_STEPS", 15, _INT)
    _bind(model, "toolbox_enabled", "TOOLBOX_ENABLED", True, _BOOL)

    # ── 记忆 ──
    mem = settings.namespace("memory")
    _bind(mem, "enabled", "MEMORY_ENABLED", True, _BOOL)
    _bind(mem, "embedding_enabled", "MEMORY_EMBEDDING_ENABLED", True, _BOOL)
    _bind(mem, "summary_backend", "MEMORY_SUMMARY_BACKEND", "openai")

    # ── 语音 ──
    voice = settings.namespace("voice")
    _bind(voice, "asr_enabled", "ASR_ENABLED", True, _BOOL)
    _bind(voice, "asr_device", "ASR_DEVICE", "cuda")
    _bind(voice, "tts_enabled", "TTS_ENABLED", True, _BOOL)
    _bind(voice, "tts_base_url", "TTS_BASE_URL", "http://127.0.0.1:9880")
    _bind(voice, "tts_process_enabled", "TTS_PROCESS_ENABLED", True, _BOOL)
    _bind(voice, "asr_filter_enabled", "ASR_FILTER_ENABLED", True, _BOOL)

    # ── 陪伴（人格 / 世界） ──
    companion = settings.namespace("companion")
    _bind(companion, "personality_v3_enabled", "PERSONALITY_V3_ENABLED", True, _BOOL)
    _bind(companion, "world_enabled", "WORLD_ENABLED", True, _BOOL)
    _bind(companion, "narrative_enabled", "NARRATIVE_ENABLED", True, _BOOL)

    # ── 个人助理（提醒/闹钟/待办/计划） ──
    personal = settings.namespace("personal")
    _bind(personal, "task_manager_enabled", "TASK_MANAGER_ENABLED", True, _BOOL)

    # ── 语义缓存 ──
    cache = settings.namespace("cache")
    _bind(cache, "semantic_cache_enabled", "SEMANTIC_CACHE_ENABLED", True, _BOOL)
    _bind(cache, "similarity_threshold", "SEMANTIC_CACHE_SIMILARITY_THRESHOLD", 0.9, _FLOAT)

    # ── 视觉 / 追踪 ──
    vision = settings.namespace("vision")
    _bind(vision, "active_vision_enabled", "ACTIVE_VISION_ENABLED", False, _BOOL)
    _bind(vision, "vision_warmup", "VISION_WARMUP", True, _BOOL)

    tracking = settings.namespace("tracking")
    _bind(tracking, "ai_access_enabled", "TRACKING_AI_ACCESS_ENABLED", True, _BOOL)

    return settings
