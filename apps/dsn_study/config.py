
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

def _env(key: str, default: str = "", required: bool = False) -> str:
    val = os.environ.get(key, default)
    if required and not val:
        raise EnvironmentError(
            f"缺少必需的环境变量: {key}\n请参考 .env.example 创建 .env 文件。"
        )
    return val if val is not None else ""

def _env_bool(key: str, default: str = "false") -> bool:
    return str(_env(key, default)).lower() in ("1", "true", "yes", "on")


def resource_idle_shutdown_enabled() -> bool:
    """资源池的**空闲回收总开关**（运行时求值）。

    规则：
      * 显式配置 RESOURCE_IDLE_SHUTDOWN → 以它为准；
      * 否则跟随语音开关 VOICE_IDLE_SHUTDOWN（向后兼容旧配置 ——
        这项开关原本只管语音资源，现在扩到整个资源池）。

    为什么是函数而不是类属性：测试会 monkeypatch Config.VOICE_IDLE_SHUTDOWN，
    若在类定义时就把「跟随关系」算死，运行时再改就失灵了。
    """
    raw = str(_env("RESOURCE_IDLE_SHUTDOWN", "")).strip().lower()
    if raw:
        return raw in ("1", "true", "yes", "on")
    return bool(getattr(Config, "VOICE_IDLE_SHUTDOWN", False))


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
    OPENAI_BACKUP_API_KEY = _env("OPENAI_BACKUP_API_KEY", "")

    # 多账号 FailoverChat: 近期失败过的账号自动排后的窗口（秒）。
    # 该窗口内失败的账号会被自动放到回退链末尾（手动 promote/demote 仍保留，
    # 但"刚失败过"优先于提优，避免在坏账号上白等）。窗口过后恢复原优先级排序。
    FAILOVER_DOWN_WINDOW = int(_env("FAILOVER_DOWN_WINDOW", "3600"))

    # ═══════════════════════════════════════════════════════════════════════
    # 第二层: 服务与存储
    # ═══════════════════════════════════════════════════════════════════════

    # ── 服务 ──
    SERVER_HOST = _env("SERVER_HOST", "0.0.0.0")
    SERVER_PORT = int(_env("SERVER_PORT", "5000"))
    SERVER_BASE_URL = _env("SERVER_BASE_URL", "")               # 对外访问地址，为空则自动检测
    LOCAL_CALLBACK_PORT = int(_env("LOCAL_CALLBACK_PORT", "5001"))

    # ── 存储 ──
    DATABASE_PATH = _env("DATABASE_PATH", "DSN_study_usrdata.db")
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

    # ==================== 存储配置 ====================
    QUESTION_BANK_DB_PATH = _env("QUESTION_BANK_DB_PATH", ".dsn/study_question_bank.db")

    # ── 模型共存管理 ──
    MAX_CONCURRENT_LM_MODELS = int(_env("MAX_CONCURRENT_LM_MODELS", "1"))
    MODEL_LOAD_TIMEOUT = int(_env("MODEL_LOAD_TIMEOUT", "180"))
    MODEL_REQUEST_TIMEOUT = int(_env("MODEL_REQUEST_TIMEOUT", "300"))
    # 语音轮的模型调用超时（秒）—— 对讲机要"快失败"：
    # provider 偶尔会卡住几十秒，等下去用户只会以为设备坏了。
    VOICE_MODEL_TIMEOUT = int(_env("VOICE_MODEL_TIMEOUT", "45"))

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
    MEMORY_SUMMARY_BACKEND = _env("MEMORY_SUMMARY_BACKEND", "openai")    # "openai" | "lmstudio"
    MEMORY_MODEL = _env("MEMORY_MODEL", "deepseek-v4-flash")
    MEMORY_QUERY_LIMIT = max(1, int(_env("MEMORY_QUERY_LIMIT", "50")))

    # 摘要模型参数
    SUMMARY_RETRY_COUNT = max(0, int(_env("SUMMARY_RETRY_COUNT", "3")))
    SUMMARY_RETRY_BACKOFF_SECONDS = max(0.0, float(_env("SUMMARY_RETRY_BACKOFF_SECONDS", "1.0")))
    SUMMARY_CONTEXT_SIZE = max(0, int(_env("SUMMARY_CONTEXT_SIZE", "10")))
    SUMMARY_TEMPERATURE = min(2.0, max(0.0, float(_env("SUMMARY_TEMPERATURE", "0.1"))))
    SUMMARY_TIMEOUT = max(1, int(_env("SUMMARY_TIMEOUT", "60")))
    # 话题 LLM judge 的超时（秒）。它在**对话热路径**上同步调用，
    # 超时就走规则判定（judge 失败本来就有回退逻辑）。
    TOPIC_JUDGE_TIMEOUT = max(1, int(_env("TOPIC_JUDGE_TIMEOUT", "8")))
    # 话题摘要的输入长度上限（字符）。20 条长消息能到 18k token，
    # provider 要 7s+ —— 必须封顶。
    TOPIC_SUMMARY_INPUT_CHARS = max(200, int(
        _env("TOPIC_SUMMARY_INPUT_CHARS", "3000")))
    # 话题摘要的 LLM 超时（秒）。
    TOPIC_SUMMARY_TIMEOUT = max(1, int(_env("TOPIC_SUMMARY_TIMEOUT", "20")))

    # ── 向量嵌入检索 ──
    MEMORY_EMBEDDING_DIMS = int(_env("MEMORY_EMBEDDING_DIMS", "768"))

    # ── 话题系统 (话题) ──
    TOPIC_IDLE_SECONDS = max(1, int(_env("TOPIC_IDLE_SECONDS", "1800")))   # 30min 不聊 → 关话题/划新话题
    TOPIC_ACTIVATION_THRESHOLD = min(1.0, max(0.0, float(_env("TOPIC_ACTIVATION_THRESHOLD", "0.55"))))
    TOPIC_CONTINUE_THRESHOLD = min(1.0, max(0.0, float(_env("TOPIC_CONTINUE_THRESHOLD", "0.65"))))
    TOPIC_REOPEN_THRESHOLD = min(1.0, max(0.0, float(_env("TOPIC_REOPEN_THRESHOLD", "0.50"))))
    TOPIC_TAIL_ROUNDS = max(1, int(_env("TOPIC_TAIL_ROUNDS", "10")))
    TOPIC_MAX_OPEN_TOPICS = max(1, int(_env("TOPIC_MAX_OPEN_TOPICS", "3")))
    TOPIC_MAX_VERBATIM_CHARS = max(0, int(_env("TOPIC_MAX_VERBATIM_CHARS", "6000")))
    TOPIC_SUMMARY_CHARS = max(0, int(_env("TOPIC_SUMMARY_CHARS", "2000")))
    TOPIC_MEMO_CHARS = max(0, int(_env("TOPIC_MEMO_CHARS", "1200")))
    TOPIC_JUDGE_ENABLED = _env("TOPIC_JUDGE_ENABLED", "true").lower() == "true"
    TOPIC_JUDGE_ALWAYS = _env("TOPIC_JUDGE_ALWAYS", "false").lower() == "true"
    TOPIC_CANDIDATE_K = max(1, int(_env("TOPIC_CANDIDATE_K", "3")))
    # ── 无嵌入信号时的词面兜底 ──
    # 嵌入服务（LMStudio:4501）没起时，话题判定拿不到任何语义信号；
    # 若此时「一律延续当前话题」，会话会被卡死在一个话题里推不下去。
    # 词面相似度（字符 bigram）不需要模型/网络，中文短句够用。
    TOPIC_LEXICAL_ENABLED = _env_bool("TOPIC_LEXICAL_ENABLED", "true")
    # 词面阈值比向量阈值低（bigram 更严）—— 同一话题的续问通常复用关键词。
    # 三个阈值构成一条带：≥CONTINUE 延续；≤NEW 换话题；中间地带证据不足，保守延续。
    TOPIC_LEXICAL_CONTINUE_THRESHOLD = float(
        _env("TOPIC_LEXICAL_CONTINUE_THRESHOLD", "0.28"))
    TOPIC_LEXICAL_NEW_THRESHOLD = float(
        _env("TOPIC_LEXICAL_NEW_THRESHOLD", "0.10"))
    TOPIC_LEXICAL_REOPEN_THRESHOLD = float(
        _env("TOPIC_LEXICAL_REOPEN_THRESHOLD", "0.33"))
    # 短于此字数的消息不参与切话题判定（"好的"/"打印"这类没有信息量）
    TOPIC_LEXICAL_MIN_CHARS = int(_env("TOPIC_LEXICAL_MIN_CHARS", "6"))

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
    # 主模型对话历史裁剪上限（非 system 消息保留条数）；0 = 不裁剪
    MODEL_MAX_HISTORY = max(0, int(_env("MODEL_MAX_HISTORY", "12")))
    # 客户端未携带 chat_id 时，自动续接该用户最近一个聊天，而不是新建聊天
    CHAT_RESUME_LATEST = _env("CHAT_RESUME_LATEST", "true").lower() in ("true", "1", "yes", "on")

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

    # ── ASR 资源托管（infra 资源池）──
    # 与 TTS 同构：资源调度全交给 infra.resources.ResourcePool，这里只提供参数。
    # ASR_AUTOSTART=true  → 托管模式：资源池按 LaunchSpec 拉起 sidecar（conda 环境）。
    # ASR_AUTOSTART=false → adopt 模式：只接入既有服务，绝不拉起也绝不杀进程。
    # FunASR 依赖（torch/funasr）只在 conda 环境里有，因此默认走 conda 模式。
    ASR_AUTOSTART = _env("ASR_AUTOSTART", "true").lower() == "true"
    ASR_PORT = max(1, int(_env("ASR_PORT", "9881")))
    ASR_BASE_URL = _env("ASR_BASE_URL", "http://127.0.0.1:9881")
    # sidecar 脚本所在目录与入口文件名（默认与本文件同目录）
    ASR_SERVER_DIR = _env("ASR_SERVER_DIR", str(Path(__file__).resolve().parent))
    ASR_SERVER_ENTRY = _env("ASR_SERVER_ENTRY", "asr_server.py")
    # 启动策略：conda（默认，funasr/torch 只在独立 conda 环境里）/ command
    ASR_LAUNCH_MODE = _env("ASR_LAUNCH_MODE", "conda")
    ASR_CONDA_ENV = _env("ASR_CONDA_ENV", "GPTSoVits")
    ASR_CONDA_EXE = _env("ASR_CONDA_EXE", "/home/darkstar/anaconda3/bin/conda")
    ASR_CONDA_NO_CAPTURE = _env("ASR_CONDA_NO_CAPTURE", "true").lower() == "true"
    # command 模式下的解释器（留空 = 当前解释器）
    ASR_PYTHON = _env("ASR_PYTHON", "")
    # 启动前预检（入口脚本存在 / conda 环境存在），失败时给出可操作的中文错误
    ASR_PREFLIGHT = _env("ASR_PREFLIGHT", "true").lower() == "true"
    # 资源池为 ASR 预留的加载超时（FunASR 权重加载是分钟级）
    ASR_LOAD_TIMEOUT = int(_env("ASR_LOAD_TIMEOUT", "600"))
    # 单次识别请求超时
    ASR_REQUEST_TIMEOUT = float(_env("ASR_REQUEST_TIMEOUT", "180"))
    # 启动后后台预热（拉起 sidecar 并加载模型）。默认关闭：加载耗时且占显存，
    # 交给运维显式预热或首次识别时按需拉起更稳妥。
    ASR_WARMUP = _env("ASR_WARMUP", "false").lower() == "true"

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

    # ── 语音轮回复长度 ──
    # 语音播报耗时 ≈ 1.3s + 0.045s/字，所以语音轮历史上强制「只回一到两句、
    # 不超过 40 字」。代价是**主AI 在语音场景里只能短回复** —— 讲题讲不开、
    # 展开推导被压成一句话。
    # 现在默认**不限制**（要完整回答就让它写全）；只有在明确要「快答」
    # 的场景（对讲机随手一问）才把开关打开。
    VOICE_SHORT_REPLY = _env_bool("VOICE_SHORT_REPLY", "false")

    # ── TTS 文本预处理 ──
    TTS_PROCESS_ENABLED = _env("TTS_PROCESS_ENABLED", "true").lower() == "true"
    TTS_PROCESS_MODEL = _env("TTS_PROCESS_MODEL", None) or _env("MEMORY_MODEL", "google/gemma-3-4b")
    TTS_PROCESS_MAX_TOKENS = int(_env("TTS_PROCESS_MAX_TOKENS", "1024"))
    TTS_PROCESS_TEMPERATURE = float(_env("TTS_PROCESS_TEMPERATURE", "0.2"))
    TTS_PROCESS_TIMEOUT = int(_env("TTS_PROCESS_TIMEOUT", "30"))

    # ── TTS 资源托管（infra 资源池）──
    # 资源调度全部交给 infra.resources.ResourcePool；这里只提供参数。
    # TTS_AUTOSTART=true  → 托管模式：资源池负责拉起/停止 GPT-SoVITS 服务。
    # TTS_AUTOSTART=false → adopt 模式：只接入既有服务，绝不拉起也绝不杀进程。
    TTS_AUTOSTART = _env("TTS_AUTOSTART", "true").lower() == "true"
    TTS_PORT = max(1, int(_env("TTS_PORT", "9880")))
    TTS_DEVICE = _env("TTS_DEVICE", "cuda")
    # 只用于 CUDA_VISIBLE_DEVICES 的物理卡号（"0"）；留空 = 不限制。切勿填 "cuda"。
    TTS_GPU_ID = _env("TTS_GPU_ID", "")
    TTS_SERVER_DIR = _env("TTS_SERVER_DIR", "/home/darkstar/TTS")
    TTS_SERVER_ENTRY = _env("TTS_SERVER_ENTRY", "api.py")
    # 启动策略：conda（默认，GPT-SoVITS 依赖在独立 conda 环境里）/ command
    TTS_LAUNCH_MODE = _env("TTS_LAUNCH_MODE", "conda")
    TTS_CONDA_ENV = _env("TTS_CONDA_ENV", "GPTSoVits")
    TTS_CONDA_EXE = _env("TTS_CONDA_EXE", "/home/darkstar/anaconda3/bin/conda")
    TTS_CONDA_NO_CAPTURE = _env("TTS_CONDA_NO_CAPTURE", "true").lower() == "true"
    # command 模式下的解释器（留空 = 当前解释器）
    TTS_PYTHON = _env("TTS_PYTHON", "")
    # 启动前预检（入口脚本存在 / conda 环境存在），失败时给出可操作的中文错误
    TTS_PREFLIGHT = _env("TTS_PREFLIGHT", "true").lower() == "true"
    # 服务就绪判定：GPT-SoVITS 的 GET / 缺参数时合法返回 400，故放宽为 <500
    TTS_READY_ACCEPT_BELOW = int(_env("TTS_READY_ACCEPT_BELOW", "500"))
    # 资源池为 TTS 预留的加载超时（GPT+SoVITS 权重加载是分钟级）
    TTS_LOAD_TIMEOUT = int(_env("TTS_LOAD_TIMEOUT", "600"))
    TTS_MAX_CONCURRENT = max(1, int(_env("TTS_MAX_CONCURRENT", "1")))
    # 单次合成请求超时
    TTS_REQUEST_TIMEOUT = float(_env("TTS_REQUEST_TIMEOUT", "180"))
    # 音色 profile
    TTS_PROFILE_DIR = _env("TTS_PROFILE_DIR", "")
    TTS_PROFILE_NAME = _env("TTS_PROFILE_NAME", "")
    # 启动后后台预热（拉起 TTS 服务）。默认关闭：GPT-SoVITS 加载权重需
    # 分钟级并占用显存，交给运维显式预热或首次合成时按需拉起更稳妥。
    TTS_WARMUP = _env("TTS_WARMUP", "false").lower() == "true"

    # ── 语音计算资源空闲自动关闭 ──
    # TTS/ASR 是重量级常驻进程（合计约 3.8GB 显存），挂进 infra 资源池后
    # resident=True 意味着**永远不会被调度器驱逐** —— 不配这项，显存就一直占着。
    # 启用后：闲置超过阈值 → 资源池停掉服务释放显存；下次有请求时由调度器
    # 重新拉起（首次请求需等待模型加载，属预期代价）。
    #
    # 注意：本开关只对**托管模式**（池自己拉起/停掉进程）生效。
    # adopt 模式（只接入外部服务）池没有停服能力，回收无从谈起。
    VOICE_IDLE_SHUTDOWN = _env("VOICE_IDLE_SHUTDOWN", "false").lower() == "true"
    # 池级空闲回收总开关（覆盖语音 + 视觉）。留空则跟随 VOICE_IDLE_SHUTDOWN，
    # 详见模块级函数 resource_idle_shutdown_enabled()。
    # RESOURCE_IDLE_SHUTDOWN=true
    # 统一空闲阈值（秒），默认 3600 = 1 小时
    VOICE_IDLE_TIMEOUT = max(0, int(_env("VOICE_IDLE_TIMEOUT", "3600")))
    # 单资源覆盖：留空跟随统一值；显式设为 0 表示该资源不参与空闲回收
    TTS_IDLE_TIMEOUT = int(_env("TTS_IDLE_TIMEOUT", "") or VOICE_IDLE_TIMEOUT)
    ASR_IDLE_TIMEOUT = int(_env("ASR_IDLE_TIMEOUT", "") or VOICE_IDLE_TIMEOUT)
    # 后台检查周期（秒）：太小徒增 CPU 占用，太大则回收时机不准
    VOICE_IDLE_CHECK_INTERVAL = max(5, int(_env("VOICE_IDLE_CHECK_INTERVAL", "60")))
    # 池拉起 ASR sidecar 后是否自动预热模型（把模型加载进显存）。
    # ASR 模型是**懒加载**的（首次识别才加载），不预热则冷启动后首个请求很慢。
    # 原先由 systemd 单元的 ExecStartPost 负责，改为池托管后需在此显式补上。
    ASR_WARMUP_ON_LOAD = _env("ASR_WARMUP_ON_LOAD", "true").lower() == "true"

    # ═══════════════════════════════════════════════════════════════════════
    # 第六层: 视觉系统
    # ═══════════════════════════════════════════════════════════════════════

    # ── 视觉模型（GLM-4.6V / GPT-4V 等）──
    VISION_ENABLED = _env("VISION_ENABLED", "true").lower() == "true"
    VISION_PROMPT = _env("VISION_PROMPT", "请详细描述这张图片的内容")
    VISION_API_KEY = _env("VISION_API_KEY", "")
    VISION_API_BASE = _env("VISION_API_BASE", "https://open.bigmodel.cn/api/paas/v4")
    VISION_MODEL_NAME = _env("VISION_MODEL_NAME", "glm-4.6v")
    # 本地视觉兜底端点的模型名（LM Studio 等）。
    # **绝不复用 MAIN_MODEL_NAME** —— 主模型常是纯文本模型，
    # 把 image_url 发给它会得到幻觉描述而不是报错。
    # 留空 = 不启用本地兜底，未配 VISION_API_KEY 时视觉功能明确报错。
    VISION_FALLBACK_MODEL_NAME = _env("VISION_FALLBACK_MODEL_NAME", "")

    # ── 人格系统（harness/personality PEV3）──
    # 角色卡目录必须指向 dsn_study 自己的（harness 的默认查找会落到
    # apps/dsn/character_cards —— 那是 dsn 的 EXA「AI 同事」卡）。
    PERSONALITY_ENABLED = _env("PERSONALITY_ENABLED", "true").lower() == "true"
    PERSONALITY_DEFAULT_CARD = _env("PERSONALITY_DEFAULT_CARD", "study_tutor.yaml")
    VISION_OVERRIDE = _env("VISION_OVERRIDE", "false").lower() == "true"
    # 启动时预热 VLM（后台发一次低 token dummy 请求，摊薄首次 look_around 冷启动）
    VISION_WARMUP = _env("VISION_WARMUP", "true").lower() == "true"
    # look_around 短时去重窗口（秒）：窗口内同 focus+camera 的重复观察直接复用上次结果
    VISION_LOOK_AROUND_DEDUP = float(_env("VISION_LOOK_AROUND_DEDUP", "10"))
    # 按需视觉请求的等待超时（秒）：look_around 阻塞等待客户端回帧的上限，
    # 过期请求在其 +10s 缓冲内即被 GC（不复制 dsn 的 120s 僵尸滞留）
    VISION_REQUEST_TIMEOUT = float(_env("VISION_REQUEST_TIMEOUT", "8"))
    # 实时流推送：无人订阅时是否仍下发 streams 推送配置（study 默认关，
    # 心跳里有订阅者时自动视为开）
    VISION_STREAMS_ENABLED = _env_bool("VISION_STREAMS_ENABLED", "false")

    # ── OCR ──
    OCR_MODEL = _env("OCR_MODEL", "deepseek-ocr")
    OCR_BASE_URL = _env("OCR_BASE_URL", "http://localhost:4502")
    OCR_UNLOAD_AFTER_USE = _env("OCR_UNLOAD_AFTER_USE", "true").lower() == "true"

    # ── 本地 VLM（入库 OCR 用）──
    #
    # 入库的整卷 OCR 走**本地** Bonsai llama-server（ternary 27B + mmproj），
    # 不再调用云端视觉模型。它挂在 infra 资源池上，与 ASR/TTS 同一套生命周期：
    #   按需拉起（第一次 OCR 时才启动）→ 租约保活 → 空闲超时自动回收显存。
    #
    # 端口刻意**不与 LMSTUDIO_BASE_URL（4501）重合**：那个端口在 .env 里是给
    # Instant 模式的小模型用的，两者撞端口会让「以为在调 Instant 模型，
    # 实际打到另一个服务」的错配无从排查。
    VLM_ENABLED = _env("VLM_ENABLED", "true").lower() == "true"
    # AUTOSTART=true → 池托管：需要时由池拉起子进程，用完按空闲阈值回收；
    # AUTOSTART=false → adopt 模式：只接入已在跑的同一个服务，绝不拉起/杀进程。
    VLM_AUTOSTART = _env("VLM_AUTOSTART", "true").lower() == "true"
    VLM_HOST = _env("VLM_HOST", "127.0.0.1")
    VLM_PORT = int(_env("VLM_PORT", "4503"))
    # OpenAI 兼容端点（llama-server 的 /v1 前缀）
    VLM_BASE_URL = _env("VLM_BASE_URL", "") or f"http://{VLM_HOST}:{VLM_PORT}/v1"
    # 请求里的 model 字段：llama-server 不校验它，填个可读的名字即可
    VLM_MODEL_NAME = _env("VLM_MODEL_NAME", "bonsai2-27b")
    # Bonsai 资源根目录（留空用默认 ~/Bonsai-demo）
    VLM_DEMO_DIR = _env("VLM_DEMO_DIR", "")
    # 主模型 / 视觉投影器：留空 = 自动扫描（优先带 mmproj 的最大模型）
    VLM_MODEL_PATH = _env("VLM_MODEL_PATH", "")
    VLM_MMPROJ_PATH = _env("VLM_MMPROJ_PATH", "")
    # 推理参数
    VLM_CTX_SIZE = int(_env("VLM_CTX_SIZE", "8192"))
    VLM_NGL = int(_env("VLM_NGL", "99"))
    VLM_THREADS = int(_env("VLM_THREADS", "8"))
    # 冷启动要加载 7.2GB 主模型 + 629MB 投影器，留足时间
    VLM_LOAD_TIMEOUT = int(_env("VLM_LOAD_TIMEOUT", "900"))
    # 单次请求超时（OCR 一页物理卷约 30~60s，留足余量）
    VLM_REQUEST_TIMEOUT = int(_env("VLM_REQUEST_TIMEOUT", "600"))
    # 空闲多久（秒）后自动停掉释放显存（27B 占约 12GB，值得回收）
    VLM_IDLE_TIMEOUT = int(_env("VLM_IDLE_TIMEOUT", "900"))
    # VLM 是否参与空闲回收（受池级总开关 resource_idle_shutdown_enabled 约束）
    VLM_IDLE_SHUTDOWN = _env_bool("VLM_IDLE_SHUTDOWN", "true")
    # 显存占用预估（MB），仅用于状态展示
    VLM_VRAM_ESTIMATE_MB = int(_env("VLM_VRAM_ESTIMATE_MB", "12000"))
    # 服务日志落盘位置（空 = 不落盘）
    VLM_LOG_FILE = _env("VLM_LOG_FILE", "") or ".dsn/logs/vlm_server.log"

    TWO_MD_API = _env("TWO_MD_API", "http://localhost:8000")

    # ── 摄像头 ──
    CAMERA_ENABLED = _env("CAMERA_ENABLED", "true").lower() == "true"
    CAMERA_DEVICE_ID = int(_env("CAMERA_DEVICE_ID", "0"))

    # ── 远程摄像头 (webcam infra) ──
    # 注册表持久化路径；经 /webcam 命令或 REST API 添加的远程摄像头保存在这里。
    WEBCAM_CONFIG_PATH = _env("WEBCAM_CONFIG_PATH", ".dsn/webcams.json")
    # 打开流超时（秒）：cv2 打开 RTSP/HTTP 流可能阻塞，超时即放弃
    WEBCAM_OPEN_TIMEOUT = float(_env("WEBCAM_OPEN_TIMEOUT", "5"))
    # 单帧抓取超时（秒）
    WEBCAM_FRAME_TIMEOUT = float(_env("WEBCAM_FRAME_TIMEOUT", "8"))
    # 多台 webcam 并发抓帧的线程上限
    WEBCAM_MAX_FRAMES = int(_env("WEBCAM_MAX_FRAMES", "4"))
    # 本地摄像头实时监控流的推送间隔（秒）：webUI 有本地流订阅时
    # 心跳下发该值，minimal.py StreamPusher 按此周期抓帧推送到后端
    STREAM_LOCAL_INTERVAL = float(_env("STREAM_LOCAL_INTERVAL", "2.0"))

    # ── 主动视觉感知 ──
    ACTIVE_VISION_ENABLED = _env("ACTIVE_VISION_ENABLED", "false").lower() == "true"
    ACTIVE_VISION_INTERVAL = int(_env("ACTIVE_VISION_INTERVAL", "300"))
    ACTIVE_VISION_CAMERA = _env("ACTIVE_VISION_CAMERA", "")   # 周期观察用哪台摄像头(逻辑名), 空=主摄像头
    ACTIVE_VISION_PROACTIVE_COOLDOWN = int(_env("ACTIVE_VISION_PROACTIVE_COOLDOWN", "600"))
    ACTIVE_VISION_PERIODIC_NOTIFY_MIN = int(_env("ACTIVE_VISION_PERIODIC_NOTIFY_MIN", "30"))

    # ── 闲置时感知 (idle-time sensing) ──
    # 主开关：客户端在未按 Enter 录音时持续监听麦克风，感知到响动就捕捉并上报后端 ASR 存档。
    SENSING_ENABLED = _env_bool("SENSING_ENABLED", "false")
    # 同一客户端两次上报之间的最小间隔（秒），服务端/客户端都会用它节流。
    SENSING_COOLDOWN = max(1, int(_env("SENSING_COOLDOWN", "60")))
    # 单条感知片段的最大时长（秒）。
    SENSING_MAX_RECORD_SECS = max(1.0, float(_env("SENSING_MAX_RECORD_SECS", "6.0")))
    # 允许 AI 通过工具查询闲置时感知记录（false 时工具返回未启用）。
    SENSING_AI_ACCESS_ENABLED = _env_bool("SENSING_AI_ACCESS_ENABLED", "false")

    # ── 用户跟踪系统 (tracking, infra) ──
    # 主开关：启用跟踪系统的聆听能力（闲时感知的音频部分依赖它）。
    TRACKING_ENABLED = _env_bool("TRACKING_ENABLED", "false")
    # 允许 AI 通过工具查询跟踪观察日志 / 建模结果（false 时工具返回未启用）。
    TRACKING_AI_ACCESS_ENABLED = _env_bool("TRACKING_AI_ACCESS_ENABLED", "false")
    # 拍照 / 录像（infra）媒体保存根目录。
    TRACKING_MEDIA_ROOT = _env("TRACKING_MEDIA_ROOT", ".dsn/tracking_media")
    # 独立加密数据库路径；为空则放在 <TRACKING_MEDIA_ROOT>/../tracking/tracking.db。
    TRACKING_DB_PATH = _env("TRACKING_DB_PATH", "")
    # 闲时感知音频是否同时把真实 WAV 存入用户媒体库（完整日记；关则只存识别文本）。
    TRACKING_SAVE_AUDIO = _env_bool("TRACKING_SAVE_AUDIO", "true")

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

    # ── 记忆系统（MEMORY_ENABLED=false 或未配模型时全部静默降级） ──
    MEMORY_ENABLED = _env("MEMORY_ENABLED", "true").lower() == "true"
    MEMORY_SUMMARY_LENGTH = int(_env("MEMORY_SUMMARY_LENGTH", "100"))
    MEMORY_CONTEXT_WINDOW_SIZE = int(_env("MEMORY_CONTEXT_WINDOW_SIZE", "80"))
    MEMORY_REPLACE_THRESHOLD_RATIO = float(_env("MEMORY_REPLACE_THRESHOLD_RATIO", "0.7"))
    MEMORY_ASYNC_ENABLED = _env("MEMORY_ASYNC_ENABLED", "true").lower() == "true"
    MEMORY_SEARCH_THRESHOLD = min(1.0, max(0.0, float(_env("MEMORY_SEARCH_THRESHOLD", "0.5"))))
    MEMORY_DETAIL_CHARS_PER_ROUND = max(1, int(_env("MEMORY_DETAIL_CHARS_PER_ROUND", "4000")))
    MEMORY_TOTAL_DETAIL_CHARS = max(1, int(_env("MEMORY_TOTAL_DETAIL_CHARS", "16000")))
    MEMORY_EMBEDDING_ENABLED = _env("MEMORY_EMBEDDING_ENABLED", "false").lower() == "true"
    MEMORY_EMBEDDING_BASE_URL = _env("MEMORY_EMBEDDING_BASE_URL", "")   # 空 = OPENAI_API_BASE
    # 嵌入服务独立密钥：本地 LMStudio 不需要；远程端点按需单独配
    MEMORY_EMBEDDING_API_KEY = _env("MEMORY_EMBEDDING_API_KEY", "")
    MEMORY_EMBEDDING_MODEL = _env("MEMORY_EMBEDDING_MODEL", "text-embedding-nomic-embed-text-v1.5@f16")
    MEMORY_EMBEDDING_WEIGHT = float(_env("MEMORY_EMBEDDING_WEIGHT", "0.6"))
    TOPIC_ENABLED = _env("TOPIC_ENABLED", "false").lower() == "true"   # 话题系统休眠

    # ── 语义缓存（拦截重复贵请求；需 MEMORY_EMBEDDING_ENABLED 才有 L2/语义命中） ──

    # ── Agent 循环 ──
    # AGENT_MAX_STEPS: 0 = 不限制自主执行轮数（由模型自己决定何时收尾）；
    # >0 = 硬上限，超过即触发收束轮。墙钟预算 AGENT_MAX_SECONDS 是不限轮数时的兜底。
    AGENT_MAX_STEPS = max(0, int(_env("AGENT_MAX_STEPS", "0")))
    AGENT_MAX_SECONDS = max(0.0, float(_env("AGENT_MAX_SECONDS", "1800")))
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

    # ── 外部 MCP（Obsidian 知识库 / 笔记）──
    # MCP_ENABLED=false 时完全跳过 MCP 连接（不影响其余功能）。
    MCP_ENABLED = _env("MCP_ENABLED", "true").lower() == "true"
    MCP_CONFIG_PATH = _env(
        "MCP_CONFIG_PATH",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_servers.yaml"))
    # Obsidian vault 绝对路径（必须含 .obsidian 目录）；经 OBSIDIAN_VAULT_PATH
    # 环境变量注入 MCP 配置，避免把路径写死在 yaml 里。
    OBSIDIAN_VAULT_PATH = _env(
        "OBSIDIAN_VAULT_PATH", "/home/darkstar/dsn_workspace/library/library")
    # vault 在 MCP 侧的短名（AI 调用工具时要传）
    OBSIDIAN_VAULT_ID = _env("OBSIDIAN_VAULT_ID", "study")
    # 知识点索引笔记的目录（相对 vault 根）
    OBSIDIAN_KP_FOLDER = _env("OBSIDIAN_KP_FOLDER", "知识点库")
    # 学习笔记目录
    OBSIDIAN_NOTE_FOLDER = _env("OBSIDIAN_NOTE_FOLDER", "学习笔记")
    # 暴露侧 MCP（FEATURE_GAP 阶段 6）：把学习技能工具经 stdio MCP 暴露给外部
    # Agent（apps/dsn_study/mcp_server.py）。MCP_EXPOSE_ENABLED=false 时不启动。
    MCP_EXPOSE_ENABLED = _env_bool("MCP_EXPOSE_ENABLED", "true")
    # MCP 工具名上限（MCP 规范建议 ≤64，且仅限字母/数字/下划线/连字符）
    MCP_EXPOSE_TOOL_NAME_MAX = 64

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
        """加载 skills/*/skill.env，让技能能声明自己的环境配置。

        注意（2026-11）：**这个方法在本应用里此前从未被调用过** ——
        写了 skill.env 也是静默失效的。现加载链路已统一到
        harness/skills/env_loader.py（由 SkillManager 在扫描时调用，
        值写进 os.environ，并挂到 Skill.env）。
        本方法保留用于"把技能私有配置也挂成 Config 属性"的场景，
        技能侧推荐直接读 os.environ。
        """
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
