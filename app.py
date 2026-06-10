
# DSN-exp/app.py
# UPD v3_260328

import os
import base64
import json
import re
import logging
import threading
import queue
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
from memory import MemoryManager
from tasks import TaskManager, TaskType, TaskStatus, ComplexityAnalyzer, get_task_manager
import prompt

# 导入 TTS 模块
import sys
sys.path.insert(0, os.path.dirname(__file__))  # 确保 vocal_infer 可导入
from vocal_infer import VocalExp, TTSRequestError

# 导入 ASR 过滤模块
from ASR_filter import LMFilterModel

# 导入 ASR 依赖
from flask import Response, stream_with_context
if Config.ASR_ENABLED: # 启动的更快
    from funasr import AutoModel
import io

# ---------- 全局变量 ----------
task_manager = None
completion_queue = queue.Queue()
complexity_analyzer = ComplexityAnalyzer()
notification_thread = None
_tts_available = True  # TTS 可用性标记，首次失败后置 False 避免刷屏

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

def _format_tool_result(skill: str, tool: str, result) -> str:
    """格式化工具执行结果为用户友好的文本。"""
    if not isinstance(result, dict):
        return str(result)

    if not result.get("success", False):
        return f"[工具 {skill}.{tool} 失败] {result.get('error', '未知错误')}"

    if skill == "web_search" and tool == "search":
        lines = [f"搜索: {result.get('query', '')}"]
        for i, r in enumerate(result.get("results", []), 1):
            lines.append(f"  {i}. {r.get('title', '')}")
            if r.get("snippet"):
                lines.append(f"     {r['snippet'][:200]}")
            if r.get("url"):
                lines.append(f"     {r['url']}")
        return "\n".join(lines)

    if skill == "file_manager":
        if tool == "list_dir":
            lines = [f"目录 {result.get('path', '')}:"]
            for item in result.get("items", []):
                marker = "[DIR]" if item.get("type") == "dir" else "[FILE]"
                lines.append(f"  {marker} {item['name']}")
            return "\n".join(lines)
        if tool == "read_file":
            content = result.get("content", "")
            if len(content) > 2000:
                content = content[:2000] + "\n...(截断)"
            return f"文件 {result.get('path', '')} ({result.get('size', 0)} bytes):\n{content}"
        if tool == "write_file":
            return f"已写入 {result.get('path', '')} ({result.get('size', 0)} bytes)"

    if skill == "browser_use":
        if tool == "navigate":
            return f"[浏览器] 已导航到 {result.get('url', '')}\n标题: {result.get('title', '')}"
        if tool == "click":
            return f"[浏览器] 已点击 \"{result.get('selector', '')}\""
        if tool == "type":
            return f"[浏览器] 已在 \"{result.get('selector', '')}\" 中输入文本"
        if tool == "get_content":
            return f"[浏览器] 页面内容 ({result.get('length', 0)} 字符):\n{result.get('content', '')[:2000]}"
        if tool == "get_title":
            return f"[浏览器] 页面标题: {result.get('title', '')}"
        if tool == "get_url":
            return f"[浏览器] 当前 URL: {result.get('url', '')}"
        if tool == "screenshot":
            if result.get("path"):
                return f"[浏览器] 截图已保存到 {result['path']}"
            return f"[浏览器] 截图 (base64, {result.get('length', 0)} 字符)"
        if tool == "execute_js":
            return f"[浏览器] JS 执行结果: {result.get('result', '')[:1000]}"
        if tool == "wait_for":
            appeared = result.get("appeared", False)
            status = "已出现" if appeared else "未出现"
            return f"[浏览器] 等待 \"{result.get('selector', '')}\" → {status}"
        if tool == "scroll":
            return f"[浏览器] 已向{result.get('direction', '')}滚动"

    if skill == "skillmgr":
        if tool == "list_skills":
            skills = result.get("skills", [])
            lines = [f"已安装技能 ({len(skills)} 个):"]
            for s in skills:
                status = "✓" if s.get("enabled") else "✗"
                lines.append(f"  {status} {s['name']} ({s.get('display_name', '')}) [{s.get('source', '')}] — {s.get('tool_count', 0)} tools")
            return "\n".join(lines)
        if tool == "enable_skill":
            return f"[skillmgr] {result.get('message', '')}"
        if tool == "disable_skill":
            return f"[skillmgr] {result.get('message', '')}"
        if tool == "install_deps":
            py = result.get("python_installed", [])
            sk = result.get("python_skipped", [])
            sys_r = result.get("system_results", [])
            lines = [f"[skillmgr] 依赖安装完成:"]
            if py:
                lines.append(f"  新安装: {', '.join(py)}")
            if sk:
                lines.append(f"  已存在: {', '.join(sk)}")
            if sys_r:
                for r in sys_r:
                    lines.append(f"  系统命令: {r.get('command', '')} (exit={r.get('exit_code', '?')})")
            return "\n".join(lines)
        if tool == "convert_skill":
            return f"[skillmgr] {result.get('message', '')}\n目标: {result.get('target', '')}\n二进制: {result.get('binary', '')}"
        if tool == "download_skill":
            return f"[skillmgr] {result.get('message', '')}"

    return json.dumps(result, ensure_ascii=False, indent=2)

def handle_complex_question(user_id: int, chat_id: int, message: str, history: list) -> dict:
    """处理复杂问题：创建异步推理任务并返回初步回复"""
    if not task_manager:
        return {"error": "任务管理器未初始化"}
    
    # 分析问题复杂度
    context_length = len(history)
    complexity_result = complexity_analyzer.analyze_complexity(message, context_length)
    
    app.logger.info("问题复杂度分析: %s", complexity_result)
    
    if not complexity_result["is_complex"]:
        return {"should_use_reasoner": False}
    
    # 创建推理任务
    task_params = {
        "question": message,
        "context": "\n".join([f"{msg['role']}: {msg['content']}" for msg in history[-5:]])  # 最近5条消息作为上下文
    }
    
    try:
        task_id = task_manager.create_task(
            task_type=TaskType.REASONER,
            user_id=user_id,
            chat_id=chat_id,
            params=task_params,
            priority=1  # 正常优先级
        )
        
        # 立即执行任务
        task_manager.execute_task(task_id)
        
        return {
            "should_use_reasoner": True,
            "task_id": task_id,
            "complexity_score": complexity_result["score"],
            "preliminary_reply": "这个问题看起来比较复杂，我需要一些时间来深入思考。让我先分析一下，稍后给您详细的解答。在此期间，您可以继续问我其他问题。"
        }
    except Exception as e:
        app.logger.error("创建推理任务失败: %s", e)
        return {"error": f"创建推理任务失败: {str(e)}"}

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
        notification_thread = threading.Thread(target=process_task_completion, daemon=True)
        notification_thread.start()
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
                model_type=Config.MAIN_MODEL_TYPE,
                model_name=Config.NARRATIVE_MODEL,
                api_key=Config.DEEPSEEK_API_KEY,
                base_url=Config.LMSTUDIO_BASE_URL if Config.MAIN_MODEL_TYPE == "lmstudio" else None,
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

# ---- 初始化插件管理器 ----
from plugins.manager import PluginManager
from plugins.base import HookPoint, PluginContext
_app_plugin_manager = PluginManager()
if _personality_v2:
    from plugins.builtin.personality_plugin import PersonalityPlugin
    _app_plugin_manager.register(PersonalityPlugin(personality_v2=_personality_v2))

from plugins.builtin.impression_plugin import ImpressionPlugin
_app_plugin_manager.register(ImpressionPlugin(impression_manager=_impression_manager))

if _world_engine and Config.WORLD_ENABLED:
    from world import WorldPlugin
    _app_plugin_manager.register(WorldPlugin(
        world_engine=_world_engine,
        world_state_manager=_world_state_manager,
        narrative_model=_narrative_model,
        personality_v2=_personality_v2,
    ))


def _dispatch_plugins_sync(hook: HookPoint, ctx: PluginContext) -> None:
    """同步调度指定钩子下所有已启用的插件（用于 Flask 非异步端点）"""
    for plugin in _app_plugin_manager.get_hooks_for(hook):
        if not _app_plugin_manager.is_enabled(plugin.name):
            continue
        try:
            plugin.on_hook(hook, ctx)
        except Exception:
            pass

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

    message = data["message"]
    chat_id = data.get("chat_id")
    chat_name = data.get("chat_name", "未命名")
    tts_enabled = data.get("tts_enabled", True)
    is_asr_input = data.get("is_asr_input", False)
    model_type = data.get("model_type")

    user_id = g.user["uid"]

    # 获取或创建聊天会话
    history = []
    if chat_id:
        try:
            history = db.get_chat_history(user_id, chat_id)
            if not history:
                return jsonify({"error": "Chat not found or access denied"}), 404
        except Exception as e:
            app.logger.error("获取聊天历史失败: %s", e)
            return jsonify({"error": "Database error"}), 500
    else:
        try:
            chat_id = db.create_chat(user_id, chat_name)
        except Exception as e:
            app.logger.error("创建聊天失败: %s", e)
            return jsonify({"error": "Database error"}), 500

    # 如果是ASR输入且启用过滤，先通过过滤模型判断
    if is_asr_input and filter_model is not None:
        decision = filter_model.filter_input(message)
        if decision == "HOLD":
            # 不转发给主模型，但生成记忆
            memory_content = f"听到：{message}"
            try:
                # 立即生成记忆并插入聊天列表
                round_index = db.get_memory_count(user_id, chat_id) + 1
                memory_id = db.save_memory(user_id, chat_id, round_index, memory_content)
                # 将记忆作为系统消息插入聊天历史
                db.append_messages(user_id, chat_id, [{"role": "system", "content": f"记忆摘要：{memory_content}"}])
                app.logger.info("ASR输入被过滤，生成记忆: %s", memory_content)
                return jsonify({"reply": "", "chat_id": chat_id, "filtered": True})
            except Exception as e:
                app.logger.error("生成ASR记忆失败: %s", e)
                return jsonify({"error": "Memory error"}), 500
        # 如果是FORWARD，继续正常流程

    # 构建包含系统提示词的完整历史，并基于记忆规则替换远端内容
    system_prompt = prompt.get_system_prompt(g.user)
    # PRE_PROCESS 插件 (世界模型注入环境)
    pre_ctx = PluginContext(user_id=user_id, message=message, system_prompt=system_prompt, nickname=g.user.get("nickname", "用户"))
    _dispatch_plugins_sync(HookPoint.PRE_PROCESS, pre_ctx)
    system_prompt = pre_ctx.system_prompt or system_prompt
    if memory_manager:
        assembled = memory_manager.assemble_context(g.user["uid"], chat_id, history)
    else:
        assembled = history
    full_history = [{"role": "system", "content": system_prompt}] + assembled
    # 这样我们避开把系统提示词给记忆化。

    # 下面调用主模型 API
    try:
        chat = create_chat_client(model_type)
        
        # 在用户消息前添加时间戳
        from datetime import datetime
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        timestamped_message = f"[{current_time}] {message}"
        
        chat.messages = full_history.copy()
        reply = chat.send_message(timestamped_message)
    except Exception as e:
        app.logger.error("主模型 API 调用失败: %s", e)
        return jsonify({"error": "AI service error"}), 500

    # 将新消息存入数据库 (附带 round_index 用于记忆召回)
    round_index = db.get_memory_count(user_id, chat_id) + 1
    new_messages = chat.messages[-2:]
    try:
        db.append_messages(user_id, chat_id, new_messages, round_index=round_index)
    except Exception as e:
        app.logger.error("追加消息失败: %s", e)
        return jsonify({"error": "Database error"}), 500

    # 保存原始回复
    original_reply = reply

    # ---- 插件调度: POST_PROCESS (人格v2 + 世界模型 + 印象) ----
    _dispatch_plugins_sync(HookPoint.POST_PROCESS,
                           PluginContext(user_id=user_id, message=message,
                                         reply=reply, original_reply=reply))

    # --- 处理技能工具 (<tool> 标签) ---
    if skill_registry is not None:
        import re as _tool_re
        _tool_pat = _tool_re.compile(r"<tool>\s*(.*?)\s*</tool>", _tool_re.DOTALL)
        _tool_matches = list(_tool_pat.finditer(original_reply))
        if _tool_matches:
            tool_results: list[str] = []
            for match in _tool_matches:
                try:
                    tool_data = json.loads(match.group(1).strip())
                    s_name = tool_data.get("skill", "")
                    t_name = tool_data.get("tool", "")
                    params = tool_data.get("params", {})
                    if s_name and t_name:
                        result = skill_registry.call_tool(s_name, t_name, params)
                        formatted = _format_tool_result(s_name, t_name, result)
                        tool_results.append(formatted)
                        app.logger.info("工具执行: %s.%s", s_name, t_name)
                except json.JSONDecodeError as e:
                    tool_results.append(f"[工具调用失败: JSON 解析错误] {e}")
                except ValueError as e:
                    tool_results.append(f"[工具调用失败] {e}")
                except Exception as e:
                    app.logger.exception("工具执行异常: %s", e)
                    tool_results.append(f"[工具执行异常] {e}")
            if tool_results:
                reply = _tool_pat.sub("", reply).strip()
                reply += "\n\n" + "\n".join(tool_results)

    # --- 处理记忆召回 (<recall> 标签) ---
    if memory_manager:
        try:
            recall_processed = memory_manager.process_recall_tags(user_id, chat_id, original_reply)
            if recall_processed != original_reply:
                reply = recall_processed
                app.logger.info("记忆召回已处理，回复已更新")
        except Exception as e:
            app.logger.error("记忆召回处理失败: %s", e)

    # --- 解析并执行异步任务 ---
    task_status_messages: list[str] = []
    if task_manager:
        tasks = parse_task_instructions(original_reply)
        for task_data in tasks:
            try:
                task_type = task_data.get("type")
                params = task_data.get("params", {})

                if task_type == "reminder":
                    time_str = params.get("time")
                    if time_str:
                        scheduled_time = datetime.fromisoformat(time_str)
                        task_id = task_manager.create_task(
                            task_type=TaskType.REMINDER,
                            user_id=user_id,
                            chat_id=chat_id,
                            params=params,
                            priority=1,
                            scheduled_time=scheduled_time
                        )
                        short_id = task_id[:8]
                        task_status_messages.append(f"[系统] 提醒已设置，将在 {time_str} 触发。任务ID: {short_id}")
                        app.logger.info("已创建提醒任务: %s, 时间: %s", task_id, scheduled_time)

                elif task_type == "reasoner":
                    task_id = task_manager.create_task(
                        task_type=TaskType.REASONER,
                        user_id=user_id,
                        chat_id=chat_id,
                        params=params,
                        priority=1
                    )
                    task_manager.execute_task(task_id)
                    short_id = task_id[:8]
                    task_status_messages.append(f"[系统] 深度推理任务已提交（ID: {short_id}），正在后台执行，完成后会通知你。")
                    app.logger.info("已创建并提交推理任务: %s", task_id)

                elif task_type == "action":
                    if "action_type" not in params:
                        params["action_type"] = "shell"
                    task_id = task_manager.create_task(
                        task_type=TaskType.ACTION,
                        user_id=user_id,
                        chat_id=chat_id,
                        params=params,
                        priority=1
                    )
                    task_manager.execute_task(task_id)
                    short_id = task_id[:8]
                    action_type = params.get("action_type", "shell")
                    task_status_messages.append(f"[系统] {action_type} 任务已提交（ID: {short_id}），正在后台执行，完成后会通知你。")
                    app.logger.info("已创建并提交动作任务: %s (类型: %s)", task_id, action_type)

            except Exception as e:
                app.logger.error("处理任务失败: %s, 任务数据: %s", e, task_data)

    if task_status_messages:
        status_text = "\n".join(task_status_messages)
        db.append_messages(user_id, chat_id, [{"role": "system", "content": status_text}])
        reply += "\n\n" + status_text

    # --- TTS 合成 ---
    audio_data = None
    tts_error = None
    global _tts_available

    # 移除所有标签以得到纯净显示文本
    import re
    display_reply = original_reply

    # <text> — 保留内容，去标签
    display_reply = re.sub(r'<text>(.*?)</text>', r'\1', display_reply, flags=re.DOTALL | re.IGNORECASE)
    # <task>, <tool>, <recall> — 完全移除
    for tag in ("task", "tool", "recall"):
        display_reply = re.sub(f"<{tag}>.*?</{tag}>", '', display_reply, flags=re.DOTALL)
    # 残留的 <> 标签
    display_reply = re.sub(r'<[^>]+>', '', display_reply)
    display_reply = re.sub(r'\s+', ' ', display_reply).strip()
    reply = display_reply

    # TTS 文本 — 完全移除所有标签
    tts_text = original_reply
    tts_text = re.sub(r'<text>(.*?)</text>', '', tts_text, flags=re.DOTALL | re.IGNORECASE)
    for tag in ("task", "tool", "recall"):
        tts_text = re.sub(f"<{tag}>.*?</{tag}>", '', tts_text, flags=re.DOTALL)
    tts_text = re.sub(r'<[^>]+>', '', tts_text)
    tts_text = re.sub(r'\s+', ' ', tts_text).strip()
    
    # 如果有内容才进行TTS合成
    if tts_text and _tts_available:
        try:
            REF_AUDIO_PATH = os.path.join(os.path.dirname(__file__), "tests", "ref.wav")
            PROMPT_TEXT = "Many people may feel lost at times. After all, it's impossible for everything to happen according to your own wishes."

            params = {
                "text": tts_text,
                "text_lang": "zh",
                "ref_audio_path": REF_AUDIO_PATH,
                "prompt_lang": "en",
                "prompt_text": PROMPT_TEXT,
                "media_type": "wav",
                "streaming_mode": False,
            }
            audio_data = tts_client.tts(**params)
            app.logger.info("TTS合成成功")
        except TTSRequestError as e:
            tts_error = f"TTS 服务请求失败: {e}"
            _tts_available = False
            app.logger.warning("TTS 不可用 (后续将跳过): %s", e)
        except Exception as e:
            tts_error = f"TTS 错误: {e}"
            _tts_available = False
            app.logger.warning("TTS 不可用 (后续将跳过): %s", e)
    elif not _tts_available:
        pass  # TTS 不可用，静默跳过

    # 写入记忆模块（异步摘要）
    if memory_manager:
        try:
            app.logger.info("启动记忆摘要任务...")
            memory_manager.record_dialog_and_summary(
                user_id=user_id,
                chat_id=chat_id,
                round_index=round_index,
                messages=[{"role": "user", "content": message}, {"role": "assistant", "content": original_reply}],
                async_mode=True,
            )
        except Exception as e:
            app.logger.error("记忆摘要任务启动失败: %s", e)

    # 准备响应
    response = {
        "reply": reply,
        "chat_id": chat_id,
        "audio": base64.b64encode(audio_data).decode('utf-8') if audio_data else None,
        "tts_error": tts_error
    }
    return jsonify(response)

@app.route("/api/chat/stream_send", methods=["POST"])
@login_required
def chat_stream_send():
    """流式发送消息 — Agent Loop：AI 可执行 action 并将结果喂回继续对话"""
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "Missing message"}), 400

    message = data["message"]
    chat_id = data.get("chat_id")
    chat_name = data.get("chat_name", "未命名")
    tts_enabled = data.get("tts_enabled", True)
    is_asr_input = data.get("is_asr_input", False)
    model_type = data.get("model_type")
    user_id = g.user["uid"]

    def _clean_display(raw: str) -> str:
        """移除控制标签，返回纯净显示文本"""
        t = raw
        t = re.sub(r'```action\s*\n.*?```', '', t, flags=re.DOTALL | re.IGNORECASE)
        t = re.sub(r'<text>(.*?)</text>', r'\1', t, flags=re.DOTALL | re.IGNORECASE)
        for tag in ("task", "tool", "recall"):
            t = re.sub(f"<{tag}>.*?</{tag}>", '', t, flags=re.DOTALL)
        t = re.sub(r'<[^>]+>', '', t)
        return re.sub(r'\s+', ' ', t).strip()

    def _extract_actions(raw: str) -> list:
        """从原始回复中提取可执行的 action 参数列表"""
        actions = []
        for td in parse_task_instructions(raw):
            if td.get("type") == "action":
                p = td.get("params", {})
                if "action_type" not in p:
                    p["action_type"] = "shell"
                actions.append({"action_type": p.get("action_type", "shell"), "params": p})
        return actions

    def _extract_and_save_impressions(text: str) -> None:
        """从 AI 回复中提取 IMPRESSION: 标签并写入 DB"""
        if not _impression_manager:
            return
        import re
        pat = re.compile(r"IMPRESSION\s*:\s*(.+?)\s*:\s*(.+?)\s*:\s*(\d+)", re.IGNORECASE)
        for m in pat.finditer(text):
            try:
                _impression_manager.add(
                    user_id,
                    m.group(1).strip(),
                    m.group(2).strip(),
                    int(m.group(3)) / 100.0,
                    "inferred",
                )
            except Exception:
                pass

    def _format_action_result(action_type: str, result: dict) -> str:
        """格式化 action 执行结果，用于喂回 AI"""
        if result.get("success"):
            return f"[系统] 你刚才的 {action_type} 操作已成功完成。\n输出:\n{result.get('output', '')}"[:2000]
        return f"[系统] 你刚才的 {action_type} 操作执行失败。\n错误: {result.get('error', '未知错误')}"

    def _process_tools_and_recall(raw: str) -> tuple[str, str]:
        """处理工具标签和记忆召回。返回 (清理后的文本, 工具结果反馈文本 或 空字符串)"""
        augmented = raw
        tool_results: list[str] = []
        if skill_registry is not None:
            _pat = re.compile(r"<tool>\s*(.*?)\s*</tool>", re.DOTALL)
            for m in _pat.finditer(raw):
                try:
                    d = json.loads(m.group(1).strip())
                    s_name = d.get("skill", "")
                    t_name = d.get("tool", "")
                    params = d.get("params", {})
                    if s_name and t_name:
                        r = skill_registry.call_tool(s_name, t_name, params)
                        formatted = _format_tool_result(s_name, t_name, r)
                        tool_results.append(formatted)
                        app.logger.info("工具执行: %s.%s", s_name, t_name)
                except Exception:
                    pass
            augmented = _pat.sub("", augmented).strip()
        if memory_manager:
            try:
                rec = memory_manager.process_recall_tags(user_id, chat_id, raw)
                if rec != raw:
                    augmented = rec
            except Exception:
                pass
        feedback = "\n".join(tool_results) if tool_results else ""
        return augmented, feedback

    def generate_stream():
        nonlocal chat_id
        # ── 阶段 1: 解析 ──
        yield f"data: {json.dumps({'status': 'parsing'})}\n\n"

        history = []
        if chat_id:
            history = db.get_chat_history(user_id, chat_id)
        else:
            chat_id = db.create_chat(user_id, chat_name)

        if is_asr_input and filter_model is not None:
            decision = filter_model.filter_input(message)
            if decision == "HOLD":
                mem = f"听到：{message}"
                ridx = db.get_memory_count(user_id, chat_id) + 1
                db.save_memory(user_id, chat_id, ridx, mem)
                db.append_messages(user_id, chat_id, [{"role": "system", "content": f"记忆摘要：{mem}"}])
                yield f"data: {json.dumps({'status': 'completed', 'reply': '', 'chat_id': chat_id, 'filtered': True})}\n\n"
                return

        system_prompt = prompt.get_system_prompt(g.user)
        # PRE_PROCESS 插件 (世界模型注入环境)
        pre_ctx = PluginContext(user_id=user_id, message=message, system_prompt=system_prompt, nickname=g.user.get("nickname", "用户"))
        _dispatch_plugins_sync(HookPoint.PRE_PROCESS, pre_ctx)
        system_prompt = pre_ctx.system_prompt or system_prompt
        if memory_manager:
            assembled = memory_manager.assemble_context(g.user["uid"], chat_id, history)
        else:
            assembled = history
        full_history = [{"role": "system", "content": system_prompt}] + assembled

        # ── 阶段 2: 初始 AI 调用 ──
        yield f"data: {json.dumps({'status': 'request'})}\n\n"

        chat = create_chat_client(model_type)
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        chat.messages = full_history.copy()
        reply = chat.send_message(f"[{current_time}] {message}")

        round_index = db.get_memory_count(user_id, chat_id) + 1
        db.append_messages(user_id, chat_id, chat.messages[-2:], round_index=round_index)
        original_reply = reply

        # ---- 插件调度: POST_PROCESS (人格v2 + 世界模型 + 印象) ----
        pctx = PluginContext(
            user_id=user_id, message=message,
            reply=_clean_display(original_reply),
            original_reply=original_reply,
        )
        _dispatch_plugins_sync(HookPoint.POST_PROCESS, pctx)
        narrative_text = pctx.extra.get("narrative", "")
        if narrative_text:
            yield f"data: {json.dumps({'status': 'narrative_update', 'text': narrative_text, 'speaker': 'narrator'})}\n\n"

        # ── 阶段 3: 统一 Agent Loop（工具 + 动作）──
        ssp_mode = bool(re.search(r"<ssp>", original_reply, re.IGNORECASE))
        max_steps = 50 if ssp_mode else Config.AGENT_MAX_STEPS
        if ssp_mode:
            app.logger.info("SSP 自维持管线启动: uid=%d max_steps=%d", user_id, max_steps)
            yield f"data: {json.dumps({'status': 'agent_action', 'desc': 'ssp_start'})}\n\n"

        pending = original_reply
        last_reply_for_tts = original_reply
        first_display = True

        for step in range(max_steps):
            clean, tool_feedback = _process_tools_and_recall(pending)
            actions = _extract_actions(clean)

            if not tool_feedback and not actions:
                if first_display:
                    yield f"data: {json.dumps({'status': 'text_ready', 'reply': _clean_display(clean), 'chat_id': chat_id})}\n\n"
                break

            if tool_feedback:
                remaining = max_steps - step - 1
                if remaining > 0:
                    tool_feedback = f"[Agent 步数 {step + 1}/{max_steps}，剩余 {remaining} 次执行机会]\n\n{tool_feedback}"
                chat.messages.append({"role": "system", "content": tool_feedback})
                db.append_messages(user_id, chat_id, [{"role": "system", "content": tool_feedback}])
                app.logger.info("Agent loop step %d: 工具结果已喂回 AI", step + 1)
                pending = chat.send_message(tool_feedback)
                db.append_messages(user_id, chat_id, chat.messages[-2:], round_index=round_index)
                last_reply_for_tts = pending
                _extract_and_save_impressions(pending)
                if first_display:
                    yield f"data: {json.dumps({'status': 'text_ready', 'reply': _clean_display(clean), 'chat_id': chat_id})}\n\n"
                    first_display = False
                yield f"data: {json.dumps({'status': 'text_update', 'reply': _clean_display(pending)})}\n\n"
                continue

            if actions:
                yield f"data: {json.dumps({'status': 'execution', 'step': step + 1})}\n\n"
                batch_results = []
                for act in actions:
                    atype = act["action_type"]
                    yield f"data: {json.dumps({'status': 'agent_action', 'desc': atype})}\n\n"
                    result = task_manager.execute_action_sync(user_id, chat_id, act["params"])
                    batch_results.append((atype, result))
                    app.logger.info("Agent loop step %d: %s 完成 (success=%s)", step + 1, atype, result.get("success"))
                if not batch_results:
                    break
                feedback = "\n\n".join(_format_action_result(t, r) for t, r in batch_results)
                remaining = max_steps - step - 1
                if remaining > 0:
                    feedback = f"[Agent 步数 {step + 1}/{max_steps}，剩余 {remaining} 次执行机会]\n\n{feedback}"
                chat.messages.append({"role": "system", "content": feedback})
                db.append_messages(user_id, chat_id, [{"role": "system", "content": feedback}])
                pending = chat.send_message(feedback)
                db.append_messages(user_id, chat_id, chat.messages[-2:], round_index=round_index)
                last_reply_for_tts = pending
                _extract_and_save_impressions(pending)
                if first_display:
                    yield f"data: {json.dumps({'status': 'text_ready', 'reply': _clean_display(clean), 'chat_id': chat_id})}\n\n"
                    first_display = False
                yield f"data: {json.dumps({'status': 'text_update', 'reply': _clean_display(pending)})}\n\n"

        # ── 阶段 4: TTS ──
        audio_b64 = None
        tts_error = None
        global _tts_available
        if tts_enabled and _tts_available:
            yield f"data: {json.dumps({'status': 'tts'})}\n\n"
            t = last_reply_for_tts
            t = re.sub(r'```action\s*\n.*?```', '', t, flags=re.DOTALL | re.IGNORECASE)
            t = re.sub(r'<text>(.*?)</text>', '', t, flags=re.DOTALL | re.IGNORECASE)
            for tag in ("task", "tool", "recall"):
                t = re.sub(f"<{tag}>.*?</{tag}>", '', t, flags=re.DOTALL)
            t = re.sub(r'<[^>]+>', '', t)
            t = re.sub(r'\s+', ' ', t).strip()
            if t:
                try:
                    tts_params = {
                        "text": t, "text_lang": "zh",
                        "ref_audio_path": os.path.join(os.path.dirname(__file__), "tests", "ref.wav"),
                        "prompt_lang": "en", "prompt_text": "Many people may feel lost at times.",
                        "media_type": "wav", "streaming_mode": False,
                    }
                    audio_data = tts_client.tts(**tts_params)
                    audio_b64 = base64.b64encode(audio_data).decode('utf-8')
                except Exception as e:
                    tts_error = str(e)
                    _tts_available = False
                    app.logger.warning("TTS 不可用 (后续将跳过): %s", e)

        # ── 阶段 5: 记忆 ──
        if memory_manager:
            try:
                memory_manager.record_dialog_and_summary(
                    user_id, chat_id, round_index,
                    [{"role": "user", "content": message}, {"role": "assistant", "content": original_reply}],
                    async_mode=True,
                )
            except Exception as e:
                app.logger.error("记忆摘要失败: %s", e)

        # ── 阶段 6: 完成 ──
        yield f"data: {json.dumps({'status': 'completed', 'audio': audio_b64, 'tts_error': tts_error})}\n\n"

    return Response(stream_with_context(generate_stream()), mimetype="text/event-stream")

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


# ========== 人格系统 v2 API ==========

@app.route("/api/personality/status", methods=["GET"])
@login_required
def personality_status():
    """获取当前人格状态摘要"""
    if not _personality_v2:
        return jsonify({"error": "PersonalitySystemV2 not available"}), 503
    state = _personality_v2.get_state(g.user["uid"])
    return jsonify(state)


@app.route("/api/personality/current", methods=["GET"])
@login_required
def personality_current():
    """获取完整人格状态"""
    if not _personality_v2:
        return jsonify({"error": "PersonalitySystemV2 not available"}), 503
    state = _personality_v2.get_full_state(g.user["uid"])
    return jsonify(state)


@app.route("/api/personality/list", methods=["GET"])
@login_required
def personality_list():
    """列出所有可用性格预设"""
    if not _personality_v2:
        return jsonify({"error": "PersonalitySystemV2 not available"}), 503
    presets = _personality_v2.list_presets()
    return jsonify({"presets": presets})


@app.route("/api/personality/switch", methods=["POST"])
@login_required
def personality_switch():
    """切换到指定性格预设"""
    if not _personality_v2:
        return jsonify({"error": "PersonalitySystemV2 not available"}), 503
    data = request.get_json()
    if not data or "preset" not in data:
        return jsonify({"error": "Missing preset name"}), 400
    result = _personality_v2.switch_preset(g.user["uid"], data["preset"])
    return jsonify(result)


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