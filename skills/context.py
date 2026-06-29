# skills/context.py
# 技能调用上下文 — 线程安全的 ctx 传递

import threading

_local = threading.local()


def set_call_context(user_id: int = 0, chat_id: int = 0, extra: dict = None):
    _local.uid = user_id
    _local.cid = chat_id
    _local.extra = extra or {}



