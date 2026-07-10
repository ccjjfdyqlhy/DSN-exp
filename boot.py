
# DSN-exp/boot.py
# 系统启动引导 — 初始化所有组件，供 app.py 和 main.py 使用

import os
import time
import base64
import json
import re
import logging
import threading
import queue
from logging.handlers import RotatingFileHandler
from datetime import datetime

from flask import Flask
from config import Config
from api.auth import init_usermgr
from api.todo import todo_bp
from api.reminder import reminder_bp, init_reminder_api
from api.plan import plan_bp, init_plan_api
from api.heartbeat import heartbeat_bp, init_heartbeat_api
from api.alarm import alarm_bp, init_alarm_api
from db.plan_store import set_plan_db
from db.chat import ChatDBManager
from db.question_bank import QuestionBankDBManager
from models import OpenAIChat, LMSummaryModel, LMStudioChat, EmbeddingClient
from models import _load_lmstudio_model, _unload_lmstudio_model
from memory import MemorySystem
from tasks import TaskManager, TaskType
from utils.workspace import init_workspace_manager
import prompt

import sys
sys.path.insert(0, os.path.dirname(__file__))
from audio.infer import VocalExp
from plugins.builtin.tts_profile import TTSProfileManager
from utils.text_clean import clean_tts_text

# ── 模块级全局变量 ──
app: Flask = None
db: ChatDBManager = None
engine = None
task_manager = None
memory_system = None
summary_model = None
tts_client = None
tts_profile_mgr = None
personality_v3 = None
maint_system = None
_tts_process_model = None
_tts_available = True
filter_model = None
asr_model = None
prompt_engine = None
_impression_manager = None
skill_registry = None
skill_manager = None
script_engine = None
script_plugin = None
completion_queue: queue.Queue = None
_auth_manager = None

# ── 辅助函数 ──

def create_chat_client(model_type: str = None):
    if model_type is None:
        model_type = app.config.get("MAIN_MODEL_TYPE", "openai")
    if model_type in ("fast", "lmstudio"):
        return LMStudioChat(
            base_url=app.config.get("LMSTUDIO_BASE_URL", "http://localhost:4501"),
            model_name=app.config.get("MAIN_MODEL_NAME"),
            temperature=app.config.get("LMSTUDIO_TEMPERATURE", 0.7),
            max_tokens=app.config.get("LMSTUDIO_MAX_TOKENS", 4096),
            timeout=app.config.get("LMSTUDIO_TIMEOUT", 300),
        )
    return OpenAIChat(
        api_key=app.config["OPENAI_API_KEY"],
        model=app.config.get("MAIN_MODEL_NAME", "deepseek-v4-flash"),
        api_url=app.config.get("OPENAI_API_BASE")
    )


def _process_image_input(message: str, image_data: str) -> str:
    if not image_data:
        return message
    data_url = image_data if image_data.startswith("data:") else f"data:image/png;base64,{image_data}"
    try:
        vision_chat = LMStudioChat(
            base_url=app.config.get("LMSTUDIO_BASE_URL", "http://localhost:4501"),
            model_name=app.config.get("MEMORY_MODEL", "gemma-4-12b-it"),
            temperature=0.1, max_tokens=500,
            timeout=app.config.get("LMSTUDIO_TIMEOUT", 300),
        )
        vision_prompt = app.config.get("VISION_PROMPT", "请详细描述这张图片的内容")
        description = vision_chat.describe_image(data_url, vision_prompt)
        return f"[图片描述: {description}]\n{message}"
    except Exception as e:
        return f"[无法识别图片: {e}]\n{message}"


def _save_debug_audio(audio_bytes: bytes):
    _dir = os.path.join(os.path.dirname(__file__), "logs", "asr_history")
    os.makedirs(_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = os.path.join(_dir, f"{ts}.webm")
    with open(path, "wb") as f:
        f.write(audio_bytes)
    app.logger.debug("DEBUG_ASR: 音频已保存 → %s (%d bytes)", path, len(audio_bytes))


def _convert_audio_to_wav(audio_bytes: bytes) -> bytes:
    import subprocess
    import shutil
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return audio_bytes
    try:
        proc = subprocess.run(
            [ffmpeg, "-y", "-i", "pipe:0", "-f", "wav", "-acodec", "pcm_s16le",
             "-ar", "16000", "-ac", "1", "pipe:1"],
            input=audio_bytes, capture_output=True, timeout=15,
        )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout
        return audio_bytes
    except Exception:
        return audio_bytes


def _synthesize_tts_lines(text: str) -> list[dict]:
    global _tts_available
    if not text or not _tts_available:
        return []
    cleaned = clean_tts_text(text)
    if not cleaned:
        return []
    lines = [l.strip() for l in cleaned.split("\n") if l.strip()
             and any(c.isalpha() or "\u4e00" <= c <= "\u9fff" for c in l.strip())]
    if not lines:
        return []
    results = []
    for i, line in enumerate(lines):
        try:
            processed = _tts_process_model.process_tts_text(line) if _tts_process_model else line
            params = tts_profile_mgr.build_params(processed)
            audio_data = tts_client.tts(**params)
            results.append({"index": i, "total": len(lines), "text": line,
                            "audio_b64": base64.b64encode(audio_data).decode("utf-8")})
        except Exception as e:
            app.logger.warning("TTS 行 %d/%d 失败: %s", i + 1, len(lines), e)
            results.append({"index": i, "total": len(lines), "text": line, "audio_b64": None})
    return results


def setup_logging(_app):
    log_dir = _app.config["LOG_DIR"]
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".log")
    file_handler = RotatingFileHandler(log_path, maxBytes=10*1024*1024, backupCount=30, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)
    root.addHandler(file_handler)
    root.addHandler(console_handler)
    root.setLevel(logging.INFO)
    root.propagate = False
    _app.logger.setLevel(logging.INFO)
    _app.logger.propagate = True
    logging.getLogger('werkzeug').setLevel(logging.INFO)
    logging.getLogger('werkzeug').propagate = True

    # 压制高频轮询端点的 werkzeug 日志
    class _NoiseFilter(logging.Filter):
        _NOISE_PATTERNS = ("/api/heartbeat", "/api/music/state", "/api/music/status")
        def filter(self, record: logging.LogRecord) -> bool:
            msg = record.getMessage()
            return not any(p in msg for p in self._NOISE_PATTERNS)
    logging.getLogger('werkzeug').addFilter(_NoiseFilter())

    _app.logger.info("日志系统初始化完成")


def process_task_completion():
    while True:
        try:
            task_id, result = completion_queue.get()
            if task_id is None:
                break
            global app, db, task_manager, engine
            # 如果有 AsyncTaskStore 关联到此 taskmgr_id，标记完成
            if engine and engine.async_task_store:
                reply = str(result) if result else "任务完成"
                if isinstance(result, dict):
                    reply = (result.get("reminder_text", "")
                             or result.get("output", "")
                             or result.get("conclusion", "")
                             or str(result))
                engine.async_task_store.complete_by_taskmgr_id(task_id, reply=reply)
            task = task_manager.get_task(task_id)
            if not task:
                continue
            if task.task_type in (TaskType.REMINDER, TaskType.HABIT, TaskType.COUNTDOWN,
                                  TaskType.DAILY_PLAN, TaskType.PERIODIC):
                _handle_reminder_completion(task, result)
            elif task.task_type == TaskType.REASONER:
                _handle_reasoner_completion(task, result)
            elif task.task_type == TaskType.ACTION:
                _handle_action_completion(task, result)
        except Exception as e:
            time.sleep(1)


def _handle_reminder_completion(task, result):
    """提醒任务到期：只写一条 system 消息到聊天历史。
    AI 回复 + TTS 的生成改由前端心跳接口 /api/heartbeat 触发，
    这样可以避免 SSE 单向通信导致后端无法主动通知前端的问题。
    task_notifications 表中的记录由 TaskManager._notify_task_completion 写入。
    """
    short_id = task.task_id[:8]
    text = result.get("reminder_text", "提醒时间到了！")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = f"[系统] ⏰ 提醒（ID: {short_id}）\n现在是 {now}，你之前设置的提醒：{text}"
    try:
        db.append_messages(task.user_id, task.chat_id, [{"role": "system", "content": msg}])
    except Exception:
        pass


def _handle_reasoner_completion(task, result):
    short_id = task.task_id[:8]
    conclusion = result.get("conclusion", "") or result.get("reasoning", "")[:2000]
    msg = f"[系统] 推理任务完成（ID: {short_id}）。\n结论: {conclusion}"
    try:
        db.append_messages(task.user_id, task.chat_id, [{"role": "system", "content": msg}])
    except Exception:
        pass


def _handle_action_completion(task, result, retry_depth=0):
    from tasks import TaskType as _tt
    short_id = task.task_id[:8]
    success = result.get("success", False)
    error = result.get("error", "")
    if success:
        output = result.get("output", "")
        if len(output) > 500:
            output = output[:500] + "\n...(截断)"
        msg = f"[系统] 动作任务完成（ID: {short_id}）\n{output}"
    elif retry_depth < 2 and error:
        new_id = task_manager.create_task(
            task_type=_tt.ACTION, user_id=task.user_id, chat_id=task.chat_id,
            params={"action_type": result.get("action_type", "shell"), "content": result.get("content", "")},
        )
        task_manager.execute_task(new_id)
        with task_manager._retry_lock:
            task_manager._retry_depths[new_id] = retry_depth + 1
        return
    else:
        msg = f"[系统] 动作任务执行失败（ID: {short_id}）\n{error[:500]}" if error else \
              f"[系统] 动作任务执行失败（ID: {short_id}）"
    try:
        db.append_messages(task.user_id, task.chat_id, [{"role": "system", "content": msg}])
    except Exception:
        pass


# ── 模型预加载 ──

def _preload_models(app):
    """
    启动时检查 LMStudio 已加载的模型，缺失的立即加载。
    嵌入模型不纳入编排槽；其他本地模型只注册，由 Scheduler 按需加载/驱逐。
    """
    logger = logging.getLogger("boot")
    from models.scheduler import ModelScheduler, _get_loaded_models
    scheduler = ModelScheduler.get_instance()

    base_url = Config.LMSTUDIO_BASE_URL
    model_load_timeout = Config.MODEL_LOAD_TIMEOUT

    # 查询当前已加载的模型
    loaded = _get_loaded_models(base_url)
    logger.info("模型预加载: LMStudio 当前已加载=%s", loaded)

    # ── 1) 必须驻留的小模型（先加载，让大模型最后加载时不被挤掉）──
    small_models = []

    # 词向量嵌入模型（小，约 500MB）
    emb_model = Config.MEMORY_EMBEDDING_MODEL
    if emb_model and Config.MEMORY_EMBEDDING_ENABLED:
        small_models.append(("embedding", emb_model, base_url))

    # ── 2) 需要注册到 scheduler 的大模型（最后加载，VRAM 紧张时挤掉小模型）──
    scheduler_models = []

    # TTS 预处理模型
    tts_model = Config.TTS_PROCESS_MODEL
    if tts_model and Config.TTS_PROCESS_ENABLED:
        scheduler_models.append(("TTS处理", tts_model, base_url))

    # 主对话模型（仅在 MAIN_MODEL_TYPE == "lmstudio" 时）
    if Config.MAIN_MODEL_TYPE == "lmstudio":
        main_model = Config.MAIN_MODEL_NAME
        if main_model:
            scheduler_models.append(("主对话", main_model, base_url))

    # 人格 / judge 模型
    persona_model = Config.PERSONALITY_MODEL_NAME
    persona_url = Config.PERSONALITY_MODEL_URL
    if persona_model and Config.PERSONALITY_V3_ENABLED:
        scheduler_models.append(("人格", persona_model, persona_url))

    # ── 先加载小模型 ──
    for label, model_name, url in small_models:
        if model_name in loaded:
            logger.info("模型预加载: %s (%s) 已加载", label, model_name)
        else:
            logger.info("模型预加载: 正在加载 %s (%s) ...", label, model_name)
            _load_lmstudio_model(url, model_name, label, timeout=model_load_timeout)
        scheduler.mark_preloaded(model_name)

    # 小模型加载后重新查询（可能被 LMStudio 的 VRAM 管理卸载了主模型）
    loaded = _get_loaded_models(base_url)

    # ── 注册大模型：不在启动阶段直接加载，避免绕过调度器占满 VRAM ──
    for label, model_name, url in scheduler_models:
        scheduler.register(
            model_name=model_name,
            base_url=url,
            load_fn=lambda mn=model_name, bu=url, lb=label:
                _load_lmstudio_model(bu, mn, lb, timeout=model_load_timeout),
            unload_fn=lambda mn=model_name, bu=url:
                _unload_lmstudio_model(bu, mn),
        )

        if model_name in loaded:
            logger.info("模型预加载: %s (%s) 已加载", label, model_name)
            scheduler.mark_preloaded(model_name)
        else:
            logger.info("模型预加载: %s (%s) 已注册，将按需加载", label, model_name)


# ── 启动计时器 ──

_t_start_total = 0.0
_t_prev_time = 0.0
_t_log: list[tuple[str, float]] = []


def _t(name: str, disabled: bool = False):
    global _t_start_total, _t_prev_time
    now = time.time()
    if not _t_log:
        _t_start_total = now
        _t_prev_time = now
        _t_log.append((name, -1.0 if disabled else 0.0))
    else:
        elapsed = now - _t_prev_time if not disabled else -1.0
        _t_prev_time = now
        _t_log.append((name, elapsed))
    return now


# ── 启动函数 ──

def create_application():
    """初始化所有组件并设置模块级全局变量"""
    global app, db, engine, task_manager, memory_system, summary_model
    global tts_client, tts_profile_mgr, personality_v3, maint_system
    global _tts_process_model, filter_model, asr_model, prompt_engine
    global _impression_manager, skill_registry, skill_manager
    global completion_queue, _auth_manager

    _t_log.clear()
    _t("start")

    app = Flask(__name__)
    app.config.from_object(Config)
    setup_logging(app)
    completion_queue = queue.Queue()

    # ── 认证 ──
    from auth import AuthManager, auth_bp
    _auth_manager = AuthManager(
        db=None, jwt_secret=Config.JWT_SECRET,
        session_days=Config.AUTH_SESSION_DAYS,
        pairing_digits=Config.AUTH_PAIRING_DIGITS,
        pairing_timeout=Config.AUTH_PAIRING_TIMEOUT,
    )
    app.config["AUTH_MANAGER"] = _auth_manager
    app.register_blueprint(auth_bp)
    init_usermgr(app)
    app.register_blueprint(todo_bp)
    app.register_blueprint(reminder_bp)
    app.register_blueprint(plan_bp)
    app.register_blueprint(heartbeat_bp)
    app.register_blueprint(alarm_bp)
    from api.async_tasks import async_task_bp
    app.register_blueprint(async_task_bp)
    from api.agent import agent_bp
    app.register_blueprint(agent_bp)
    from api.music import music_bp
    app.register_blueprint(music_bp)
    _t("认证 + 蓝图 + 数据库")

    # ── 数据库 ──
    db = ChatDBManager(db_path=app.config["DATABASE_PATH"])
    app.config["DB"] = db
    set_plan_db(db)
    _auth_manager.db = db
    if _auth_manager._user_count() == 0:
        print("  首次启动提示: 在服务器控制台输入 /newbind 生成配对码")

    # ── 工作区 ──
    init_workspace_manager(db=db, workspace_dir=Config.WORKSPACE_DIR)
    _t("工作区")

    # ── 任务管理器 ──
    _task_mgr_enabled = app.config.get("TASK_MANAGER_ENABLED", True)
    if _task_mgr_enabled:
        try:
            task_manager = TaskManager(db=db, max_workers=app.config.get("TASK_MAX_WORKERS", 5))
            task_manager.completion_queue = completion_queue
            init_reminder_api(db, task_manager, _auth_manager)
            init_alarm_api(db, _auth_manager)
            init_plan_api(db, _auth_manager)
            threading.Thread(target=process_task_completion, daemon=True).start()
        except Exception:
            task_manager = None
    _t("任务管理器", disabled=not _task_mgr_enabled)

    # ── 模型预加载（在记忆系统之前，避免 EmbeddingClient 加载时挤掉主模型）──
    _preload_models(app)
    _t("模型预加载")

    # ── 记忆与摘要 ──
    _memory_enabled = app.config.get("MEMORY_ENABLED", True)
    if _memory_enabled:
        summary_model = LMSummaryModel(
            backend=app.config.get("MEMORY_SUMMARY_BACKEND", "openai"),
            base_url=app.config.get("LMSTUDIO_BASE_URL"),
            model_name=app.config.get("MEMORY_MODEL"),
            summary_length=app.config.get("MEMORY_SUMMARY_LENGTH", 100),
        )
        memory_system = MemorySystem(db=db, summary_model=summary_model)
        if Config.MEMORY_EMBEDDING_ENABLED:
            try:
                memory_system = MemorySystem(
                    db=db, summary_model=summary_model,
                    embedding_client=EmbeddingClient(base_url=Config.LMSTUDIO_BASE_URL),
                )
            except Exception:
                pass
    _t("记忆与摘要", disabled=not _memory_enabled)

    # ── TTS ──
    tts_client = VocalExp(app.config["TTS_BASE_URL"])
    tts_profile_mgr = TTSProfileManager()

    # TTS 启动探测：等待服务就绪（最多重试3次，指数退避）
    tts_probe_ok = False
    for _tts_attempt in range(4):
        if tts_client.probe(timeout=3.0):
            tts_probe_ok = True
            app.logger.info("TTS 服务探测成功 (第 %d 次)", _tts_attempt + 1)
            break
        if _tts_attempt < 3:
            _tts_wait = min(2.0 * (2 ** _tts_attempt), 8.0)
            app.logger.warning("TTS 服务未就绪，%.1fs 后重试 (%d/3)...", _tts_wait, _tts_attempt + 1)
            time.sleep(_tts_wait)
    if not tts_probe_ok:
        app.logger.warning("TTS 服务 (端口 9880) 启动探测失败，TTS 功能可能不可用")

    if Config.TTS_PROCESS_ENABLED:
        try:
            from models.tts_process import TTSProcessModel
            _tts_process_model = TTSProcessModel()
        except Exception:
            _tts_process_model = None
    _t("TTS")

    # ── ASR ──
    filter_model = None
    if app.config.get("ASR_FILTER_ENABLED", True):
        try:
            from models.asr_filter import LMFilterModel
            filter_model = LMFilterModel()
        except Exception:
            pass
    asr_model = None
    if app.config.get("ASR_ENABLED", True):
        from funasr import AutoModel
        _asr_device = app.config.get("ASR_DEVICE", "cuda")
        _asr_gpu_id = app.config.get("ASR_GPU_ID", "")
        if _asr_gpu_id:
            _asr_device = f"cuda:{_asr_gpu_id}"
        asr_model = AutoModel(
            model="paraformer-zh", model_revision="v2.0.4",
            vad_model="fsmn-vad", vad_model_revision="v2.0.4",
            punc_model="ct-punc-c", punc_model_revision="v2.0.4",
            device=_asr_device,
            disable_update=True, disable_pbar=True,
        )
    _t("ASR")

    # ── Prompt ──
    _prompt_dir = os.path.join(os.path.dirname(__file__), "prompt", "prompts")
    prompt_engine = prompt.init_prompt_engine(
        library_dirs=[
            os.path.join(_prompt_dir, "core"),
            os.path.join(_prompt_dir, "capabilities"),
            os.path.join(_prompt_dir, "extensions"),
        ],
        personality_v2_dir=os.path.join(os.path.dirname(__file__), "prompt", "personality_v2", "presets"),
        db=db,
    )

    # ── 印象管理器 ──
    from prompt.impression import ImpressionManager
    _impression_manager = ImpressionManager(db=db)
    _t("Prompt + 印象")

    # ── 世界 ──
    _world_engine = _world_state_manager = _narrative_model = None
    if Config.WORLD_ENABLED:
        try:
            from world import WorldEngine, WorldStateManager
            wp = os.path.join(os.path.dirname(__file__), "world", "worlds", f"{Config.WORLD_PRESET}.yaml")
            _world_engine = WorldEngine()
            _world_engine.load_config_file(wp)
            _world_state_manager = WorldStateManager(_world_engine, Config.WORLD_UPDATE_INTERVAL)
            _world_state_manager.start()
            if Config.NARRATIVE_ENABLED:
                from world import NarrativeModel
                _narrative_model = NarrativeModel(
                    model_type=Config.NARRATIVE_MODEL_TYPE, model_name=Config.NARRATIVE_MODEL,
                    api_key=Config.OPENAI_API_KEY,
                    base_url=Config.LMSTUDIO_BASE_URL if Config.NARRATIVE_MODEL_TYPE == "lmstudio" else None,
                    temperature=Config.NARRATIVE_TEMPERATURE, max_tokens=Config.NARRATIVE_MAX_TOKENS,
                    keep_history=Config.NARRATIVE_KEEP_HISTORY,
                )
                _narrative_model.load_system_prompt_file(
                    os.path.join(os.path.dirname(__file__), "prompt", "world", "narrative.md"))
        except Exception:
            pass
    _t("世界", disabled=not Config.WORLD_ENABLED)

    # ── 技能系统 ──
    try:
        from skills.registry import SkillRegistry
        from skills.manager import SkillManager
        Config.load_skill_configs()
        skill_registry = SkillRegistry()
        skill_manager = SkillManager(
            skill_dirs=[os.path.join(os.path.dirname(__file__), "skills", "builtin"),
                        os.path.join(os.path.dirname(__file__), "skills", "custom"),
                        os.path.join(os.path.dirname(__file__), "skills", "system")],
            registry=skill_registry,
        )
        skill_manager.scan_and_load()
        prompt_engine.set_skill_registry(skill_registry)
    except Exception:
        pass
    _t("技能系统")

    # ── Phase 2: 学习系统 ──
    _question_store = _template_manager = _exam_composer = _error_analyzer = _scanner_pipeline = None
    _graph_store = _graph_engine = _knowledge_matcher = _graph_builder = None
    _exam_engine = _exam_scorer = None
    _qb_db = None
    try:
        from question_bank.template_manager import SubjectTemplateManager
        from question_bank.store import QuestionStore
        from question_bank.composer import ExamComposer
        from question_bank.error_analyzer import ErrorAnalyzer
        from question_bank.scanner_pipeline import ScannerPipeline
        from knowledge_graph.graph_store import GraphStore
        from knowledge_graph.graph_engine import GraphEngine
        from knowledge_graph.matcher import KnowledgeMatcher
        from knowledge_graph.builder import KnowledgeGraphBuilder
        from exam_sim.engine import ExamEngine
        from exam_sim.scorer import ExamScorer

        _qb_db = QuestionBankDBManager(db_path=app.config.get("QUESTION_BANK_DB_PATH"))
        app.logger.info("题库数据库: %s", _qb_db.db_path)

        _template_manager = SubjectTemplateManager(db=_qb_db)
        _template_manager.init_builtin_templates()

        if not _template_manager.has_subjects():
            _template_manager.apply_template("6_subjects")
            app.logger.info("学习系统: 首次启动，已应用默认模板 6_subjects")

        _question_store = QuestionStore(db=_qb_db)
        _exam_composer = ExamComposer(question_store=_question_store)
        _scanner_pipeline = ScannerPipeline(
            question_store=_question_store, models_plugin=None,
        )
        _error_analyzer = ErrorAnalyzer(question_store=_question_store, models_plugin=None)

        _graph_store = GraphStore(db=_qb_db)
        _graph_engine = GraphEngine(graph_store=_graph_store)
        _knowledge_matcher = KnowledgeMatcher(graph_store=_graph_store, models_plugin=None)
        _graph_builder = KnowledgeGraphBuilder(graph_store=_graph_store, models_plugin=None)

        _exam_scorer = ExamScorer(question_store=_question_store, models_plugin=None)
        _exam_engine = ExamEngine(db=_qb_db, question_store=_question_store, scorer=_exam_scorer)

        app.logger.info("学习系统: 题库+知识图+考试引擎初始化完成")
    except Exception as e:
        app.logger.warning("学习系统初始化失败: %s", e)
    _t("学习系统")

    # ── 人格系统 V3 ──
    if Config.PERSONALITY_V3_ENABLED:
        try:
            from prompt.personality_v3 import PersonalitySystemV3
            _v3_chat = create_chat_client("fast")
            if hasattr(_v3_chat, 'model_name'):
                _v3_chat.model_name = Config.PERSONALITY_MODEL_NAME
            personality_v3 = PersonalitySystemV3(
                db=db, personality_model_chat=_v3_chat,
                default_card_path=os.path.join(os.path.dirname(__file__), "character_cards", "exa.yaml"),
            )
            personality_v3.init_tables()
            if Config.DISTILLATION_MODEL == "lmstudio":
                _d = create_chat_client("fast")
                if hasattr(_d, 'model_name'):
                    _d.model_name = Config.PERSONALITY_MODEL_NAME
                personality_v3.set_distillation_model(fast_chat=_d)
            else:
                personality_v3.set_distillation_model(main_chat=create_chat_client("deep"))
            prompt_engine.personality_v3 = personality_v3
            if Config.PERSONALITY_V3_OVERRIDE_V2:
                prompt_engine.personality_v2 = None
        except Exception:
            pass
    _t("人格系统 V3", disabled=not Config.PERSONALITY_V3_ENABLED)

    # ── DSNEngine ──
    from engine import create_engine_with_defaults
    engine = create_engine_with_defaults(
        db=db, memory_system=memory_system,
        skill_registry=skill_registry, skill_manager=skill_manager,
        impression_manager=_impression_manager,
        tts_client=tts_client, filter_model=filter_model,
        world_engine=_world_engine, world_state_manager=_world_state_manager,
        narrative_model=_narrative_model,
        task_manager=task_manager, personality_v3=personality_v3,
        question_store=_question_store, template_manager=_template_manager,
        exam_composer=_exam_composer, error_analyzer=_error_analyzer,
        scanner_pipeline=_scanner_pipeline,
        graph_store=_graph_store, graph_engine=_graph_engine,
        knowledge_matcher=_knowledge_matcher, graph_builder=_graph_builder,
        exam_engine=_exam_engine, exam_scorer=_exam_scorer,
    )
    app.config["ENGINE"] = engine
    # 初始化心跳接口（需要 engine 来生成 AI 回复 + TTS）
    init_heartbeat_api(db, task_manager, _auth_manager, engine)
    _t("DSNEngine")

    # ── 语义缓存系统 (L1/L2/L3) ──
    cache_engine = None
    if Config.SEMANTIC_CACHE_ENABLED:
        try:
            from semantic_cache import CacheStore, L1PragmaticCache, CacheEngine
            from semantic_cache.l2 import L2Cache
            from semantic_cache.l3 import L3SlotRegistry

            _cache_dir = os.path.join(os.path.dirname(__file__),
                                      Config.SEMANTIC_CACHE_DIR)
            _cache_store = CacheStore(db=db, cache_dir=_cache_dir)
            _l1_cache = L1PragmaticCache(store=_cache_store)
            _l1_cache.init_builtin_phrases()

            _emb = None
            if Config.MEMORY_EMBEDDING_ENABLED:
                from models import EmbeddingClient
                _emb = EmbeddingClient()

            cache_engine = CacheEngine(
                store=_cache_store,
                l1_cache=_l1_cache,
                embedding_client=_emb,
                similarity_threshold=Config.SEMANTIC_CACHE_SIMILARITY_THRESHOLD,
            )

            from plugins.container import PluginDIContainer
            from plugins.loader import PluginLoader
            PluginDIContainer.register("cache_engine", cache_engine)
            PluginDIContainer.register("tts_client", tts_client)
            _cache_loader = PluginLoader(["plugins/builtin"])
            for m in _cache_loader.scan():
                if m.name == "cache_interceptor" and m.meets_condition():
                    plugin = _cache_loader.instantiate(m)
                    if plugin:
                        engine.plugin_manager.register(plugin)
            engine._cache_engine = cache_engine
            engine._l2_cache = cache_engine.l2
            engine._l3_registry = cache_engine.l3

            app.logger.info("语义缓存系统: 已启用 (L1/L2/L3, 阈值=%.2f)",
                            Config.SEMANTIC_CACHE_SIMILARITY_THRESHOLD)
        except Exception as e:
            app.logger.warning("语义缓存系统初始化失败: %s", e)
    _t("语义缓存系统", disabled=not Config.SEMANTIC_CACHE_ENABLED)

    # ── 剧本系统 ──
    script_engine = None
    script_plugin = None
    try:
        from scripts import ScriptEngine, ScriptState, OOCDetector
        from scripts import ScriptRecorder, ScriptPlayer
        _script_state = ScriptState(db)
        script_engine = ScriptEngine(state=_script_state)
        _scripts_dir = os.path.join(os.path.dirname(__file__), "scripts")
        script_engine.scan_scripts(
            os.path.join(_scripts_dir, "builtin"),
            os.path.join(_scripts_dir, "custom"),
        )
        _ooc = OOCDetector()
        _recorder = ScriptRecorder(state=_script_state)
        _player = ScriptPlayer(state=_script_state)
        # 通过 PluginLoader 自动注入 ScriptPlugin
        from plugins.loader import PluginLoader
        from plugins.container import PluginDIContainer
        PluginDIContainer.register("engine", script_engine)
        PluginDIContainer.register("ooc", _ooc)
        PluginDIContainer.register("recorder", _recorder)
        PluginDIContainer.register("player", _player)
        _script_loader = PluginLoader(["scripts"])
        for m in _script_loader.scan():
            if m.name == "script" and m.meets_condition():
                plugin = _script_loader.instantiate(m)
                if plugin:
                    engine.plugin_manager.register(plugin)
                    script_plugin = plugin
        engine._script_engine = script_engine
        engine._script_plugin = script_plugin
        app.logger.info("剧本系统初始化完成: %d 个剧本",
                        len(script_engine.list_scripts()))
    except Exception as e:
        app.logger.warning("剧本系统初始化失败: %s", e)
    _t("剧本系统")

    # ── 提示词缓存索引 ──
    try:
        from prompt.prompt_cache import PromptCache
        from models import EmbeddingClient
        
        embedding_client = None
        if Config.MEMORY_EMBEDDING_ENABLED:
            embedding_client = EmbeddingClient()
            app.logger.info("提示词缓存: 向量嵌入已启用")
        else:
            app.logger.info("提示词缓存: 向量嵌入未启用，仅使用关键词搜索")
        
        prompt_cache = PromptCache(db=db, embedding_client=embedding_client)
        engine.prompt_cache = prompt_cache
        
        # 为所有已有聊天索引提示词
        conn = db._get_connection()
        chats = conn.execute(
            "SELECT DISTINCT user_id, chat_id FROM chats"
        ).fetchall()
        
        indexed_count = 0
        for row in chats:
            uid = row["user_id"]
            cid = row["chat_id"]
            count = engine.index_prompts_for_chat(uid, cid)
            indexed_count += count
        
        app.logger.info("提示词缓存索引完成: %d 条提示词, %d 个聊天", indexed_count, len(chats))
    except Exception as e:
        app.logger.warning("提示词缓存索引失败: %s", e)
    _t("提示词缓存")

    # V3 注入到 personality_materials 技能
    try:
        if personality_v3 and skill_registry:
            for k, inst in skill_registry._tool_instances.items():
                if k.startswith("personality_materials."):
                    inst._v3 = personality_v3
    except Exception:
        pass

    # ── 维护模块 ──
    _maint_disabled = True
    try:
        from maintenance import config as maint_config
        _maint_disabled = not maint_config.MAINTENANCE_ENABLED
        if _maint_disabled:
            app.logger.info("维护模块已禁用 (MAINTENANCE_ENABLED=false)")
            app.config["MAINTENANCE_SYSTEM"] = None
        else:
            from maintenance import MaintenanceSystem
            from maintenance.api import maintenance_bp
            from maintenance.frontend_bridge import broadcast as mb
            maint_system = MaintenanceSystem(db=db, v3=personality_v3, engine=engine)
            maint_system.on_maintenance_start(lambda: app.logger.info("维护流程开始"))
            maint_system.on_maintenance_progress(
                lambda task, prog: mb("maintenance_progress", {
                    "task": task.name, "current": prog.current,
                    "total": prog.total, "message": prog.message,
                }))
            maint_system.on_maintenance_done(
                lambda results: mb("maintenance_complete", {
                    "results": results, "total": len(results),
                    "success": sum(1 for r in results if r.get("success")),
                }))
            maint_system.start()
            app.config["MAINTENANCE_SYSTEM"] = maint_system
            app.register_blueprint(maintenance_bp)
    except Exception:
        app.config["MAINTENANCE_SYSTEM"] = None
    _t("维护模块", disabled=_maint_disabled)

    # ── 打印启动耗时 ──
    app.logger.info("=" * 45)
    app.logger.info("  启动耗时汇总")
    app.logger.info("=" * 45)
    total = sum(el for _, el in _t_log if el > 0)
    for name, elapsed in _t_log:
        if elapsed == 0:
            continue
        if elapsed < 0:
            app.logger.info("  %-24s %s", name, "未加载")
        else:
            app.logger.info("  %-24s %7.2fs", name, elapsed)
    app.logger.info("  " + "-" * 31)
    app.logger.info("  %-24s %7.2fs", "总计", total)
    app.logger.info("=" * 45)

    return app
