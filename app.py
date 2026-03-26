
# DSN-exp/app.py
# UPD v2_260326

import os
import base64
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from flask import Flask, request, jsonify, g
from functools import wraps

from usermgr import init_usermgr, auth_bp
from chatdbmgr import ChatDBManager
from models import DeepSeekChat, LMSummaryModel
from memory import MemoryManager
import prompt

# 导入 TTS 模块
import sys
sys.path.insert(0, os.path.dirname(__file__))  # 确保 vocal_infer 可导入
from vocal_infer import VocalExp, TTSRequestError

# 导入 ASR 过滤模块
from ASR_filter import LMFilterModel

# ---------- 日志配置 ----------
def setup_logging(app):
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

    # 配置根日志记录器，这样所有模块的日志都会同时记录到文件和控制台
    root_logger = logging.getLogger()
    root_logger.handlers.clear()  # 清除现有的处理器
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    root_logger.setLevel(logging.INFO)

    # 同时配置Flask应用日志记录器
    app.logger.handlers.clear()
    app.logger.addHandler(file_handler)
    app.logger.addHandler(console_handler)
    app.logger.setLevel(logging.INFO)

    # 禁用werkzeug的默认处理器，避免重复日志
    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.handlers.clear()
    werkzeug_logger.addHandler(file_handler)
    werkzeug_logger.addHandler(console_handler)
    werkzeug_logger.setLevel(logging.INFO)

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
    tts_enabled = data.get("tts_enabled", True)  # 获取 TTS 开关，默认启用
    is_asr_input = data.get("is_asr_input", False)  # 新增：是否为ASR输入

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

    # 下面调用 DeepSeek API
    try:
        chat = DeepSeekChat(api_key=app.config["DEEPSEEK_API_KEY"])
        chat.messages = full_history.copy()
        reply = chat.send_message(message)
    except Exception as e:
        app.logger.error("DeepSeek API 调用失败: %s", e)
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

    # --- TTS 合成 ---
    audio_data = None
    tts_error = None

    # 检查是否包含<text>标签
    import re
    text_tag_pattern = r'<text>(.*?)</text>'
    text_matches = re.findall(text_tag_pattern, reply, re.DOTALL | re.IGNORECASE)

    if text_matches:
        # 包含<text>标签，提取标签内的内容用于显示
        app.logger.info("检测到<text>标签，提取标签内内容用于显示")
        # 从回复中移除<text>标签，保留纯文本内容用于显示
        clean_reply = re.sub(text_tag_pattern, r'\1', reply, flags=re.DOTALL | re.IGNORECASE)
        reply = clean_reply.strip()
        
        # 检查是否有不在标签里的部分，如果有则进行TTS合成
        # 获取标签外的内容：先移除所有<text>标签及其内容
        text_content_only = re.sub(text_tag_pattern, '', reply, flags=re.DOTALL | re.IGNORECASE)
        # 获取原始回复中标签外的内容
        outside_text = re.sub(r'<text>.*?</text>', '', original_reply, flags=re.DOTALL | re.IGNORECASE)
        outside_text = outside_text.strip()
        
        if outside_text:
            app.logger.info(f"检测到标签外内容，进行TTS合成: {outside_text}")
            try:
                # 构造 TTS 请求参数
                REF_AUDIO_PATH = os.path.join(os.path.dirname(__file__), "tests", "ref.wav")
                PROMPT_TEXT = "Many people may feel lost at times. After all, it's impossible for everything to happen according to your own wishes."

                params = {
                    "text": outside_text,
                    "text_lang": "zh",                     # 假设回复为中文
                    "ref_audio_path": REF_AUDIO_PATH,
                    "prompt_lang": "en",
                    "prompt_text": PROMPT_TEXT,
                    "media_type": "wav",
                    "streaming_mode": False,
                }
                audio_data = tts_client.tts(**params)
                app.logger.info("标签外内容TTS合成成功")
            except TTSRequestError as e:
                tts_error = f"TTS 服务请求失败: {e}"
                app.logger.error(tts_error)
            except Exception as e:
                tts_error = f"TTS 未知错误: {e}"
                app.logger.exception("TTS 异常")
        else:
            app.logger.info("没有检测到标签外内容，跳过TTS合成")
    else:
        # 不包含<text>标签，进行正常TTS合成
        try:
            # 构造 TTS 请求参数（可根据需要从数据库或配置获取参考音频等）
            # 这里使用示例参数，实际应让客户端选择或使用默认配置
            REF_AUDIO_PATH = os.path.join(os.path.dirname(__file__), "tests", "ref.wav")
            PROMPT_TEXT = "Many people may feel lost at times. After all, it's impossible for everything to happen according to your own wishes."

            params = {
                "text": reply,
                "text_lang": "zh",                     # 假设回复为中文
                "ref_audio_path": REF_AUDIO_PATH,
                "prompt_lang": "en",
                "prompt_text": PROMPT_TEXT,
                "media_type": "wav",
                "streaming_mode": False,
            }
            audio_data = tts_client.tts(**params)
        except TTSRequestError as e:
            tts_error = f"TTS 服务请求失败: {e}"
            app.logger.error(tts_error)
        except Exception as e:
            tts_error = f"TTS 未知错误: {e}"
            app.logger.exception("TTS 异常")

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

if __name__ == "__main__":
    app.run(
        host=app.config["SERVER_HOST"],
        port=app.config["SERVER_PORT"],
        debug=True
    )