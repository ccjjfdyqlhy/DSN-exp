
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

from usermgr import init_usermgr, auth_bp
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
from funasr import AutoModel
import io

# ---------- 全局变量 ----------
task_manager = None
completion_queue = queue.Queue()
complexity_analyzer = ComplexityAnalyzer()
notification_thread = None

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
    """解析回复中的<task>指令，支持动作代码块"""
    tasks = []
    
    # 查找所有 ```action 代码块
    action_pattern = r'```action\s*\n(.*?)```'
    action_matches = list(re.finditer(action_pattern, text, re.DOTALL | re.IGNORECASE))
    
    # 查找所有 <task> 标签
    task_pattern = r'<task>(.*?)</task>'
    task_matches = list(re.finditer(task_pattern, text, re.DOTALL | re.IGNORECASE))
    
    # 按在文本中的位置排序
    action_matches.sort(key=lambda m: m.start())
    task_matches.sort(key=lambda m: m.start())
    
    # 配对：假设每个代码块后面跟着一个task标签
    paired_tasks = []
    action_index = 0
    task_index = 0
    
    while action_index < len(action_matches) and task_index < len(task_matches):
        action_match = action_matches[action_index]
        task_match = task_matches[task_index]
        
        # 确保task标签在代码块之后（允许中间有内容）
        if task_match.start() > action_match.start():
            try:
                task_data = json.loads(task_match.group(1).strip())
                if task_data.get("type") == "action":
                    # 将代码块内容添加到params中
                    if "params" not in task_data:
                        task_data["params"] = {}
                    task_data["params"]["content"] = action_match.group(1).strip()
                    tasks.append(task_data)
                    paired_tasks.append(task_match)
                else:
                    # 非action类型，直接添加
                    tasks.append(task_data)
                    paired_tasks.append(task_match)
            except json.JSONDecodeError as e:
                app.logger.error("解析任务JSON失败: %s, 内容: %s", e, task_match.group(1)[:100])
                paired_tasks.append(task_match)
            
            action_index += 1
            task_index += 1
        else:
            # task标签在代码块之前，可能是普通任务
            try:
                task_data = json.loads(task_match.group(1).strip())
                if task_data.get("type") != "action":  # 非action类型
                    tasks.append(task_data)
                paired_tasks.append(task_match)
            except json.JSONDecodeError as e:
                app.logger.error("解析任务JSON失败: %s, 内容: %s", e, task_match.group(1)[:100])
                paired_tasks.append(task_match)
            task_index += 1
    
    # 处理剩余的未配对的task标签（非action类型）
    for j in range(task_index, len(task_matches)):
        if task_matches[j] not in paired_tasks:
            try:
                task_data = json.loads(task_matches[j].group(1).strip())
                if task_data.get("type") != "action":  # 跳过没有代码块的action类型
                    tasks.append(task_data)
            except json.JSONDecodeError as e:
                app.logger.error("解析任务JSON失败: %s, 内容: %s", e, task_matches[j].group(1)[:100])
    
    return tasks

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
                # 处理动作任务：触发AI生成结果消息
                _handle_action_completion(task, result)
            else:
                # 其他类型任务
                app.logger.info("任务类型 %s 完成，结果: %s", task.task_type.value, result)
            
            # 将任务结果保存到数据库，供后续查询
            try:
                conn = db._get_connection()
                conn.execute(
                    "INSERT INTO task_notifications (task_id, user_id, chat_id, result, created_at) VALUES (?, ?, ?, ?, ?)",
                    (task_id, task.user_id, task.chat_id, json.dumps(result), datetime.now().isoformat())
                )
                conn.commit()
                app.logger.info("任务通知已保存到数据库")
            except Exception as e:
                app.logger.error("保存任务通知失败: %s", e)
                
        except Exception as e:
            app.logger.error("处理任务完成通知失败: %s", e)
            import time
            time.sleep(1)

def _generate_ai_reminder_message(task, reminder_text):
    """调用AI生成自然的提醒消息"""
    try:
        # 获取聊天历史作为上下文
        history = db.get_chat_history(task.user_id, task.chat_id)
        
        # 构建系统提示词
        from prompt import get_system_prompt
        # 创建一个临时的用户信息字典
        temp_user_info = {"uid": task.user_id, "nickname": f"用户{task.user_id}"}
        system_prompt = get_system_prompt(temp_user_info)
        
        # 构建更自然的提醒提示词 - 让AI像主动想起一样提醒用户
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        reminder_prompt = f"""
现在是 {current_time}，你之前设置了一个提醒。
提醒内容：{reminder_text}
自然地提醒用户这件事。
"""
        
        # 创建聊天客户端
        chat = create_chat_client()
        
        # 构建完整的消息历史
        full_history = [{"role": "system", "content": system_prompt}]
        
        # 添加最近的历史消息作为上下文（最多5条）
        recent_history = history[-5:] if len(history) > 5 else history
        for msg in recent_history:
            full_history.append(msg)
        
        # 添加提醒提示词（带时间戳）
        full_history.append({"role": "user", "content": reminder_prompt})
        
        # 设置消息历史并发送
        chat.messages = full_history
        ai_response = chat.send_message("请生成一个自然的提醒消息")
        
        app.logger.info("AI生成的提醒消息: %s", ai_response[:100])
        return ai_response
        
    except Exception as e:
        app.logger.error("生成AI提醒消息失败: %s", e)
        # 如果AI调用失败，返回一个默认的自然提醒消息
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return f"嘿，现在是 {current_time}，你之前设置的提醒时间到了：{reminder_text}。记得去处理哦！"

def _handle_reminder_completion(task, result):
    """处理提醒任务完成：调用AI生成自然提醒消息"""
    app.logger.info("处理提醒任务完成: task_id=%s, user_id=%d, chat_id=%d", 
                   task.task_id, task.user_id, task.chat_id)
    
    # 检查是否需要AI通知
    if result.get("requires_ai_notification", False):
        reminder_text = result.get("reminder_text", "提醒时间到了！")
        skip_memory = result.get("skip_memory", False)
        
        app.logger.info("需要AI生成自然提醒消息: %s", reminder_text)
        
        try:
            # 调用AI生成自然提醒消息
            ai_message = _generate_ai_reminder_message(task, reminder_text)
            
            # 将AI生成的提醒消息保存到聊天历史
            reminder_message = {
                "role": "assistant",
                "content": ai_message,
                "skip_memory": skip_memory  # 添加标记，跳过记忆化
            }
            
            # 将提醒消息追加到聊天历史
            db.append_messages(task.user_id, task.chat_id, [reminder_message])
            app.logger.info("AI提醒消息已保存到聊天历史: %s", ai_message[:100])
            
            # 这里可以添加其他通知机制，如WebSocket推送、邮件通知等
            # 例如：通过WebSocket实时推送提醒
            # _send_websocket_notification(task.user_id, task.chat_id, ai_message)
            
        except Exception as e:
            app.logger.error("生成或保存AI提醒消息失败: %s", e)

def _handle_reasoner_completion(task, result):
    """处理推理任务完成"""
    app.logger.info("处理推理任务完成: task_id=%s, user_id=%d, chat_id=%d", 
                   task.task_id, task.user_id, task.chat_id)
    
    # 保存推理结果到聊天历史
    reasoning_result = result.get("reasoning", "")
    conclusion = result.get("conclusion", "")
    
    if conclusion:
        ai_message = f"【推理完成】\n\n经过深入分析，我得出的结论是：\n{conclusion}\n\n详细的推理过程已保存。"
        
        try:
            reminder_message = {
                "role": "assistant",
                "content": ai_message
            }
            
            db.append_messages(task.user_id, task.chat_id, [reminder_message])
            app.logger.info("推理结果已保存到聊天历史")
        except Exception as e:
            app.logger.error("保存推理结果失败: %s", e)

def _generate_action_result_message(task, result):
    """调用AI生成动作执行结果的回复消息"""
    try:
        # 获取聊天历史作为上下文
        history = db.get_chat_history(task.user_id, task.chat_id)
        
        # 构建系统提示词
        from prompt import get_system_prompt
        # 创建一个临时的用户信息字典
        temp_user_info = {"uid": task.user_id, "nickname": f"用户{task.user_id}"}
        system_prompt = get_system_prompt(temp_user_info)
        
        # 构建动作结果的提示词
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 根据动作类型和结果构建提示词
        action_type = result.get("action_type", "unknown")
        success = result.get("success", False)
        error = result.get("error")
        output = result.get("output", "")
        
        if action_type == "shell":
            prompt_text = f"""
现在是 {current_time}，我之前执行的系统命令已经完成。

命令预览：{result.get('content_preview', '')[:100]}...

执行结果：
- 成功：{success}
- 退出码：{result.get('exit_code', 'N/A')}
- 输出：{output[:500] if output else '无输出'}

请根据这个结果生成一个自然的回复，告诉用户命令执行的结果。如果成功，可以说命令执行完成并简要说明结果；如果失败，说明遇到了什么问题。
"""
        elif action_type == "python":
            prompt_text = f"""
现在是 {current_time}，我之前执行的Python代码已经完成。

代码预览：{result.get('content_preview', '')[:100]}...

执行结果：
- 成功：{success}
- 退出码：{result.get('exit_code', 'N/A')}
- 输出：{output[:500] if output else '无输出'}

请根据这个结果生成一个自然的回复，告诉用户代码执行的结果。
"""
        elif action_type == "write_file":
            prompt_text = f"""
现在是 {current_time}，我之前执行的文件写入操作已经完成。

文件路径：{result.get('file_path', '')}
文件大小：{result.get('file_size', 0)} 字符

执行结果：
- 成功：{success}
- 错误：{error if error else '无'}

请根据这个结果生成一个自然的回复，告诉用户文件写入的结果。
"""
        elif action_type == "edit_file":
            prompt_text = f"""
现在是 {current_time}，我之前执行的文件编辑操作已经完成。

文件路径：{result.get('file_path', '')}
原始大小：{result.get('old_size', 0)} 字符
新大小：{result.get('new_size', 0)} 字符

执行结果：
- 成功：{success}
- 错误：{error if error else '无'}

请根据这个结果生成一个自然的回复，告诉用户文件编辑的结果。
"""
        else:
            prompt_text = f"""
现在是 {current_time}，我之前执行的操作已经完成。

操作类型：{action_type}
执行结果：
- 成功：{success}
- 错误：{error if error else '无'}
- 输出：{output[:500] if output else '无输出'}

请根据这个结果生成一个自然的回复，告诉用户操作执行的结果。
"""
        
        # 创建聊天客户端
        chat = create_chat_client()
        
        # 构建完整的消息历史
        full_history = [{"role": "system", "content": system_prompt}]
        
        # 添加最近的历史消息作为上下文（最多5条）
        recent_history = history[-5:] if len(history) > 5 else history
        for msg in recent_history:
            full_history.append(msg)
        
        # 添加动作结果提示词
        full_history.append({"role": "user", "content": prompt_text})
        
        # 设置消息历史并发送
        chat.messages = full_history
        ai_response = chat.send_message("请生成一个自然的回复消息")
        
        app.logger.info("AI生成的动作结果消息: %s", ai_response[:100])
        return ai_response
        
    except Exception as e:
        app.logger.error("生成AI动作结果消息失败: %s", e)
        # 如果AI调用失败，返回一个默认的回复消息
        action_type = result.get("action_type", "操作")
        success = result.get("success", False)
        
        if success:
            return f"我之前执行的{action_type}操作已经成功完成了！"
        else:
            error = result.get("error", "未知错误")
            return f"我之前执行的{action_type}操作失败了：{error}"

def _handle_action_completion(task, result):
    """处理动作任务完成：调用AI生成自然结果消息"""
    app.logger.info("处理动作任务完成: task_id=%s, user_id=%d, chat_id=%d, action_type=%s", 
                   task.task_id, task.user_id, task.chat_id, result.get("action_type"))
    
    # 检查是否需要AI通知
    if result.get("requires_ai_notification", True):
        skip_memory = result.get("skip_memory", True)
        
        app.logger.info("需要AI生成动作结果消息")
        
        try:
            # 调用AI生成自然结果消息
            ai_message = _generate_action_result_message(task, result)
            
            # 将AI生成的消息保存到聊天历史
            action_message = {
                "role": "assistant",
                "content": ai_message,
                "skip_memory": skip_memory  # 添加标记，跳过记忆化
            }
            
            # 将消息追加到聊天历史
            db.append_messages(task.user_id, task.chat_id, [action_message])
            app.logger.info("AI动作结果消息已保存到聊天历史: %s", ai_message[:100])
            
        except Exception as e:
            app.logger.error("生成或保存AI动作结果消息失败: %s", e)

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

try:
    from config import Config
except ImportError:
    app.logger.warning("配置未初始化，请根据config.py.example创建config.py并配置相关参数")
    exit(1)

app.config.from_object(Config)

setup_logging(app)
init_usermgr(app)
db = ChatDBManager(db_path=app.config["DATABASE_PATH"])

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
    summary_model = LMSummaryModel(
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

# ---------- 认证装饰器 ----------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid token"}), 401
        token = auth_header[7:]
        user = app.config["USER_MANAGER"].verify_jwt(token)
        if not user:
            return jsonify({"error": "Invalid token"}), 401
        g.user = user
        db.add_or_update_user(user["uid"], user["nickname"])
        return f(*args, **kwargs)
    return decorated_function

# ---------- 请求钩子 ----------
@app.teardown_appcontext
def close_db_connection(exception=None):
    db.close_connection()

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

    # 将新消息存入数据库
    new_messages = chat.messages[-2:]
    try:
        db.append_messages(user_id, chat_id, new_messages)
    except Exception as e:
        app.logger.error("追加消息失败: %s", e)
        return jsonify({"error": "Database error"}), 500

    # 保存原始回复用于记忆摘要
    original_reply = reply

    # --- 解析并执行任务 ---
    if task_manager:
        tasks = parse_task_instructions(original_reply)
        for task_data in tasks:
            try:
                task_type = task_data.get("type")
                params = task_data.get("params", {})
                
                if task_type == "reminder":
                    # 解析提醒时间
                    time_str = params.get("time")
                    if time_str:
                        from datetime import datetime
                        scheduled_time = datetime.fromisoformat(time_str)
                        
                        task_id = task_manager.create_task(
                            task_type=TaskType.REMINDER,
                            user_id=user_id,
                            chat_id=chat_id,
                            params=params,
                            priority=1,
                            scheduled_time=scheduled_time
                        )
                        app.logger.info("已创建提醒任务: %s, 时间: %s", task_id, scheduled_time)
                        
                elif task_type == "reasoner":
                    # 创建推理任务
                    task_id = task_manager.create_task(
                        task_type=TaskType.REASONER,
                        user_id=user_id,
                        chat_id=chat_id,
                        params=params,
                        priority=1
                    )
                    # 立即执行推理任务
                    task_manager.execute_task(task_id)
                    app.logger.info("已创建并执行推理任务: %s", task_id)
                    
                elif task_type == "action":
                    # 创建动作执行任务
                    # 确保有action_type参数
                    if "action_type" not in params:
                        app.logger.warning("action类型任务缺少action_type参数")
                        params["action_type"] = "shell"  # 默认类型
                    
                    task_id = task_manager.create_task(
                        task_type=TaskType.ACTION,
                        user_id=user_id,
                        chat_id=chat_id,
                        params=params,
                        priority=1
                    )
                    # 立即执行动作任务
                    task_manager.execute_task(task_id)
                    app.logger.info("已创建并执行动作任务: %s (类型: %s)", task_id, params.get("action_type"))
                    
            except Exception as e:
                app.logger.error("处理任务失败: %s, 任务数据: %s", e, task_data)

    # --- TTS 合成 ---
    audio_data = None
    tts_error = None

    # 在TTS合成之前，需要移除所有标签，包括<text>和<task>标签
    # 首先提取用于显示的回复（移除所有标签）
    import re
    
    # 移除<text>标签，保留标签内的内容用于显示
    text_tag_pattern = r'<text>(.*?)</text>'
    display_reply = re.sub(text_tag_pattern, r'\1', original_reply, flags=re.DOTALL | re.IGNORECASE)
    
    # 移除<task>标签及其内容（完全移除）
    task_tag_pattern = r'<task>.*?</task>'
    display_reply = re.sub(task_tag_pattern, '', display_reply, flags=re.DOTALL | re.IGNORECASE)
    
    # 移除其他可能的标签
    display_reply = re.sub(r'<[^>]+>', '', display_reply)  # 移除所有HTML标签
    
    # 清理多余的空格和换行
    display_reply = re.sub(r'\s+', ' ', display_reply).strip()
    reply = display_reply
    
    # 准备用于TTS合成的文本：移除所有标签，只保留纯文本
    tts_text = original_reply
    
    # 移除<text>标签及其内容（完全移除）
    tts_text = re.sub(text_tag_pattern, '', tts_text, flags=re.DOTALL | re.IGNORECASE)
    
    # 移除<task>标签及其内容（完全移除）
    tts_text = re.sub(task_tag_pattern, '', tts_text, flags=re.DOTALL | re.IGNORECASE)
    
    # 移除其他可能的标签
    tts_text = re.sub(r'<[^>]+>', '', tts_text)  # 移除所有HTML标签
    
    # 清理多余的空格和换行
    tts_text = re.sub(r'\s+', ' ', tts_text).strip()
    
    # 如果有内容才进行TTS合成
    if tts_text:
        app.logger.info(f"进行TTS合成，文本: {tts_text[:100]}...")
        try:
            # 构造 TTS 请求参数
            REF_AUDIO_PATH = os.path.join(os.path.dirname(__file__), "tests", "ref.wav")
            PROMPT_TEXT = "Many people may feel lost at times. After all, it's impossible for everything to happen according to your own wishes."

            params = {
                "text": tts_text,
                "text_lang": "zh",                     # 假设回复为中文
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
            app.logger.error(tts_error)
        except Exception as e:
            tts_error = f"TTS 未知错误: {e}"
            app.logger.exception("TTS 异常")
    else:
        app.logger.info("没有可用于TTS合成的文本内容，跳过TTS合成")

    # 写入记忆模块（异步摘要）- 使用原始reply内容
    if memory_manager:
        round_index = db.get_memory_count(user_id, chat_id) + 1
        try:
            print("启动记忆摘要任务...")
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
    """流式发送消息并同步处理状态"""
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

    def generate_stream():
        nonlocal chat_id
        # --- [阶段 1: 解析] ---
        yield f"data: {json.dumps({'status': 'parsing'})}\n\n"
        
        history = []
        if chat_id:
            history = db.get_chat_history(user_id, chat_id)
        else:
            chat_id = db.create_chat(user_id, chat_name)

        if is_asr_input and filter_model is not None:
            decision = filter_model.filter_input(message)
            if decision == "HOLD":
                memory_content = f"听到：{message}"
                round_index = db.get_memory_count(user_id, chat_id) + 1
                db.save_memory(user_id, chat_id, round_index, memory_content)
                db.append_messages(user_id, chat_id, [{"role": "system", "content": f"记忆摘要：{memory_content}"}])
                yield f"data: {json.dumps({'status': 'completed', 'reply': '', 'chat_id': chat_id, 'filtered': True})}\n\n"
                return

        system_prompt = prompt.get_system_prompt(g.user)
        if memory_manager:
            assembled = memory_manager.assemble_context(g.user["uid"], chat_id, history)
        else:
            assembled = history
        full_history = [{"role": "system", "content": system_prompt}] + assembled

        # --- [阶段 2: 请求] ---
        yield f"data: {json.dumps({'status': 'request'})}\n\n"
        
        chat = create_chat_client(model_type)
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        timestamped_message = f"[{current_time}] {message}"
        
        chat.messages = full_history.copy()
        reply = chat.send_message(timestamped_message)
        db.append_messages(user_id, chat_id, chat.messages[-2:])
        original_reply = reply

        # 请求完成，立即把文字回复推给前端进行逐行打字机渲染
        yield f"data: {json.dumps({'status': 'text_ready', 'reply': original_reply, 'chat_id': chat_id})}\n\n"

        # --- [阶段 3: 执行] ---
        yield f"data: {json.dumps({'status': 'execution'})}\n\n"
        if task_manager:
            tasks = parse_task_instructions(original_reply)
            for task_data in tasks:
                try:
                    task_type = task_data.get("type")
                    params = task_data.get("params", {})
                    if task_type == "reminder":
                        time_str = params.get("time")
                        if time_str:
                            task_manager.create_task(TaskType.REMINDER, user_id, chat_id, params, 1, datetime.fromisoformat(time_str))
                    elif task_type == "reasoner":
                        task_id = task_manager.create_task(TaskType.REASONER, user_id, chat_id, params, 1)
                        task_manager.execute_task(task_id)
                    elif task_type == "action":
                        # 确保有action_type参数
                        if "action_type" not in params:
                            app.logger.warning("action类型任务缺少action_type参数")
                            params["action_type"] = "shell"  # 默认类型
                        
                        task_id = task_manager.create_task(
                            task_type=TaskType.ACTION,
                            user_id=user_id,
                            chat_id=chat_id,
                            params=params,
                            priority=1
                        )
                        # 立即执行动作任务
                        task_manager.execute_task(task_id)
                        app.logger.info("已创建并执行动作任务: %s (类型: %s)", task_id, params.get("action_type"))
                except Exception as e:
                    app.logger.error("处理任务失败: %s", e)

        # --- [阶段 4: TTS] ---
        audio_b64 = None
        tts_error = None
        if tts_enabled:
            yield f"data: {json.dumps({'status': 'tts'})}\n\n"
            text_tag_pattern = r'<text>(.*?)</text>'
            task_tag_pattern = r'<task>.*?</task>'
            tts_text = re.sub(text_tag_pattern, '', original_reply, flags=re.DOTALL | re.IGNORECASE)
            tts_text = re.sub(task_tag_pattern, '', tts_text, flags=re.DOTALL | re.IGNORECASE)
            tts_text = re.sub(r'<[^>]+>', '', tts_text)
            tts_text = re.sub(r'\s+', ' ', tts_text).strip()
            
            if tts_text:
                try:
                    params = {
                        "text": tts_text, "text_lang": "zh", 
                        "ref_audio_path": os.path.join(os.path.dirname(__file__), "tests", "ref.wav"),
                        "prompt_lang": "en", "prompt_text": "Many people may feel lost at times.",
                        "media_type": "wav", "streaming_mode": False,
                    }
                    audio_data = tts_client.tts(**params)
                    audio_b64 = base64.b64encode(audio_data).decode('utf-8')
                except Exception as e:
                    tts_error = str(e)

        if memory_manager:
            round_index = db.get_memory_count(user_id, chat_id) + 1
            memory_manager.record_dialog_and_summary(user_id, chat_id, round_index, [{"role": "user", "content": message}, {"role": "assistant", "content": original_reply}], async_mode=True)

        # --- [阶段 5: 完成] ---
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

if __name__ == "__main__":
    app.run(
        host=app.config["SERVER_HOST"],
        port=app.config["SERVER_PORT"],
        debug=True
    )