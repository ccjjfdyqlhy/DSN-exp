"""手动脚本：用 OpenAI 兼容端点做一次真实对话（**不是 pytest 测试**）。

2026-10 重命名说明：原名 test_openaichat.py 会被 pytest 收集，但它在模块级调用
input()，非交互环境下直接抛 OSError: reading from stdin，导致整轮收集被
污染。重命名为 scripts_*.py。跑法：python tests/scripts_openaichat.py
# tests/test_openaichat.py
# PASSED v1_260214
"""

# 简单示例
import os
import sys
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from apps.dsn.models import OpenAIChat

# 简单示例
chat = OpenAIChat(api_key=input("请输入API密钥: "))
try:
    reply1 = chat.send_message("你好，我是小明")
    print("AI:", reply1)

    reply2 = chat.send_message("你还记得我的名字吗？")
    print("AI:", reply2)

    print("当前历史:", chat.get_history())
    chat.reset_conversation()
except Exception as e:
    print("发生错误:", e)