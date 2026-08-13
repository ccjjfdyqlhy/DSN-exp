# apps/text_agent/__init__.py
# 参考应用：一个完全基于 harness 核心的纯文本 Agent。
#
# 它不 import 任何 DSN 代码，仅依赖 harness.*，
# 用来说明 harness 是"场景无关"的：换掉模型与工具即可承载任意应用。
#
# 用法:
#     from apps.text_agent.app import TextAgentApp
#     agent = TextAgentApp(...)
#     print(agent.run("1+2 等于几？"))

from .app import TextAgentApp

__all__ = ["TextAgentApp"]
