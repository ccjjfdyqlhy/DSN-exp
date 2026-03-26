
# DSN-exp/ASR_filter.py
# UPD v1_260326

import requests
import json
import os
import logging
from typing import List, Dict, Optional, Union

class LMFilterModel:
    """本地 LMStudio 过滤模型，用于判断用户输入是否应该转发给主AI系统。"""

    FILTER_PROMPT = '''
你是一个对话过滤器，负责判断用户输入是否应该转发给主AI系统（EXA）。请遵循以下规则：

1. 当用户明显在与EXA对话（包含问题、请求或延续对话的内容）时，转发完整内容。
2. 如果用户提到"EXA"，"Axa"或和主AI系统名字相似的发音，立即转发。
3. 当用户使用“你”时，立即转发。

判断后只需输出"FORWARD"（转发）或"HOLD"（保留），无需解释。
'''

    def __init__(
        self,
        base_url: str = None,
        model_name: str = None,
        timeout: int = 30,
        logger: Optional[logging.Logger] = None,
    ):
        from config import Config

        self.base_url = base_url or Config.LMSTUDIO_BASE_URL
        self.model_name = model_name or Config.FILTER_MODEL
        self.timeout = timeout
        self.logger = logger or logging.getLogger(self.__class__.__name__)

        # 初始化对话历史，包含系统提示
        self.messages: List[Dict[str, str]] = [{"role": "system", "content": self.FILTER_PROMPT}]

    def filter_input(self, user_input: str) -> str:
        """
        判断用户输入是否应该转发给主AI系统。

        :param user_input: 用户输入的文本
        :return: "FORWARD" 或 "HOLD"
        """
        if not user_input or not isinstance(user_input, str):
            return "HOLD"

        # 添加用户输入到对话历史
        self.messages.append({"role": "user", "content": user_input})

        # 准备请求
        url = f"{self.base_url}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        payload = {
            "model": self.model_name,
            "messages": self.messages,
            "max_tokens": 10,  # 只需输出FORWARD或HOLD
            "temperature": 0.1,  # 低温度确保一致性
            "stream": False
        }

        try:
            self.logger.debug("发送过滤请求到 LMStudio: %s", user_input[:50] + "..." if len(user_input) > 50 else user_input)
            response = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
            response.raise_for_status()
            result = response.json()

            if "choices" in result and result["choices"]:
                decision = result["choices"][0]["message"]["content"].strip().upper()
                if decision in ["FORWARD", "HOLD"]:
                    # 添加助手回复到历史
                    self.messages.append({"role": "assistant", "content": decision})
                    self.logger.info("过滤决策: %s for input: %s", decision, user_input[:50] + "..." if len(user_input) > 50 else user_input)
                    return decision
                else:
                    self.logger.warning("过滤模型返回无效决策: %s", decision)
                    return "HOLD"
            else:
                raise ValueError("LMStudio响应格式异常")

        except requests.exceptions.Timeout:
            self.logger.error("过滤请求超时 (%d秒)", self.timeout)
            return "HOLD"
        except requests.exceptions.ConnectionError:
            self.logger.error("无法连接到LMStudio服务器: %s", self.base_url)
            return "HOLD"
        except requests.exceptions.RequestException as e:
            self.logger.error("过滤请求失败: %s", str(e))
            return "HOLD"
        except (KeyError, ValueError) as e:
            self.logger.error("过滤响应解析失败: %s", str(e))
            return "HOLD"

    def reset_context(self):
        """重置过滤上下文"""
        self.messages = [{"role": "system", "content": self.FILTER_PROMPT}]
        self.logger.info("过滤上下文已重置")