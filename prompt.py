
# DSN-exp/prompt.py
# UPD v1_260214

from datetime import datetime
from typing import Dict, Any

# 默认系统提示词模板
DEFAULT_SYSTEM_PROMPT = """
你是一个名为DSN-exp的人工智能系统。
当前登录的用户ID：{nickname}
当前时间：{current_time}
"""

def get_system_prompt(user_info: Dict[str, Any]) -> str:
    """
    根据用户信息生成系统提示词。

    :param user_info: 包含用户信息的字典，至少应有 uid 和 nickname
    :return: 格式化后的系统提示词字符串
    """
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return DEFAULT_SYSTEM_PROMPT.format(
        nickname=user_info.get("nickname", "用户"),
        current_time=current_time
    )

# 可在此添加其他模板或根据不同条件返回不同提示词