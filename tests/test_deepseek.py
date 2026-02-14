
# tests/test_deepseek.py
# PASSED v1_260214

import os
import sys
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from models import DeepSeekChat

# 简单示例
chat = DeepSeekChat(api_key=input("请输入DeepSeek API密钥: "))
try:
    reply1 = chat.send_message("你好，我是小明")
    print("AI:", reply1)

    reply2 = chat.send_message("你还记得我的名字吗？")
    print("AI:", reply2)

    print("当前历史:", chat.get_history())
    chat.reset_conversation()
except Exception as e:
    print("发生错误:", e)