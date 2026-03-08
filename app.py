
# DSN-exp/app.py
# UPD v2_260308

import os
import base64
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from flask import Flask, request, jsonify, g
from functools import wraps

from usermgr import init_usermgr, auth_bp
from chatdbmgr import ChatDBManager
from models import DeepSeekChat
import prompt

# 导入 TTS 模块
import sys
sys.path.insert(0, os.path.dirname(__file__))  # 确保 vocal_infer 可导入
from vocal_infer import VocalExp, TTSRequestError

# ---------- 日志配置 ----------
def setup_logging(app):
    log_dir = app.config["LOG_DIR"]
    os.makedirs(log_dir, exist_ok=True)
    log_filename = datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".log"
    log_path = os.path.join(log_dir, log_filename)

    file_handler = RotatingFileHandler(
        log_path, maxBytes=10*1024*1024, backupCount=30, encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    file_handler.setFormatter(file_formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(console_formatter)

    app.logger.handlers.clear()
    app.logger.addHandler(file_handler)
    app.logger.addHandler(console_handler)
    app.logger.setLevel(logging.INFO)

    logging.getLogger('server').handlers.clear()
    logging.getLogger('server').addHandler(file_handler)
    logging.getLogger('server').addHandler(console_handler)

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

# 初始化 TTS 客户端
tts_client = VocalExp(app.config["TTS_BASE_URL"])

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

    # 构建包含系统提示词的完整历史
    system_prompt = prompt.get_system_prompt(g.user)
    full_history = [{"role": "system", "content": system_prompt}] + history

    # 调用 DeepSeek API
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

    # --- TTS 合成（仅在启用时执行）---
    audio_data = None
    tts_error = None
    if tts_enabled:
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