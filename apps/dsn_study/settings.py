# apps/dsn_study/settings.py
# 把 DSN Study 的环境变量绑定到 harness 命名空间化配置。

from __future__ import annotations

from harness.settings import Settings

_BOOL = "bool"
_INT = "int"
_FLOAT = "float"
_STR = "str"


def _bind(ns, attr, env_key, default=None, kind=_STR):
    if kind == "bool":
        ns.bind_bool(attr, env_key, default=bool(default))
    elif kind == "int":
        try:
            int_val = int(default or 0)
        except (ValueError, TypeError):
            int_val = 0
        ns.bind_int(attr, env_key, default=int_val)
    elif kind == "float":
        try:
            float_val = float(default or 0.0)
        except (ValueError, TypeError):
            float_val = 0.0
        ns.bind_float(attr, env_key, default=float_val)
    else:
        ns.bind(attr, env_key, default=default)


def bind_dsn_study_settings(settings: Settings) -> Settings:
    """绑定 DSN Study 各子系统的配置命名空间。"""

    # ── 模型 ──
    model = settings.namespace("model")
    _bind(model, "main_model_type", "MAIN_MODEL_TYPE", "openai")
    _bind(model, "main_model_name", "MAIN_MODEL_NAME", "deepseek-v4-flash")
    _bind(model, "api_key", "OPENAI_API_KEY", "")
    _bind(model, "api_base", "OPENAI_API_BASE", "https://api.deepseek.com/v1")
    _bind(model, "llamacpp_bin", "LLAMACPP_BIN", "~/llama.cpp/build/bin/llama-server")
    _bind(model, "llamacpp_base_url", "LLAMACPP_BASE_URL", "http://127.0.0.1:8080")
    _bind(model, "llamacpp_model_path", "LLAMACPP_MODEL_PATH", "")
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

    # ── 学习特化子系统（题库/模考/图谱） ──
    study = settings.namespace("study")
    _bind(study, "question_bank_db", "QUESTION_BANK_DB_PATH", ".dsn/question_bank.db")
    _bind(study, "exam_sim_enabled", "EXAM_SIM_ENABLED", True, _BOOL)
    _bind(study, "ocr_model_type", "OCR_MODEL_TYPE", "openai")
    _bind(study, "ocr_model_name", "OCR_MODEL_NAME", "glm-ocr")

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
