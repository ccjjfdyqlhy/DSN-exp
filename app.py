
# DSN-exp/app.py
# UPD v4.2
# Core backend logics

import os
import time
import base64
import json
import re
import logging
import threading
import queue
from concurrent.futures import ThreadPoolExecutor
from logging.handlers import RotatingFileHandler
from datetime import datetime
from flask import Flask, request, jsonify, g
from functools import wraps

try:
    from config import Config
except ImportError:
    logging.warning("配置未初始化，请根据config.py.example创建config.py并配置相关参数")
    exit(1)

from usermgr import init_usermgr, auth_bp
from todo_api import todo_bp
from chatdbmgr import ChatDBManager
from models import DeepSeekChat, LMSummaryModel, LMStudioChat
from tts_process_model import TTSProcessModel
from memory import MemoryManager
from tasks import TaskManager, TaskType
import prompt

# 导入 TTS 模块
import sys
sys.path.insert(0, os.path.dirname(__file__))  # 确保 vocal_infer 可导入
from vocal_infer import VocalExp, TTSRequestError
from plugins.builtin.tts_profile import TTSProfileManager

# 导入 ASR 过滤模块
from ASR_filter import LMFilterModel

# 导入 ASR 依赖
from flask import Response, stream_with_context
if Config.ASR_ENABLED: # 启动的更快
    from funasr import AutoModel

# ---------- 全局变量 ----------
task_manager = None
completion_queue = queue.Queue()
_tts_available = True  # TTS 可用性标记，首次失败后置 False 避免刷屏
_tts_process_model = None  # TTS 文本预处理模型

# ---------- 模型工厂函数 ----------
def create_chat_client(model_type: str = None):
    """
    根据配置或参数创建聊天客户端实例。
    
    :param model_type: 模型类型，可选值: "fast"(本地LMStudio) 或 "deep"(DeepSeek)
                       如果为 None，则使用配置文件中的默认值
    :return: DeepSeekChat 或 LMStudioChat 实例
    """
    if model_type is None:
        model_type = app.config.get("MAIN_MODEL_TYPE", "deepseek")
    
    if model_type == "fast" or model_type == "lmstudio":
        return LMStudioChat(
            base_url=app.config.get("LMSTUDIO_BASE_URL", "http://localhost:4501"),
            model_name=app.config.get("MAIN_MODEL_NAME"),
            temperature=app.config.get("LMSTUDIO_TEMPERATURE", 0.7),
            max_tokens=app.config.get("LMSTUDIO_MAX_TOKENS", 4096),
            timeout=app.config.get("LMSTUDIO_TIMEOUT", 300),
        )
    else:
        return DeepSeekChat(api_key=app.config["DEEPSEEK_API_KEY"])

def _process_image_input(message: str, image_data: str) -> str:
    """
    将 base64 图片发送到本地 LMStudio 多模态模型，获取文字描述后拼入 message。
    如果 image_data 为空或转换失败，返回原 message。
    """
    if not image_data:
        return message

    # 如果 image_data 不是 data URL 格式，包装为 data URL
    data_url = image_data
    if not data_url.startswith("data:"):
        data_url = f"data:image/png;base64,{image_data}"

    try:
        vision_chat = LMStudioChat(
            base_url=app.config.get("LMSTUDIO_BASE_URL", "http://localhost:4501"),
            model_name=app.config.get("MEMORY_MODEL", "gemma-4-12b-it"),
            temperature=0.1,
            max_tokens=500,
            timeout=app.config.get("LMSTUDIO_TIMEOUT", 300),
        )
        vision_prompt = app.config.get("VISION_PROMPT", "请详细描述这张图片的内容")
        description = vision_chat.describe_image(data_url, vision_prompt)
        app.logger.info("图片转文字完成 (desc_len=%d)", len(description))
        return f"[图片描述: {description}]\n{message}"
    except Exception as e:
        app.logger.error("图片转文字失败: %s", e)
        return f"[无法识别图片: {e}]\n{message}"

# ---------- 辅助函数 ----------
def parse_task_instructions(text: str):
    """解析回复中的<task>指令，支持动作代码块。支持两种顺序:<task>在前或```action在前。"""
    tasks = []

    action_pattern = r'```action\s*\n(.*?)```'
    action_matches = list(re.finditer(action_pattern, text, re.DOTALL | re.IGNORECASE))

    task_pattern = r'<task>(.*?)</task>'
    task_matches = list(re.finditer(task_pattern, text, re.DOTALL | re.IGNORECASE))

    if not task_matches:
        return tasks

    action_matches.sort(key=lambda m: m.start())
    task_matches.sort(key=lambda m: m.start())
    used_actions = [False] * len(action_matches)

    for tm in task_matches:
        try:
            task_data = json.loads(tm.group(1).strip())
        except json.JSONDecodeError as e:
            app.logger.error("解析任务JSON失败: %s, 内容: %s", e, tm.group(1)[:100])
            continue

        if task_data.get("type") != "action":
            tasks.append(task_data)
            continue

        nearest_idx = -1
        nearest_dist = float("inf")
        for i, am in enumerate(action_matches):
            if used_actions[i]:
                continue
            dist = abs(am.start() - tm.start())
            if dist < nearest_dist:
                nearest_dist = dist
                nearest_idx = i

        if nearest_idx >= 0:
            used_actions[nearest_idx] = True
            task_data.setdefault("params", {})
            task_data["params"]["content"] = action_matches[nearest_idx].group(1).strip()
            tasks.append(task_data)

    return tasks

from utils.formatter import format_tool_result as _format_tool_result
from utils.text_clean import clean_display, clean_tts_text


def _save_debug_audio(audio_bytes: bytes):
    """DEBUG_ASR 模式下保存收到的音频到 logs/asr_history/"""
    import os as _os
    from datetime import datetime as _dt
    _dir = _os.path.join(_os.path.dirname(__file__), "logs", "asr_history")
    _os.makedirs(_dir, exist_ok=True)
    ts = _dt.now().strftime("%Y%m%d_%H%M%S_%f")
    path = _os.path.join(_dir, f"{ts}.webm")
    with open(path, "wb") as f:
        f.write(audio_bytes)
    app.logger.debug("DEBUG_ASR: 音频已保存 → %s (%d bytes)", path, len(audio_bytes))


def _convert_audio_to_wav(audio_bytes: bytes) -> bytes:
    """用 ffmpeg 将任意音频格式转为 16kHz 单声道 PCM WAV"""
    import subprocess as _sp
    import shutil as _sh

    ffmpeg = _sh.which("ffmpeg")
    if not ffmpeg:
        app.logger.warning("ffmpeg 未找到，跳过音频格式转换")
        return audio_bytes

    try:
        proc = _sp.run(
            [ffmpeg, "-y", "-i", "pipe:0",
             "-f", "wav", "-acodec", "pcm_s16le",
             "-ar", "16000", "-ac", "1", "pipe:1"],
            input=audio_bytes,
            capture_output=True,
            timeout=15,
        )
        if proc.returncode == 0 and proc.stdout:
            app.logger.debug("音频格式转换完成: %d → %d bytes", len(audio_bytes), len(proc.stdout))
            return proc.stdout
        app.logger.warning("ffmpeg 转换失败 (rc=%d): %s", proc.returncode, proc.stderr.decode(errors="replace")[:200])
        return audio_bytes
    except Exception as e:
        app.logger.warning("ffmpeg 转换异常: %s", e)
        return audio_bytes


def _synthesize_tts_lines(text: str) -> list[dict]:
    """按换行符切割文本，逐行合成 TTS 音频。返回 [{text, audio_b64}]。"""
    if not text or not _tts_available:
        return []

    cleaned = clean_tts_text(text)
    if not cleaned:
        return []

    raw_lines = cleaned.split("\n")
    lines = []
    for line in raw_lines:
        stripped = line.strip()
        if not stripped:
            continue
        if not any(c.isalpha() or "\u4e00" <= c <= "\u9fff" for c in stripped):
            continue
        lines.append(stripped)

    if not lines:
        return []

    results = []
    for i, line in enumerate(lines):
        try:
            processed_line = line
            if _tts_process_model is not None:
                processed_line = _tts_process_model.process_tts_text(line)
            tts_params = tts_profile_mgr.build_params(processed_line)
            audio_data = tts_client.tts(**tts_params)
            audio_b64 = base64.b64encode(audio_data).decode("utf-8")
            results.append({
                "index": i,
                "total": len(lines),
                "text": line,
                "audio_b64": audio_b64,
            })
            app.logger.debug("TTS 行 %d/%d 完成 (len=%d)", i + 1, len(lines), len(audio_b64))
        except Exception as e:
            app.logger.warning("TTS 行 %d/%d 失败: %s", i + 1, len(lines), e)
            results.append({
                "index": i,
                "total": len(lines),
                "text": line,
                "audio_b64": None,
            })

    ok_count = sum(1 for r in results if r["audio_b64"])
    app.logger.info("逐行 TTS 合成完成: %d/%d 行成功", ok_count, len(results))
    return results


def process_task_completion():
    """处理任务完成通知的线程函数"""
    while True:
        try:
            task_id, result = completion_queue.get()
            if task_id is None:  # 退出信号
                break
                
            app.logger.info("收到任务完成通知: task_id=%s", task_id)
            
            # 获取任务信息
            task = task_manager.get_task(task_id)
            if not task:
                app.logger.error("任务不存在: %s", task_id)
                continue
            
            app.logger.info("任务 %s 完成，用户 %d 需要被通知", task_id, task.user_id)
            
            # 处理不同类型的任务完成通知
            if task.task_type == TaskType.REMINDER:
                # 处理提醒任务：触发AI提醒用户
                _handle_reminder_completion(task, result)
            elif task.task_type == TaskType.REASONER:
                # 处理推理任务：保存结果供用户查询
                _handle_reasoner_completion(task, result)
            elif task.task_type == TaskType.ACTION:
                _handle_action_completion(task, result)
            else:
                app.logger.info("任务类型 %s 完成，结果: %s", task.task_type.value, result)

        except Exception as e:
            app.logger.error("处理任务完成通知失败: %s", e)
            import time
            time.sleep(1)

def _handle_reminder_completion(task, result):
    """处理提醒任务完成 — 注入提醒系统消息"""
    app.logger.info("提醒任务到期: task_id=%s", task.task_id)
    short_id = task.task_id[:8]
    reminder_text = result.get("reminder_text", "提醒时间到了！")
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    msg = f"[系统] ⏰ 提醒（ID: {short_id}）\n现在是 {current_time}，你之前设置的提醒：{reminder_text}"

    try:
        db.append_messages(task.user_id, task.chat_id, [{"role": "system", "content": msg}])
        app.logger.info("提醒已注入聊天: %s", short_id)
    except Exception as e:
        app.logger.error("保存提醒消息失败: %s", e)

def _handle_reasoner_completion(task, result):
    """处理推理任务完成 — 注入结果系统消息"""
    app.logger.info("推理任务完成: task_id=%s", task.task_id)
    short_id = task.task_id[:8]
    conclusion = result.get("conclusion", "")

    if conclusion:
        msg = f"[系统] 推理任务完成（ID: {short_id}）。\n结论: {conclusion}"
    else:
        reasoning = result.get("reasoning", "")
        msg = f"[系统] 推理任务完成（ID: {short_id}）。\n{reasoning[:2000]}"

    try:
        db.append_messages(task.user_id, task.chat_id, [{"role": "system", "content": msg}])
        app.logger.info("推理结果已注入聊天: %s", short_id)
    except Exception as e:
        app.logger.error("保存推理结果失败: %s", e)

def _handle_action_completion(task, result, retry_depth: int = 0):
    """处理动作任务完成 — 注入结果系统消息，支持自纠正"""
    if not result.get("requires_ai_notification", True):
        return

    app.logger.info("动作任务完成: task_id=%s, type=%s", task.task_id, result.get("action_type"))
    short_id = task.task_id[:8]
    action_type = result.get("action_type", "unknown")
    success = result.get("success", False)
    output = result.get("output", "")
    error = result.get("error", "")
    exit_code = result.get("exit_code", "")

    status = "成功" if success else "失败"
    msg_lines = [f"[系统] {action_type} 任务完成（ID: {short_id}）。状态: {status}"]

    if exit_code is not None and exit_code != "":
        msg_lines.append(f"退出码: {exit_code}")

    if output and output.strip():
        # 截断过长输出
        out = output.strip()
        if len(out) > 3000:
            out = out[:3000] + "\n...(输出截断)"
        msg_lines.append(f"输出:\n{out}")
    elif error:
        msg_lines.append(f"错误: {error}")

    msg = "\n".join(msg_lines)

    try:
        db.append_messages(task.user_id, task.chat_id, [{"role": "system", "content": msg}])
        app.logger.info("动作结果已注入聊天: %s", short_id)
    except Exception as e:
        app.logger.error("保存动作结果失败: %s", e)

# ---------- 日志配置 ----------
# 全局变量，用于跟踪日志是否已配置
_logging_configured = False

def setup_logging(app):
    global _logging_configured
    
    # 检查是否已经配置过日志，避免在Flask调试模式重启时重复配置
    if _logging_configured:
        app.logger.debug("日志系统已经配置，跳过重复配置")
        return
    
    log_dir = app.config["LOG_DIR"]
    os.makedirs(log_dir, exist_ok=True)
    log_filename = datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".log"
    log_path = os.path.join(log_dir, log_filename)

    # 创建文件处理器
    file_handler = RotatingFileHandler(
        log_path, maxBytes=10*1024*1024, backupCount=30, encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    file_handler.setFormatter(file_formatter)

    # 创建控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(console_formatter)

    # 只配置根日志记录器，这样所有子日志记录器都会继承处理器
    root_logger = logging.getLogger()
    
    # 清除所有现有的处理器，确保不会重复
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    root_logger.setLevel(logging.INFO)
    
    # 重要：禁用传播，避免日志被父日志记录器重复处理
    # 这样每个日志记录器只使用根日志记录器的处理器
    root_logger.propagate = False
    
    # 配置Flask应用日志记录器，但不添加处理器，让它使用根日志记录器的处理器
    for handler in app.logger.handlers[:]:
        app.logger.removeHandler(handler)
    
    # 不添加处理器到app.logger，让它使用根日志记录器的处理器
    app.logger.setLevel(logging.INFO)
    app.logger.propagate = True  # 允许传播到根日志记录器

    # 配置werkzeug日志记录器
    werkzeug_logger = logging.getLogger('werkzeug')
    for handler in werkzeug_logger.handlers[:]:
        werkzeug_logger.removeHandler(handler)
    
    # 不添加处理器到werkzeug_logger，让它使用根日志记录器的处理器
    werkzeug_logger.setLevel(logging.INFO)
    werkzeug_logger.propagate = True  # 允许传播到根日志记录器
    
    # 标记日志已配置
    _logging_configured = True
    
    app.logger.info("日志系统初始化完成")

# ---------- 创建应用 ----------
app = Flask(__name__)
app.config.from_object(Config)

setup_logging(app)

# ---- 分层认证系统 ----
from auth import AuthManager, auth_bp
_auth_manager = AuthManager(
    db=None,  # db 尚未创建，先创建 manager，后续注入
    jwt_secret=Config.JWT_SECRET,
    session_days=Config.AUTH_SESSION_DAYS,
    pairing_digits=Config.AUTH_PAIRING_DIGITS,
    pairing_timeout=Config.AUTH_PAIRING_TIMEOUT,
)
app.config["AUTH_MANAGER"] = _auth_manager
app.register_blueprint(auth_bp)

# 兼容：保留旧 LittleSkin OAuth 蓝图（降级为可选绑定）
init_usermgr(app)
app.register_blueprint(todo_bp)
db = ChatDBManager(db_path=app.config["DATABASE_PATH"])
_auth_manager.db = db  # 使用 property 传播到所有子管理器

# 首次启动：提示管理员使用 /newbind 生成配对码
if _auth_manager._user_count() == 0:
    print("  首次启动提示: 在服务器控制台输入 /newbind 生成配对码")
    app.logger.info("系统无用户，请在控制台输入 /newbind 生成配对码")

# 初始化任务管理器
if app.config.get("TASK_MANAGER_ENABLED", True):
    try:
        task_manager = TaskManager(db=db, max_workers=app.config.get("TASK_MAX_WORKERS", 5))
        # 设置完成队列
        task_manager.completion_queue = completion_queue
        app.logger.info("任务管理器初始化完成")
        
        # 启动任务完成通知线程
        threading.Thread(target=process_task_completion, daemon=True).start()
        app.logger.info("任务完成通知线程已启动")
    except Exception as e:
        app.logger.error("任务管理器初始化失败: %s", e)
        task_manager = None
else:
    task_manager = None
    app.logger.info("任务管理器已禁用")

# 初始化 记忆与摘要模块
if app.config.get("MEMORY_ENABLED", True):
    summary_backend = app.config.get("MEMORY_SUMMARY_BACKEND", "deepseek")
    summary_model = LMSummaryModel(
        backend=summary_backend,
        base_url=app.config.get("LMSTUDIO_BASE_URL"),
        model_name=app.config.get("MEMORY_MODEL"),
        summary_length=app.config.get("MEMORY_SUMMARY_LENGTH", 100),
    )
    memory_manager = MemoryManager(db=db, summary_model=summary_model)
else:
    summary_model = None
    memory_manager = None

# 初始化 TTS 客户端
tts_client = VocalExp(app.config["TTS_BASE_URL"])
tts_profile_mgr = TTSProfileManager()

# 初始化 TTS 文本预处理模型
if Config.TTS_PROCESS_ENABLED:
    try:
        _tts_process_model = TTSProcessModel()
        app.logger.info("TTSProcessModel 初始化完成")
    except Exception as e:
        app.logger.warning("TTSProcessModel 初始化失败: %s", e)
        _tts_process_model = None

# 初始化 ASR 过滤模型（根据配置启用）
filter_model = None
if app.config.get("ASR_FILTER_ENABLED", True):
    filter_model = LMFilterModel()

# ---------- 初始化ASR ----------
asr_model = None
if app.config.get("ASR_ENABLED", True):
    app.logger.info("正在加载FunASR模型...")
    asr_model = AutoModel(
        model="paraformer-zh",
        model_revision="v2.0.4",
        vad_model="fsmn-vad",
        vad_model_revision="v2.0.4",
        punc_model="ct-punc-c",
        punc_model_revision="v2.0.4",
        device=app.config.get("ASR_DEVICE", "cuda"), # 如果没有GPU请改为 "cpu"
        disable_update=True,
        disable_pbar=True
    )
    app.logger.info("FunASR模型加载完成")
else:
    app.logger.info("ASR功能已禁用，跳过FunASR模型加载")

# ---------- 初始化 Prompt 生态 ----------
import os as _os
_prompt_dir = _os.path.join(_os.path.dirname(__file__), "prompt", "prompts")
_pers_v2_dir = _os.path.join(_os.path.dirname(__file__), "prompt", "personality_v2", "presets")
prompt_engine = prompt.init_prompt_engine(
    library_dirs=[
        _os.path.join(_prompt_dir, "core"),
        _os.path.join(_prompt_dir, "capabilities"),
        _os.path.join(_prompt_dir, "extensions"),
    ],
    personality_v2_dir=_pers_v2_dir,
    db=db,
)
app.logger.info("PromptEngine 已初始化完成 (条目: %d)", len(prompt_engine.library.entries))

_personality_v2 = prompt_engine.personality_v2

# ---- 初始化印象管理器 ----
from prompt.impression import ImpressionManager
_impression_manager = ImpressionManager(db=db)

# ---- 初始化叙事世界模型 ----
_world_engine = None
_world_state_manager = None
_narrative_model = None
if Config.WORLD_ENABLED:
    try:
        from world import WorldEngine, WorldStateManager, NarrativeModel, WorldPlugin
        _world_preset_path = _os.path.join(
            _os.path.dirname(__file__), "world", "worlds", f"{Config.WORLD_PRESET}.yaml"
        )
        _world_engine = WorldEngine()
        _world_engine.load_config_file(_world_preset_path)
        _world_state_manager = WorldStateManager(_world_engine, Config.WORLD_UPDATE_INTERVAL)
        _world_state_manager.start()
        if Config.NARRATIVE_ENABLED:
            _narrative_model = NarrativeModel(
                model_type=Config.NARRATIVE_MODEL_TYPE,
                model_name=Config.NARRATIVE_MODEL,
                api_key=Config.DEEPSEEK_API_KEY,
                base_url=Config.LMSTUDIO_BASE_URL if Config.NARRATIVE_MODEL_TYPE == "lmstudio" else None,
                temperature=Config.NARRATIVE_TEMPERATURE,
                max_tokens=Config.NARRATIVE_MAX_TOKENS,
                keep_history=Config.NARRATIVE_KEEP_HISTORY,
            )
            _narrative_model.load_system_prompt_file(
                _os.path.join(_os.path.dirname(__file__), "prompt", "world", "narrative.md")
            )
        app.logger.info("叙事世界模型已初始化 (世界=%s, 叙事=%s)",
                        Config.WORLD_PRESET, "启用" if _narrative_model else "禁用")
    except Exception as e:
        app.logger.warning("叙事世界模型初始化失败: %s", e)

# ---------- 初始化技能系统 ----------
try:
    _skills_dir = _os.path.join(_os.path.dirname(__file__), "skills")
    from skills.registry import SkillRegistry
    from skills.manager import SkillManager

    skill_registry = SkillRegistry()
    skill_manager = SkillManager(
        skill_dirs=[
            _os.path.join(_skills_dir, "builtin"),
            _os.path.join(_skills_dir, "custom"),
        ],
        registry=skill_registry,
    )
    loaded = skill_manager.scan_and_load()
    prompt_engine.set_skill_registry(skill_registry)
    app.logger.info("技能系统初始化完成 (加载: %d 技能, 工具: %s)",
                     loaded, skill_registry.list_active_tools())
except Exception as e:
    app.logger.warning("技能系统初始化失败: %s", e)
    skill_registry = None
    skill_manager = None

# ---------- 初始化 DSNEngine ----------
from engine import create_engine_with_defaults

# ---------- 初始化人格系统 V3 ----------
personality_v3 = None
_v3_enabled = Config.PERSONALITY_V3_ENABLED
_v3_override = Config.PERSONALITY_V3_OVERRIDE_V2

app.logger.info("人格系统 V3: enabled=%s override_v2=%s", _v3_enabled, _v3_override)

if _v3_enabled:
    try:
        from prompt.personality_v3 import PersonalitySystemV3

        app.logger.info("V3: 导入 PersonalitySystemV3 成功")

        # 创建 V3 性格模型客户端（本地 LMStudio，低延迟）
        _v3_personality_chat = create_chat_client("fast")
        _v3_personality_chat.model = Config.PERSONALITY_MODEL_NAME
        if hasattr(_v3_personality_chat, 'model_name'):
            _v3_personality_chat.model_name = Config.PERSONALITY_MODEL_NAME
        app.logger.info("V3: 性格模型客户端已创建 (model=%s)", Config.PERSONALITY_MODEL_NAME)

        _v3_card_path = _os.path.join(_os.path.dirname(__file__), "character_cards", "exa.yaml")
        app.logger.info("V3: 默认角色卡路径=%s (存在=%s)", _v3_card_path, _os.path.exists(_v3_card_path))

        personality_v3 = PersonalitySystemV3(
            db=db,
            personality_model_chat=_v3_personality_chat,
            default_card_path=_v3_card_path,
        )
        app.logger.info("V3: PersonalitySystemV3 实例已创建")

        personality_v3.init_tables()
        app.logger.info("V3: 持久层表已初始化")

        # 配置蒸馏模型
        if Config.DISTILLATION_MODEL == "lmstudio":
            _distill_chat = create_chat_client("fast")
            _distill_chat.model = Config.PERSONALITY_MODEL_NAME
            if hasattr(_distill_chat, 'model_name'):
                _distill_chat.model_name = Config.PERSONALITY_MODEL_NAME
            personality_v3.set_distillation_model(fast_chat=_distill_chat)
            app.logger.info("V3: 蒸馏模型使用 LMStudio (model=%s)", Config.PERSONALITY_MODEL_NAME)
        else:
            _distill_chat = create_chat_client("deep")
            personality_v3.set_distillation_model(main_chat=_distill_chat)
            app.logger.info("V3: 蒸馏模型使用 DeepSeek API")

        # 注入到 PromptEngine
        prompt_engine.personality_v3 = personality_v3
        app.logger.info("V3: 已注入到全局 PromptEngine")

        # 当 override_v2 时，禁用 V2 的性格提示词注入
        if _v3_override:
            prompt_engine.personality_v2 = None
            app.logger.info("V3: PERSONALITY_V3_OVERRIDE_V2=true，已禁用 V2 性格注入")

        app.logger.info("PersonalitySystemV3 初始化完成 (override_v2=%s)", _v3_override)
    except Exception as e:
        app.logger.warning("PersonalitySystemV3 初始化失败: %s", e, exc_info=True)
        personality_v3 = None
else:
    app.logger.info("V3: PERSONALITY_V3_ENABLED=false，跳过初始化")

engine = create_engine_with_defaults(
    db=db,
    memory_manager=memory_manager,
    skill_registry=skill_registry,
    skill_manager=skill_manager,
    impression_manager=_impression_manager,
    tts_client=tts_client,
    filter_model=filter_model,
    world_engine=_world_engine,
    world_state_manager=_world_state_manager,
    narrative_model=_narrative_model,
    task_manager=task_manager,
    personality_v3=personality_v3,
)
app.logger.info("DSNEngine 已创建 (插件: %s)", engine.plugin_manager.list_plugins())

# ---------- 注入 V3 引用到 personality_materials 技能 ----------
try:
    if personality_v3 and skill_registry:
        for key, instance in skill_registry._tool_instances.items():
            if key.startswith("personality_materials."):
                instance._v3 = personality_v3
                app.logger.info("PersonalityMaterials: V3 已注入到 %s", key)
    else:
        app.logger.warning("PersonalityMaterials: V3 或 SkillRegistry 未初始化，跳过注入")
except Exception as e:
    app.logger.warning("PersonalityMaterials: 注入 V3 失败: %s", e)

# ---------- 初始化服务器维护模块 ----------
maint_system = None
try:
    from maintenance import MaintenanceSystem
    from maintenance.api import maintenance_bp
    from maintenance.frontend_bridge import broadcast as maint_broadcast

    maint_system = MaintenanceSystem(
        db=db,
        v3=personality_v3,
        engine=engine,
    )
    maint_system.on_maintenance_start(lambda: app.logger.info("维护流程开始"))
    maint_system.on_maintenance_progress(
        lambda task, prog: maint_broadcast("maintenance_progress", {
            "task": task.name,
            "current": prog.current,
            "total": prog.total,
            "message": prog.message,
        })
    )
    maint_system.on_maintenance_done(
        lambda results: maint_broadcast("maintenance_complete", {
            "results": results,
            "total": len(results),
            "success": sum(1 for r in results if r.get("success")),
        })
    )
    maint_system.start()
    app.config["MAINTENANCE_SYSTEM"] = maint_system
    app.register_blueprint(maintenance_bp)
    app.logger.info("维护模块已初始化")
except Exception as e:
    app.logger.warning("维护模块初始化失败: %s", e)
    app.config["MAINTENANCE_SYSTEM"] = None

# ---------- 认证装饰器 ----------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = app.config["AUTH_MANAGER"].authenticate(request)
        if not user:
            app.logger.warning("login_required: UNAUTHORIZED path=%s method=%s ip=%s auth_header=%s",
                               request.path, request.method,
                               request.remote_addr,
                               request.headers.get("Authorization", "")[:30] if request.headers.get("Authorization") else "<none>")
            return jsonify({"error": "Unauthorized"}), 401
        g.user = user
        app.logger.debug("login_required: OK uid=%d source=%s path=%s",
                         user["uid"], user.get("auth_source", "?"), request.path)
        db.add_or_update_user(user["uid"], user.get("nickname", "用户"))
        return f(*args, **kwargs)
    return decorated_function

# ---------- 请求钩子 ----------
@app.teardown_appcontext
def close_db_connection(exception=None):
    db.close_connection()

# ---------- CORS 支持 ----------
@app.after_request
def add_cors_headers(response):
    origin = request.headers.get("Origin", "")
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
    else:
        response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-DSN-API-Key"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    response.headers["Access-Control-Expose-Headers"] = "Content-Type, Cache-Control"
    response.headers["Access-Control-Max-Age"] = "3600"
    return response

# ---------- 维护状态检查 ----------
@app.before_request
def check_maintenance():
    """维护中时拒绝请求；记录活跃度"""
    if request.path.startswith("/api/maintenance/"):
        return None
    ms = app.config.get("MAINTENANCE_SYSTEM")
    if ms is None:
        return None
    ms.record_user_request()
    if ms.state.state.value == "maint":
        return jsonify({
            "error": "服务器整理中，请稍后访问",
            "status": "maintenance",
            "retry_after": 120,
        }), 503

@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        resp = jsonify({"ok": True})
        origin = request.headers.get("Origin", "")
        if origin:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Access-Control-Allow-Credentials"] = "true"
        else:
            resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-DSN-API-Key"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        resp.headers["Access-Control-Expose-Headers"] = "Content-Type, Cache-Control"
        resp.headers["Access-Control-Max-Age"] = "3600"
        return resp, 200

# ---------- API 路由 ----------
@app.route("/api/chat/send", methods=["POST"])
@login_required
def chat_send():
    """发送消息，获取回复和对应的 TTS 音频"""
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "Missing message"}), 400

    user_id = g.user["uid"]
    try:
        result = engine.chat(
            message=data["message"],
            user_id=user_id,
            chat_id=data.get("chat_id"),
            chat_name=data.get("chat_name", "未命名"),
            model_type=data.get("model_type"),
            nickname=g.user.get("nickname", "用户"),
            tts_enabled=data.get("tts_enabled", True),
            is_asr_input=data.get("is_asr_input", False),
            image_data=data.get("image_data"),
        )
    except Exception as e:
        app.logger.error("Engine chat 调用失败: %s", e)
        return jsonify({"error": "AI service error"}), 500

    if result.get("filtered"):
        return jsonify({"reply": "", "chat_id": result["chat_id"], "filtered": True})

    return jsonify({
        "reply": result["reply"],
        "chat_id": result["chat_id"],
        "audio": result.get("audio_b64"),
        "tts_error": result.get("tts_error"),
        "confirm_requested": result.get("extra", {}).get("confirm_requested", False),
    })

@app.route("/api/chat/stream_send", methods=["POST"])
@login_required
def chat_stream_send():
    """流式发送消息 — 使用引擎管线（含世界状态注入、旁白生成、Agent 循环、TTS）"""
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "Missing message"}), 400

    user_id = g.user["uid"]

    def generate():
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            agen = engine.chat_stream(
                message=data["message"],
                user_id=user_id,
                chat_id=data.get("chat_id"),
                chat_name=data.get("chat_name", "未命名"),
                model_type=data.get("model_type"),
                nickname=g.user.get("nickname", "用户"),
                tts_enabled=data.get("tts_enabled", True),
                is_asr_input=data.get("is_asr_input", False),
                image_data=data.get("image_data"),
            ).__aiter__()
            while True:
                try:
                    event = loop.run_until_complete(agen.__anext__())
                    yield event
                except StopAsyncIteration:
                    break
        finally:
            loop.close()

    return Response(stream_with_context(generate()), mimetype="text/event-stream")

@app.route("/api/chat/list", methods=["GET"])
@login_required
def chat_list():
    try:
        chats = db.list_chats(g.user["uid"])
        return jsonify({"chats": chats})
    except Exception as e:
        app.logger.error("列出聊天失败: %s", e)
        return jsonify({"error": "Database error"}), 500

@app.route("/api/chat/<int:chat_id>", methods=["GET"])
@login_required
def chat_history(chat_id):
    try:
        messages = db.get_chat_history(g.user["uid"], chat_id)
        return jsonify({"messages": messages})
    except Exception as e:
        app.logger.error("获取历史失败: %s", e)
        return jsonify({"error": "Database error"}), 500

@app.route("/api/asr/recognize", methods=["POST"])
@login_required
def asr_recognize():
    """接收客户端音频文件进行服务端识别"""
    if not app.config.get("ASR_ENABLED", True):
        return jsonify({"error": "ASR service is disabled"}), 403
        
    if 'audio' not in request.files:
        return jsonify({"error": "Missing audio file"}), 400
    
    file = request.files['audio']
    audio_bytes = file.read()

    if Config.DEBUG_ASR:
        _save_debug_audio(audio_bytes)

    audio_bytes = _convert_audio_to_wav(audio_bytes)

    try:
        res = asr_model.generate(
            input=audio_bytes,
            use_itn=True,
            batch_size_s=60,
            language="zh"
        )
        text = res[0].get("text", "").strip() if res and len(res) > 0 else ""
        return jsonify({"text": text})
    except Exception as e:
        app.logger.error("ASR识别错误: %s", e)
        return jsonify({"error": "ASR processing failed"}), 500


_SENSING_PROMPT_CACHE = None

def get_sensing_prompt() -> str:
    global _SENSING_PROMPT_CACHE
    if _SENSING_PROMPT_CACHE is not None:
        return _SENSING_PROMPT_CACHE
    import re as _re, os as _os
    path = _os.path.join(_os.path.dirname(__file__), "prompt", "prompts", "capabilities", "sensing.md")
    try:
        text = open(path, encoding="utf-8-sig").read()
        m = _re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, _re.DOTALL)
        content = m.group(2).strip() if m else text.strip()
    except Exception:
        content = ""
    _SENSING_PROMPT_CACHE = content
    return content


@app.route("/api/asr/passthrough", methods=["POST"])
@login_required
def asr_passthrough():
    """接收 base64 音频 → ASR 识别 → 聊天管线直通 (SSE)"""
    if not app.config.get("ASR_ENABLED", False):
        return jsonify({"error": "ASR service is disabled"}), 403

    data = request.get_json()
    if not data or ("audio_b64" not in data and "audio" not in data):
        return jsonify({"error": "Missing audio_b64 / audio"}), 400

    is_sensing = data.get("sensing", False) is True
    audio_b64 = data.get("audio_b64") or data.get("audio", "")
    try:
        audio_bytes = __import__("base64").b64decode(audio_b64)
    except Exception:
        return jsonify({"error": "Invalid base64 audio data"}), 400

    if Config.DEBUG_ASR:
        _save_debug_audio(audio_bytes)

    audio_bytes = _convert_audio_to_wav(audio_bytes)

    recognized_text = ""
    try:
        res = asr_model.generate(
            input=audio_bytes,
            use_itn=True,
            batch_size_s=60,
            language="zh"
        )
        recognized_text = res[0].get("text", "").strip() if res and len(res) > 0 else ""
    except Exception as e:
        app.logger.error("ASR passthrough 识别失败: %s", e)
        return jsonify({"error": "ASR processing failed"}), 500

    if not recognized_text:
        return jsonify({"reply": "", "chat_id": data.get("chat_id"), "filtered": True})

    message = f"你听到用户那边传来的声音：{recognized_text}"
    user_id = g.user["uid"]

    def generate():
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            agen = engine.chat_stream(
                message=message,
                user_id=user_id,
                chat_id=data.get("chat_id"),
                chat_name=data.get("chat_name", "Psychoscope"),
                model_type=data.get("model_type"),
                nickname=g.user.get("nickname", "用户"),
                tts_enabled=data.get("tts_enabled", True),
                is_asr_input=True,
                image_data=data.get("image_data"),
                sensing_hint=get_sensing_prompt() if is_sensing else "",
            ).__aiter__()
            while True:
                try:
                    event = loop.run_until_complete(agen.__anext__())
                    yield event
                except StopAsyncIteration:
                    break
        finally:
            loop.close()

    return Response(stream_with_context(generate()), mimetype="text/event-stream")

@app.route("/api/chat/<int:chat_id>", methods=["DELETE"])
@login_required
def chat_delete(chat_id):
    """删除聊天会话"""
    try:
        success = db.delete_chat(g.user["uid"], chat_id)
        if success:
            return jsonify({"success": True})
        else:
            return jsonify({"error": "Chat not found or access denied"}), 404
    except Exception as e:
        app.logger.error("删除聊天失败: %s", e)
        return jsonify({"error": "Database error"}), 500


# ========== 人格系统 v3 API ==========

@app.route("/api/v3/card/list", methods=["GET"])
@login_required
def v3_card_list():
    """列出所有角色卡"""
    if not personality_v3:
        return jsonify({"error": "PersonalitySystemV3 not available"}), 503
    cards = personality_v3.list_cards()
    return jsonify({"cards": cards})


@app.route("/api/v3/card/<card_id>", methods=["GET"])
@login_required
def v3_card_get(card_id):
    """获取角色卡详情"""
    if not personality_v3:
        return jsonify({"error": "PersonalitySystemV3 not available"}), 503
    card = personality_v3.get_card(card_id)
    if not card:
        return jsonify({"error": "Card not found"}), 404
    return jsonify(card.to_dict())


@app.route("/api/v3/card/upload", methods=["POST"])
@login_required
def v3_card_upload():
    """上传角色卡 YAML"""
    if not personality_v3:
        return jsonify({"error": "PersonalitySystemV3 not available"}), 503
    data = request.get_json()
    if not data or "yaml" not in data:
        return jsonify({"error": "Missing yaml content"}), 400
    try:
        from prompt.personality_v3 import CharacterCard
        card = CharacterCard.from_yaml_string(data["yaml"])
        ok = personality_v3.upload_card(card)
        return jsonify({"success": ok, "card_id": card.card_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/v3/card/<card_id>/distill", methods=["POST"])
@login_required
def v3_card_distill(card_id):
    """触发角色卡蒸馏"""
    if not personality_v3:
        return jsonify({"error": "PersonalitySystemV3 not available"}), 503
    try:
        distilled = personality_v3.distill(card_id)
        if not distilled:
            return jsonify({"error": "Distillation failed"}), 500
        return jsonify({
            "success": True,
            "distillation_id": distilled.distillation_id,
            "fingerprint": distilled.content_fingerprint,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/v3/card/<card_id>/distillation", methods=["GET"])
@login_required
def v3_card_distillation_get(card_id):
    """获取蒸馏产物"""
    if not personality_v3:
        return jsonify({"error": "PersonalitySystemV3 not available"}), 503
    d = personality_v3.get_distillation(card_id)
    if not d:
        return jsonify({"error": "Distillation not found"}), 404
    return jsonify(d.to_dict())


@app.route("/api/v3/user/bind", methods=["POST"])
@login_required
def v3_user_bind():
    """绑定用户到指定角色卡"""
    if not personality_v3:
        return jsonify({"error": "PersonalitySystemV3 not available"}), 503
    data = request.get_json()
    card_id = data.get("card_id", "") if data else ""
    if not card_id:
        return jsonify({"error": "Missing card_id"}), 400
    ok = personality_v3.bind_user_card(g.user["uid"], card_id)
    return jsonify({"success": ok})


# ========== 人格系统 v2 API (兼容保留) ==========

@app.route("/api/personality/status", methods=["GET"])
@login_required
def personality_status():
    """获取当前人格状态摘要 — V3 优先"""
    if personality_v3:
        return jsonify(personality_v3.get_personality_status(g.user["uid"]))
    if not _personality_v2:
        return jsonify({"error": "Personality system not available"}), 503
    state = _personality_v2.get_state(g.user["uid"])
    return jsonify(state)


@app.route("/api/personality/current", methods=["GET"])
@login_required
def personality_current():
    """获取完整人格状态 — V3 优先"""
    if personality_v3:
        return jsonify(personality_v3.get_personality_full(g.user["uid"]))
    if not _personality_v2:
        return jsonify({"error": "Personality system not available"}), 503
    state = _personality_v2.get_full_state(g.user["uid"])
    return jsonify(state)


@app.route("/api/personality/list", methods=["GET"])
@login_required
def personality_list():
    """列出所有可用性格 — V3 角色卡 + V2 预设"""
    result = {"presets": []}
    if personality_v3:
        result["cards"] = personality_v3.list_cards()
    if _personality_v2:
        result["presets"] = _personality_v2.list_presets()
    return jsonify(result)


@app.route("/api/personality/switch", methods=["POST"])
@login_required
def personality_switch():
    """切换到指定性格 — V3 绑角色卡 / V2 切换预设"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing data"}), 400

    # V3: 通过 card_id 绑定角色卡
    if personality_v3 and "card_id" in data:
        ok = personality_v3.bind_user_card(g.user["uid"], data["card_id"])
        return jsonify({"success": ok, "card_id": data["card_id"]})

    # V2: 通过 preset 切换预设
    if _personality_v2 and "preset" in data:
        return jsonify(_personality_v2.switch_preset(g.user["uid"], data["preset"]))

    return jsonify({"error": "Missing preset or card_id"}), 400


# ========== 用户印象 API ==========

@app.route("/api/impressions", methods=["GET"])
@login_required
def impression_list():
    """获取所有用户印象"""
    uid = g.user["uid"]
    category = request.args.get("category")
    min_conf = float(request.args.get("min_confidence", 0.0))
    imps = _impression_manager.query(uid, category=category, min_confidence=min_conf)
    return jsonify({
        "impressions": imps,
        "count": len(imps),
        "summary": _impression_manager.summary(uid),
    })


@app.route("/api/impressions", methods=["POST"])
@login_required
def impression_add():
    """手动添加印象"""
    uid = g.user["uid"]
    data = request.get_json()
    if not data or "content" not in data:
        return jsonify({"error": "Missing content"}), 400
    imp_id = _impression_manager.add(
        uid,
        data.get("category", "其他"),
        data["content"],
        data.get("confidence", 0.7),
        data.get("source", "declared"),
        data.get("evidence", ""),
    )
    return jsonify({"impression_id": imp_id})


@app.route("/api/impressions/<int:impression_id>", methods=["DELETE"])
@login_required
def impression_delete(impression_id: int):
    """删除指定印象"""
    ok = _impression_manager.delete(impression_id)
    return jsonify({"success": ok})


@app.route("/api/impressions/suggest", methods=["GET"])
@login_required
def impression_suggest():
    """检查是否建议启动全面了解协议"""
    uid = g.user["uid"]
    affinity_level = 0
    if _personality_v2:
        state = _personality_v2.get_state(uid)
        affinity_level = state.get("affinity", {}).get("level", 0)
    suggest = _impression_manager.should_propose_ssp(uid, affinity_level)
    return jsonify({
        "suggest_ssp": suggest,
        "impression_count": _impression_manager.count(uid),
    })


if __name__ == "__main__":
    app.run(
        host=app.config["SERVER_HOST"],
        port=app.config["SERVER_PORT"],
        debug=False
    )