
# DSN-exp/models.py
# UPD v2_260326

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
            # 不再添加StreamHandler，因为根日志记录器已经配置了处理器
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


class LMSummaryModel:
    """本地 LMStudio 摘要模型，用于对话记忆压缩。"""

    SUMMARY_PROMPT = '''
你是一个专门擅长概括对话内容的AI，你的任务是根据输入的对话内容，提取出其中的关键信息，并用一句100字以内的话进行概括，作为回答输出。
你管理着系统的长期记忆。你生成的概括语句必须以AI的视角概括描述输入的对话内容。
不要输出“概括如下”或者“总结：”等引导语。你必须仅仅输出概括的内容。
需要你概括的对话内容如下：\n
'''

    def __init__(
        self,
        base_url: str = None,
        model_name: str = None,
        summary_length: int = 100,
        timeout: int = 60,
        logger: Optional[logging.Logger] = None,
    ):
        from config import Config

        self.base_url = base_url or Config.LMSTUDIO_BASE_URL
        self.model_name = model_name or Config.MEMORY_MODEL
        self.summary_length = summary_length
        self.timeout = timeout
        self.logger = logger or logging.getLogger(self.__class__.__name__)

    def summarize_text(self, text: str, max_length: Optional[int] = None) -> str:
        """调用 LMStudio 生成摘要。"""
        if not text or not isinstance(text, str):
            raise ValueError("text 必须是非空字符串")

        if max_length is None:
            max_length = self.summary_length

        prompt = self.SUMMARY_PROMPT.strip() + "\n" + text
        self.logger.debug("生成摘要的输入文本: %s", text[:200] + "..." if len(text) > 200 else text)

        # 使用HTTP请求而不是lmstudio库（更可靠）
        import requests

        url = f"{self.base_url}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_length,
            "temperature": 0.3,
            "stream": False
        }

        try:
            self.logger.debug("发送请求到 LMStudio: %s", url)
            response = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
            response.raise_for_status()
            result = response.json()

            if "choices" in result and result["choices"]:
                summary = result["choices"][0]["message"]["content"].strip()
                summary = summary.replace("\n", " ")
                # 限制长度
                if len(summary) > max_length:
                    summary = summary[:max_length].rstrip() + "..."
                self.logger.info("生成摘要: %s", summary[:80] + ("..." if len(summary) > 80 else ""))
                return summary
            else:
                raise ValueError("LMStudio响应格式异常")

        except requests.exceptions.Timeout:
            self.logger.error("LMStudio请求超时 (%d秒)", self.timeout)
            raise
        except requests.exceptions.ConnectionError:
            self.logger.error("无法连接到LMStudio服务器: %s", self.base_url)
            raise
        except requests.exceptions.RequestException as e:
            self.logger.error("LMStudio请求失败: %s", str(e))
            raise
        except (KeyError, ValueError) as e:
            self.logger.error("LMStudio响应解析失败: %s", str(e))
            raise

    def summarize_dialog(self, messages: List[Dict[str, str]], max_length: Optional[int] = None) -> str:
        """根据消息列表生成一条整体摘要。"""
        combined = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")
            if not isinstance(content, str):
                continue
            prefix = "用户" if role == "user" else "助手" if role == "assistant" else role
            combined.append(f"{prefix}:{content}")

        text = "\n".join(combined)
        return self.summarize_text(text, max_length=max_length)
