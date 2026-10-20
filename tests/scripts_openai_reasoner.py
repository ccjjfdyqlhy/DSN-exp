"""手动脚本：reasoner 模型行为验证（**不是 pytest 测试**）。

2026-10 重命名说明：原名 test_openai_reasoner.py 在收集期就用真实 API Key
发起请求，离线/无网环境直接报 InternalServerError。重命名为 scripts_*.py。
跑法：python tests/scripts_openai_reasoner.py
# tests/test_openai_reasoner.py
# v1_260329
"""

# Turn 1
from openai import OpenAI

import os,sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from apps.dsn.config import Config

client = OpenAI(api_key=Config.OPENAI_API_KEY, base_url=Config.OPENAI_API_BASE)

# Turn 1
messages = [{"role": "user", "content": "9.11 and 9.8, which is greater?"}]
print("Thinking...")
response = client.chat.completions.create(
    model="deepseek-reasoner",
    messages=messages
)

reasoning_content = response.choices[0].message.reasoning_content
content = response.choices[0].message.content
print("Reasoning Content:", reasoning_content)
print("Content:", content)
