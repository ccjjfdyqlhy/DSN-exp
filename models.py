
# DSN-exp/models.py
# UPD v1_260214

import requests
import json
import os
import logging
from typing import List, Dict, Optional, Union

class DeepSeekChat:
    """
    DeepSeek API 聊天客户端类，支持多轮对话历史管理。
    使用示例：
        chat = DeepSeekChat(api_key="your-key")
        reply = chat.send_message("你好")
        print(reply)
        chat.reset_conversation()
    """

    # 默认API地址和模型
    DEFAULT_API_URL = "https://api.deepseek.com/v1/chat/completions"
    DEFAULT_MODEL = "deepseek-chat"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        api_url: str = DEFAULT_API_URL,
        logger: Optional[logging.Logger] = None,
        timeout: int = 30,
    ):
        """
        初始化DeepSeek聊天客户端。

        :param api_key: DeepSeek API密钥，若为None则从环境变量DEEPSEEK_API_KEY读取
        :param model: 使用的模型名称，默认为deepseek-chat
        :param api_url: API端点URL
        :param logger: 日志记录器实例，若不提供则创建默认logger
        :param timeout: 请求超时时间（秒）
        """
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ValueError(
                "API密钥必须提供，可通过参数传入或设置环境变量DEEPSEEK_API_KEY"
            )

        self.model = model
        self.api_url = api_url
        self.timeout = timeout

        # 初始化对话历史
        self.messages: List[Dict[str, str]] = []

        # 设置日志记录器
        if logger is not None:
            self.logger = logger
        else:
            self.logger = logging.getLogger(self.__class__.__name__)
            if not self.logger.handlers:
                handler = logging.StreamHandler()
                formatter = logging.Formatter(
                    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
                )
                handler.setFormatter(formatter)
                self.logger.addHandler(handler)
                self.logger.setLevel(logging.INFO)

        self.logger.info("DeepSeekChat客户端初始化完成，模型：%s", self.model)

    def send_message(self, message: str) -> str:
        """
        发送一条用户消息，获取模型回复。

        :param message: 用户输入的消息文本
        :return: 模型的回复内容
        :raises: 请求失败或响应异常时会抛出相应异常
        """
        if not message or not isinstance(message, str):
            raise ValueError("消息内容必须为非空字符串")

        # 将用户消息加入历史
        self.messages.append({"role": "user", "content": message})
        self.logger.info("发送用户消息: %s", message[:50] + "..." if len(message) > 50 else message)

        # 准备请求
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": self.messages,
            "stream": False
        }

        try:
            self.logger.debug("请求payload: %s", json.dumps(payload, ensure_ascii=False))
            response = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()
            result = response.json()
            self.logger.debug("API响应: %s", json.dumps(result, ensure_ascii=False))

            # 提取助手回复
            assistant_message = result["choices"][0]["message"]["content"]
            self.messages.append({"role": "assistant", "content": assistant_message})
            self.logger.info("收到助手回复: %s", assistant_message[:50] + "..." if len(assistant_message) > 50 else assistant_message)

            return assistant_message

        except requests.exceptions.Timeout:
            self.logger.error("请求超时（%d秒）", self.timeout)
            raise
        except requests.exceptions.RequestException as e:
            self.logger.error("网络请求失败: %s", str(e))
            raise
        except KeyError as e:
            self.logger.error("响应格式异常，缺少字段: %s", str(e))
            raise ValueError("API返回的数据格式不正确") from e
        except json.JSONDecodeError as e:
            self.logger.error("JSON解析失败: %s", str(e))
            raise

    def reset_conversation(self):
        """清空当前对话历史"""
        self.messages.clear()
        self.logger.info("对话历史已重置")

    def get_history(self) -> List[Dict[str, str]]:
        """
        获取当前对话历史的副本。

        :return: 包含所有消息的列表，每条消息为{"role":角色, "content":内容}
        """
        return self.messages.copy()

    def set_model(self, model: str):
        """
        切换使用的模型。

        :param model: 新模型名称，如"deepseek-reasoner"
        """
        self.model = model
        self.logger.info("模型切换为: %s", self.model)

    def set_api_key(self, api_key: str):
        """更新API密钥"""
        self.api_key = api_key
        self.logger.info("API密钥已更新")

    def __repr__(self):
        return f"<DeepSeekChat model={self.model} history_len={len(self.messages)}>"