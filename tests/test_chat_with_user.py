
# tests/test_chat_with_user.py
# PASSED v1_260214

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from usermgr import UserManager
from chatdbmgr import ChatDBManager
from models import DeepSeekChat

# 1. 登录
um = UserManager(client_id=845, client_secret="J6Hlf0Pp0mYTpRYyOhPFduJGJw828PjaDKOqXGbP")
user_info = um.login(timeout=120)
if user_info:
    uid = user_info["uid"]
    nickname = user_info["nickname"]

    # 2. 同步用户到数据库
    db = ChatDBManager()
    db.add_or_update_user(uid, nickname)

    # 3. 进行对话
    chat = DeepSeekChat(api_key="sk-5eda1d9ea5124fb4bfb13a1832ff91ab")
    chat.send_message("你好")
    chat.send_message("介绍一下自己")

    # 4. 保存对话历史
    history = chat.get_history()
    chat_id = db.save_chat_history(uid, "初次对话", history)
    print(f"聊天已保存，ID: {chat_id}")

    # 5. 列出该用户的所有聊天
    for c in db.list_chats(uid):
        print(f"聊天: {c['chat_name']} (ID: {c['chat_id']}), 消息数: {c['message_count']}")

    db.close()
else:
    print("登录失败或超时")