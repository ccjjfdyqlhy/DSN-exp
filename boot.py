
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
from usermgr import init_usermgr
from todo_api import todo_bp
from reminder_api import reminder_bp, init_reminder_api
from plan_api import plan_bp, init_plan_api
from chatdbmgr import ChatDBManager
from models import DeepSeekChat, LMSummaryModel, LMStudioChat, EmbeddingClient
from tts_process_model import TTSProcessModel
from memory import MemorySystem
from tasks import TaskManager, TaskType
from workspace import init_workspace_manager
import prompt

import sys
sys.path.insert(0, os.path.dirname(__file__))
from vocal_infer import VocalExp
from plugins.builtin.tts_profile import TTSProfileManager
from ASR_filter import LMFilterModel
if Config.ASR_ENABLED:
    from funasr import AutoModel
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
completion_queue: queue.Queue = None
_auth_manager = None

# ── 辅助函数 ──

def create_chat_client(model_type: str = None):
    if model_type is None:
        model_type = app.config.get("MAIN_MODEL_TYPE", "deepseek")
    if model_type in ("fast", "lmstudio"):
        return LMStudioChat(
            base_url=app.config.get("LMSTUDIO_BASE_URL", "http://localhost:4501"),
            model_name=app.config.get("MAIN_MODEL_NAME"),
            temperature=app.config.get("LMSTUDIO_TEMPERATURE", 0.7),
            max_tokens=app.config.get("LMSTUDIO_MAX_TOKENS", 4096),
            timeout=app.config.get("LMSTUDIO_TIMEOUT", 300),
        )
    return DeepSeekChat(api_key=app.config["DEEPSEEK_API_KEY"])


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
    _app.logger.info("日志系统初始化完成")


def process_task_completion():
    while True:
        try:
            task_id, result = completion_queue.get()
            if task_id is None:
                break
            global app, db, task_manager
            task = task_manager.get_task(task_id)
            if not task:
                continue
            if task.task_type == TaskType.REMINDER:
                _handle_reminder_completion(task, result)
            elif task.task_type == TaskType.REASONER:
                _handle_reasoner_completion(task, result)
            elif task.task_type == TaskType.ACTION:
                _handle_action_completion(task, result)
        except Exception as e:
            time.sleep(1)


def _handle_reminder_completion(task, result):
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


# ── 启动计时器 ──

_t_start_total = 0.0
_t_prev_time = 0.0
_t_log: list[tuple[str, float]] = []


def _t(name: str):
    global _t_start_total, _t_prev_time
    now = time.time()
    if not _t_log:
        _t_start_total = now
        _t_prev_time = now
        _t_log.append((name, 0.0))
    else:
        elapsed = now - _t_prev_time
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
    _t("认证 + 蓝图 + 数据库")

    # ── 数据库 ──
    db = ChatDBManager(db_path=app.config["DATABASE_PATH"])
    _auth_manager.db = db
    if _auth_manager._user_count() == 0:
        print("  首次启动提示: 在服务器控制台输入 /newbind 生成配对码")

    # ── 工作区 ──
    init_workspace_manager(db=db, workspace_dir=Config.WORKSPACE_DIR)
    _t("工作区")

    # ── 任务管理器 ──
    if app.config.get("TASK_MANAGER_ENABLED", True):
        try:
            task_manager = TaskManager(db=db, max_workers=app.config.get("TASK_MAX_WORKERS", 5))
            task_manager.completion_queue = completion_queue
            init_reminder_api(db, task_manager, _auth_manager)
            init_plan_api(db, _auth_manager)
            threading.Thread(target=process_task_completion, daemon=True).start()
        except Exception:
            task_manager = None
    _t("任务管理器")

    # ── 记忆与摘要 ──
    if app.config.get("MEMORY_ENABLED", True):
        summary_model = LMSummaryModel(
            backend=app.config.get("MEMORY_SUMMARY_BACKEND", "deepseek"),
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
    _t("记忆与摘要")

    # ── TTS ──
    tts_client = VocalExp(app.config["TTS_BASE_URL"])
    tts_profile_mgr = TTSProfileManager()
    if Config.TTS_PROCESS_ENABLED:
        try:
            _tts_process_model = TTSProcessModel()
        except Exception:
            _tts_process_model = None
    _t("TTS")

    # ── ASR ──
    filter_model = LMFilterModel() if app.config.get("ASR_FILTER_ENABLED", True) else None
    asr_model = None
    if app.config.get("ASR_ENABLED", True):
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
            from world import WorldEngine, WorldStateManager, NarrativeModel
            wp = os.path.join(os.path.dirname(__file__), "world", "worlds", f"{Config.WORLD_PRESET}.yaml")
            _world_engine = WorldEngine()
            _world_engine.load_config_file(wp)
            _world_state_manager = WorldStateManager(_world_engine, Config.WORLD_UPDATE_INTERVAL)
            _world_state_manager.start()
            if Config.NARRATIVE_ENABLED:
                _narrative_model = NarrativeModel(
                    model_type=Config.NARRATIVE_MODEL_TYPE, model_name=Config.NARRATIVE_MODEL,
                    api_key=Config.DEEPSEEK_API_KEY,
                    base_url=Config.LMSTUDIO_BASE_URL if Config.NARRATIVE_MODEL_TYPE == "lmstudio" else None,
                    temperature=Config.NARRATIVE_TEMPERATURE, max_tokens=Config.NARRATIVE_MAX_TOKENS,
                    keep_history=Config.NARRATIVE_KEEP_HISTORY,
                )
                _narrative_model.load_system_prompt_file(
                    os.path.join(os.path.dirname(__file__), "prompt", "world", "narrative.md"))
        except Exception:
            pass
    _t("世界")

    # ── 技能系统 ──
    try:
        from skills.registry import SkillRegistry
        from skills.manager import SkillManager
        skill_registry = SkillRegistry()
        skill_manager = SkillManager(
            skill_dirs=[os.path.join(os.path.dirname(__file__), "skills", "builtin"),
                        os.path.join(os.path.dirname(__file__), "skills", "custom")],
            registry=skill_registry,
        )
        skill_manager.scan_and_load()
        prompt_engine.set_skill_registry(skill_registry)
    except Exception:
        pass
    _t("技能系统")

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
    _t("人格系统 V3")

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
    )
    _t("DSNEngine")

    # V3 注入到 personality_materials 技能
    try:
        if personality_v3 and skill_registry:
            for k, inst in skill_registry._tool_instances.items():
                if k.startswith("personality_materials."):
                    inst._v3 = personality_v3
    except Exception:
        pass

    # ── 维护模块 ──
    try:
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
    _t("维护模块")

    # ── 打印启动耗时 ──
    app.logger.info("=" * 45)
    app.logger.info("  启动耗时汇总")
    app.logger.info("=" * 45)
    total = sum(el for _, el in _t_log if el > 0)
    for name, elapsed in _t_log:
        if elapsed == 0:
            continue
        app.logger.info("  %-24s %7.2fs", name, elapsed)
    app.logger.info("  " + "-" * 31)
    app.logger.info("  %-24s %7.2fs", "总计", total)
    app.logger.info("=" * 45)

    return app
