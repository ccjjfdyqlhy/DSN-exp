
# DSN-exp/app.py
# UPD v2_260324

import os
import base64
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from flask import Flask, request, jsonify, g
from functools import wraps

from config import Config
from usermgr import init_usermgr, auth_bp
from chatdbmgr import ChatDBManager
from models import DeepSeekChat, LMSummaryModel
from memory import MemoryManager
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

    logging.getLogger('werkzeug').handlers.clear()
    logging.getLogger('werkzeug').addHandler(file_handler)
    logging.getLogger('werkzeug').addHandler(console_handler)

# ---------- 创建应用 ----------
app = Flask(__name__)
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

    # 检查是否包含<text>标签，如果有则跳过TTS合成
    import re
    text_tag_pattern = r'<text>(.*?)</text>'
    text_matches = re.findall(text_tag_pattern, reply, re.DOTALL | re.IGNORECASE)

    if text_matches:
        # 包含<text>标签，跳过TTS合成
        app.logger.info("检测到<text>标签，跳过TTS合成")
        # 从回复中移除<text>标签，保留纯文本内容用于显示
        clean_reply = re.sub(text_tag_pattern, r'\1', reply, flags=re.DOTALL | re.IGNORECASE)
        reply = clean_reply.strip()
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