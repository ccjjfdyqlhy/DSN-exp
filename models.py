
# DSN-exp/models.py
# UPD v3_260328

import requests
import json
import os
import logging
from typing import List, Dict, Optional, Union


def _is_no_model_error(response) -> bool:
    """检查 HTTP 400 错误是否因 'No models loaded' 导致"""
    if response is None or response.status_code != 400:
        return False
    try:
        body = response.text or ""
        return "no model" in body.lower() or "No models loaded" in body
    except Exception:
        return False


def _load_lmstudio_model(base_url: str, model_name: str, label: str, timeout: int = 180) -> bool:
    """向 LMStudio 发送模型加载请求，返回是否成功"""
    if not model_name:
        logging.getLogger("models").error("未配置 model_name，无法自动加载 %s", label)
        return False
    try:
        logging.getLogger("models").info("正在加载 %s: %s", label, model_name)
        load_resp = requests.post(
            f"{base_url}/api/v1/models/load",
            json={"model": model_name},
            timeout=timeout,
        )
        load_resp.raise_for_status()
        result = load_resp.json()
        logging.getLogger("models").info(
            "%s 加载完成 (%.1fs): %s", label, result.get("load_time_seconds", 0), model_name)
        return True
    except Exception as e:
        logging.getLogger("models").error("自动加载 %s 失败 (%s): %s", label, model_name, e)
        return False

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
    DEFAULT_MODEL = "deepseek-v4-flash"
    REASONER_MODEL = "deepseek-v4-pro"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        api_url: str = DEFAULT_API_URL,
        logger: Optional[logging.Logger] = None,
        timeout: int = 114514,
        use_reasoner: bool = False,
        max_history: int = 0,
    ):
        """
        初始化DeepSeek聊天客户端。

        :param api_key: DeepSeek API密钥，若为None则从环境变量DEEPSEEK_API_KEY读取
        :param model: 使用的模型名称，默认为deepseek-chat
        :param api_url: API端点URL
        :param logger: 日志记录器实例，若不提供则创建默认logger
        :param timeout: 请求超时时间（秒）
        :param use_reasoner: 是否使用reasoner模型
        :param max_history: 最大历史消息数（0表示无限制），超过时丢弃最旧消息
        """
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ValueError(
                "API密钥必须提供，可通过参数传入或设置环境变量DEEPSEEK_API_KEY"
            )

        self.model = model
        self.api_url = api_url
        self.timeout = timeout
        self.use_reasoner = use_reasoner
        self.max_history = max_history

        # 初始化对话历史
        self.messages: List[Dict[str, str]] = []
        self.last_usage = None
        self.last_model = self.model

        # 设置日志记录器
        if logger is not None:
            self.logger = logger
        else:
            self.logger = logging.getLogger(self.__class__.__name__)
            # 不再添加StreamHandler，因为根日志记录器已经配置了处理器
            self.logger.setLevel(logging.INFO)

        # 如果指定使用reasoner，则切换模型
        if use_reasoner:
            self.model = self.REASONER_MODEL
        
        self.logger.info("DeepSeekChat客户端初始化完成，模型：%s", self.model)

    def send_message(self, message: str) -> str:
        """发送一条用户消息，获取模型回复。"""
        if not message or not isinstance(message, str):
            raise ValueError("消息内容必须为非空字符串")

        self.messages.append({"role": "user", "content": message})
        return self._call_and_append()

    def continue_conversation(self) -> str:
        """不追加新用户消息，直接用当前消息列表调用 LLM（用于 Agent 工具反馈循环）。"""
        return self._call_and_append()

    def _call_and_append(self) -> str:
        """核心调用逻辑：发送 self.messages → 获取回复 → 追加到 history → 返回"""
        self.logger.info("发送请求，消息数: %d", len(self.messages))

        # 上下文窗口裁剪：保留最多 max_history 条消息
        if self.max_history > 0 and len(self.messages) > self.max_history:
            system_msgs = [m for m in self.messages if m.get("role") == "system"]
            other_msgs = [m for m in self.messages if m.get("role") != "system"]
            if other_msgs:
                other_msgs = other_msgs[-(self.max_history - len(system_msgs)):]
            self.messages = system_msgs + other_msgs
            self.logger.info("上下文裁剪后消息数: %d", len(self.messages))

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

            self.last_usage = result.get("usage")
            self.last_model = result.get("model", self.model)

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


class LMStudioChat:
    """
    本地 LMStudio 聊天客户端类，支持多轮对话历史管理。
    与 DeepSeekChat 接口兼容，可作为主模型的替代方案。
    """

    def __init__(
        self,
        base_url: str = "http://localhost:4501",
        model_name: str = None,
        timeout: int = 300,
        logger: Optional[logging.Logger] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ):
        """
        初始化 LMStudio 聊天客户端。

        :param base_url: LMStudio 服务地址
        :param model_name: 模型名称，若为None则使用服务器默认模型
        :param timeout: 请求超时时间（秒）
        :param logger: 日志记录器实例
        :param temperature: 生成温度
        :param max_tokens: 最大生成token数
        """
        self.base_url = base_url.rstrip('/')
        self.model_name = model_name
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens

        self.messages: List[Dict[str, str]] = []
        self.last_usage = None
        self.last_model = self.model_name or "lmstudio"

        if logger is not None:
            self.logger = logger
        else:
            self.logger = logging.getLogger(self.__class__.__name__)
            self.logger.setLevel(logging.INFO)

        self.logger.info("LMStudioChat客户端初始化完成，地址：%s，模型：%s", self.base_url, self.model_name or "默认")

    def _ensure_model_loaded(self) -> bool:
        return _load_lmstudio_model(self.base_url, self.model_name, "LMStudio 模型")

    # ---- 底层 API 调用（含自动加载重试） ----

    def _call_chat_api(self, payload: dict) -> dict:
        """调用 /v1/chat/completions，若模型未加载则自动加载后重试一次"""
        url = f"{self.base_url}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}

        for attempt in range(2):
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
                response.raise_for_status()
                result = response.json()
                self.last_usage = result.get("usage")
                self.last_model = result.get("model", self.model_name)
                return result
            except requests.exceptions.HTTPError as e:
                if attempt == 0 and _is_no_model_error(e.response):
                    self.logger.info("检测到 LMStudio 未加载模型，自动加载后重试……")
                    if self._ensure_model_loaded():
                        continue
                raise

    def send_message(self, message: str) -> str:
        """发送一条用户消息，获取模型回复。"""
        if not message or not isinstance(message, str):
            raise ValueError("消息内容必须为非空字符串")

        self.messages.append({"role": "user", "content": message})
        self.logger.info("发送用户消息: %s", message[:50] + "..." if len(message) > 50 else message)
        return self._call_and_append()

    def continue_conversation(self) -> str:
        """不追加新用户消息，直接用当前消息列表调用 LLM（用于 Agent 工具反馈循环）。"""
        return self._call_and_append()

    def _call_and_append(self) -> str:
        payload = {
            "messages": self.messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False
        }
        if self.model_name:
            payload["model"] = self.model_name

        self.logger.debug("请求payload: %s", json.dumps(payload, ensure_ascii=False))
        result = self._call_chat_api(payload)
        self.logger.debug("API响应: %s", json.dumps(result, ensure_ascii=False))

        assistant_message = result["choices"][0]["message"]["content"]
        self.messages.append({"role": "assistant", "content": assistant_message})
        self.logger.info("收到助手回复: %s", assistant_message[:50] + "..." if len(assistant_message) > 50 else assistant_message)

        return assistant_message

    def reset_conversation(self):
        """清空当前对话历史"""
        self.messages.clear()
        self.logger.info("对话历史已重置")

    def get_history(self) -> List[Dict[str, str]]:
        """
        获取当前对话历史的副本。

        :return: 包含所有消息的列表
        """
        return self.messages.copy()

    def set_model(self, model_name: str):
        """
        切换使用的模型。

        :param model_name: 新模型名称
        """
        self.model_name = model_name
        self.logger.info("模型切换为: %s", self.model_name)

    def set_base_url(self, base_url: str):
        """更新服务地址"""
        self.base_url = base_url.rstrip('/')
        self.logger.info("服务地址已更新为: %s", self.base_url)

    def describe_image(self, data_url: str, prompt: str = "请详细描述这张图片的内容",
                       max_tokens: int = 500, temperature: float = 0.1) -> str:
        """
        发送图片到多模态模型，获取文字描述。
        """
        if not data_url:
            raise ValueError("data_url 不能为空")

        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }]

        payload = {
            "model": self.model_name or "default",
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }

        self.logger.debug("describe_image 请求 (tokens=%d)", max_tokens)
        result = self._call_chat_api(payload)

        if "choices" in result and result["choices"]:
            description = result["choices"][0]["message"]["content"].strip()
            self.logger.info("图片描述: %s", description[:80] + ("..." if len(description) > 80 else ""))
            return description
        else:
            raise ValueError("图片描述响应格式异常")

    def __repr__(self):
        return f"<LMStudioChat base_url={self.base_url} model={self.model_name} history_len={len(self.messages)}>"


class LMSummaryModel:
    """摘要模型 — 支持 DeepSeek API 和本地 LMStudio 双后端，用于对话记忆压缩。"""

    SUMMARY_PROMPT = (
        "用至多两句话（不超过50字）概括下方对话的核心事实与结论，"
        "以AI视角描述。仅输出概括语句，不要引导词，不要标签，不要关键词。\n\n"
        "对话内容：\n"
    )

    def __init__(
        self,
        backend: str = None,
        base_url: str = None,
        api_key: str = None,
        model_name: str = None,
        summary_length: int = 100,
        timeout: int = 60,
        logger: Optional[logging.Logger] = None,
    ):
        from config import Config

        self.backend = backend or getattr(Config, 'MEMORY_SUMMARY_BACKEND', 'deepseek')
        self.model_name = model_name or Config.MEMORY_MODEL
        self.summary_length = summary_length
        self.timeout = timeout
        self.logger = logger or logging.getLogger(self.__class__.__name__)
        self._http_session = requests.Session()

        if self.backend == "deepseek":
            self.api_key = api_key or Config.DEEPSEEK_API_KEY
            self.base_url = "https://api.deepseek.com/v1"
        else:
            self.base_url = base_url or Config.LMSTUDIO_BASE_URL
            self.api_key = None

    def _call_llm(self, prompt: str, max_length: int, backend_name: str,
                   url: str, headers: dict, is_lmstudio: bool = False) -> str:
        """统一的 LLM 调用后端。"""
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_length,
            "temperature": 0.3,
            "stream": False,
        }

        for attempt in range(2 if is_lmstudio else 1):
            try:
                self.logger.debug("%s summary request → %s", backend_name, self.model_name)
                response = self._http_session.post(url, headers=headers, json=payload, timeout=self.timeout)
                response.raise_for_status()
                result = response.json()

                if "choices" in result and result["choices"]:
                    summary = result["choices"][0]["message"]["content"].strip()
                    if len(summary) > max_length * 2:
                        summary = summary[:max_length * 2].rstrip() + "..."
                    self.logger.info("%s 摘要: %s", backend_name,
                                     summary[:80] + ("..." if len(summary) > 80 else ""))
                    return summary
                else:
                    raise ValueError(f"{backend_name} 响应格式异常")
            except requests.exceptions.Timeout:
                self.logger.error("%s 摘要请求超时 (%d秒)", backend_name, self.timeout)
                raise
            except requests.exceptions.ConnectionError:
                self.logger.error("无法连接到 %s: %s", backend_name, self.base_url)
                raise
            except requests.exceptions.HTTPError as e:
                if is_lmstudio and attempt == 0 and self._is_no_model_error(e.response):
                    self.logger.info("摘要模型未加载，自动加载后重试……")
                    if self._auto_load_model():
                        continue
                self.logger.error("%s 摘要请求失败: %s", backend_name, str(e))
                raise
            except (KeyError, ValueError) as e:
                self.logger.error("%s 摘要响应解析失败: %s", backend_name, str(e))
                raise

    def summarize_text(self, text: str, max_length: Optional[int] = None) -> str:
        """生成摘要。根据 backend 自动选择 DeepSeek 或 LMStudio。"""
        if not text or not isinstance(text, str):
            raise ValueError("text 必须是非空字符串")

        if max_length is None:
            max_length = self.summary_length

        prompt = self.SUMMARY_PROMPT.strip() + "\n" + text
        self.logger.debug("生成摘要输入 (%d 字符)", len(text))

        if self.backend == "deepseek":
            url = f"{self.base_url}/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            }
            return self._call_llm(prompt, max_length, "DeepSeek", url, headers)
        else:
            url = f"{self.base_url}/v1/chat/completions"
            headers = {"Content-Type": "application/json"}
            return self._call_llm(prompt, max_length, "LMStudio", url, headers, is_lmstudio=True)

    def _auto_load_model(self) -> bool:
        return _load_lmstudio_model(self.base_url, self.model_name, "摘要模型")

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
