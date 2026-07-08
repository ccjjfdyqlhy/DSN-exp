
# DSN-exp/models.py
# UPD v3_260328

import requests
import json
import os
import logging
import threading
from collections import deque
from typing import List, Dict, Optional, Union


# 全局详细模式标志，由 /detail 命令切换
DETAIL_CHATS = False
DETAIL_ACTIONS = False


def toggle_detail_chats() -> bool:
    """切换聊天详细模式，返回切换后的状态"""
    global DETAIL_CHATS
    DETAIL_CHATS = not DETAIL_CHATS
    return DETAIL_CHATS


def toggle_detail_actions() -> bool:
    """切换动作详细模式，返回切换后的状态"""
    global DETAIL_ACTIONS
    DETAIL_ACTIONS = not DETAIL_ACTIONS
    return DETAIL_ACTIONS


def _is_no_model_error(response) -> bool:
    """检查 HTTP 400 错误是否因 'No models loaded' 导致"""
    if response is None or response.status_code != 400:
        return False
    try:
        body = response.text or ""
        return "no model" in body.lower() or "No models loaded" in body
    except Exception:
        return False






    # load a model on lmstudio
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






    # unload a model from lmstudio
def _unload_lmstudio_model(base_url: str, model_name: str) -> bool:
    """卸载 LMStudio 模型。POST /api/v1/models/unload，body: {"instance_id": model_name}"""
    if not model_name:
        return False
    try:
        logger = logging.getLogger("models")
        logger.info("正在卸载模型: %s", model_name)
        resp = requests.post(
            f"{base_url}/api/v1/models/unload",
            json={"instance_id": model_name},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("instance_id") == model_name or data.get("model") == model_name:
            logger.info("模型已卸载: %s", model_name)
            return True
        logger.info("模型卸载完成: %s", model_name)
        return True
    except Exception as e:
        logging.getLogger("models").error("卸载模型失败 (%s): %s", model_name, e)
        return False

class OpenAIChat:
    """
    OpenAI 兼容 API 聊天客户端类，支持多轮对话历史管理。
    适用于 DeepSeek、OpenAI、vLLM 等所有兼容 OpenAI 格式的 API。
    使用示例：
        chat = OpenAIChat(api_key="your-key")
        reply = chat.send_message("你好")
        print(reply)
        chat.reset_conversation()
    """

    # 默认模型
    DEFAULT_MODEL = "deepseek-v4-flash"
    REASONER_MODEL = "deepseek-v4-pro"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        api_url: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
        timeout: int = 114514,
        use_reasoner: bool = False,
        max_history: int = 0,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        extra_body: Optional[dict] = None,
    ):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "API密钥必须提供，可通过参数传入或设置环境变量OPENAI_API_KEY"
            )
        from config import Config
        self.model = model
        raw = api_url or Config.OPENAI_API_BASE
        if raw and "/chat/completions" not in raw:
            self.api_url = f"{raw.rstrip('/')}/chat/completions"
        else:
            self.api_url = raw
        self.timeout = timeout
        self.use_reasoner = use_reasoner
        self.max_history = max_history
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._extra_body = extra_body or {}
        self.messages: List[Dict[str, str]] = []
        self.last_usage = None
        self.last_model = self.model
        self._last_message: Optional[dict] = None

        if logger is not None:
            self.logger = logger
        else:
            self.logger = logging.getLogger(self.__class__.__name__)
            self.logger.setLevel(logging.INFO)

        if use_reasoner:
            self.model = self.REASONER_MODEL

        self.logger.info("OpenAIChat客户端初始化完成，模型：%s", self.model)

    def send_message(self, message: str, tools: list[dict] = None,
                     tool_choice: str = "auto",
                     extra_body: Optional[dict] = None) -> str:
        if not message or not isinstance(message, str):



        # send a message to the chat model
            raise ValueError("消息内容必须为非空字符串")
        self.messages.append({"role": "user", "content": message})
        return self._call_and_append(tools=tools, tool_choice=tool_choice,
                                     extra_body=extra_body)

    def continue_conversation(self, tools: list[dict] = None,
                              tool_choice: str = "auto",
                              extra_body: Optional[dict] = None) -> str:
        return self._call_and_append(tools=tools, tool_choice=tool_choice,
                                     extra_body=extra_body)

    @property
    def last_tool_calls(self) -> Optional[list[dict]]:
        msg = self._last_message
        if msg and msg.get("tool_calls"):





        # get tool calls from the last assistant response
        # continue the conversation with more context
            return msg["tool_calls"]
        return None

    def _call_and_append(self, tools=None, tool_choice="auto",
                         extra_body: Optional[dict] = None) -> str:
        self.logger.info("发送请求，消息数: %d", len(self.messages))

        if DETAIL_CHATS:
            print("\n" + "=" * 60)
            print("📤 [OpenAI] 发送内容:")
            print("=" * 60)
            for i, msg in enumerate(self.messages):



        # call the api and append the result to history
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                print(f"\n[{i}] {role}:")
                print(content)
            print("=" * 60)

        if self.max_history > 0 and len(self.messages) > self.max_history:
            system_msgs = [m for m in self.messages if m.get("role") == "system"]
            other_msgs = [m for m in self.messages if m.get("role") != "system"]
            if other_msgs:
                other_msgs = other_msgs[-(self.max_history - len(system_msgs)):]
            self.messages = system_msgs + other_msgs
            self.logger.info("上下文裁剪后消息数: %d", len(self.messages))

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": self.messages,
            "stream": False
        }
        if self._max_tokens is not None:
            payload["max_tokens"] = self._max_tokens
        if self._temperature is not None:
            payload["temperature"] = self._temperature
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        body = dict(self._extra_body)
        if extra_body:
            body.update(extra_body)
        if body:
            payload.update(body)

        try:
            self.logger.debug("请求payload: %s", json.dumps(payload, ensure_ascii=False)[:500])
            response = requests.post(
                self.api_url, headers=headers, json=payload, timeout=self.timeout)
            response.raise_for_status()
            result = response.json()
            self.logger.debug("API响应: %s", json.dumps(result, ensure_ascii=False)[:500])

            self.last_usage = result.get("usage")
            self.last_model = result.get("model", self.model)

            msg = result["choices"][0]["message"]
            self._last_message = msg

            # 原生 tool call 模式：assistant 消息可能包含 tool_calls
            if msg.get("tool_calls"):
                self.messages.append({
                    "role": "assistant",
                    "content": msg.get("content"),
                    "tool_calls": msg["tool_calls"],
                })
                content = msg.get("content") or ""
                if content:
                    self.logger.info("收到助手回复(含tool_call): %s",
                                     content[:50] + "..." if len(content) > 50 else content)
                return content
            else:
                assistant_message = msg["content"]
                self.messages.append({"role": "assistant", "content": assistant_message})
                self.logger.info("收到助手回复: %s",
                                 assistant_message[:50] + "..." if len(assistant_message) > 50 else assistant_message)

                if DETAIL_CHATS:
                    print("\n📥 [OpenAI] 生成内容:")
                    print("-" * 60)
                    print(assistant_message)
                    print("-" * 60)

                return assistant_message

        except requests.exceptions.Timeout:
            self.logger.error("请求超时（%d秒）", self.timeout)
            raise
        except requests.exceptions.RequestException as e:
            _body = ""
            if e.response is not None:
                try:
                    _body = e.response.text[:2000]
                except Exception:
                    pass
            self.logger.error("网络请求失败: %s\n响应体: %s", str(e), _body if _body else "(无)")
            raise
        except KeyError as e:
            self.logger.error("响应格式异常，缺少字段: %s", str(e))
            raise ValueError("API返回的数据格式不正确") from e
        except json.JSONDecodeError as e:
            self.logger.error("JSON解析失败: %s", str(e))
            raise

    def reset_conversation(self):



        # reset the conversation history
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






        # set the model name to use
        # get the conversation history
        """
        切换使用的模型。

        :param model: 新模型名称，如"deepseek-reasoner"
        """
        self.model = model
        self.logger.info("模型切换为: %s", self.model)

    def set_api_key(self, api_key: str):



        # set the api key for the model client
        """更新API密钥"""
        self.api_key = api_key
        self.logger.info("API密钥已更新")

    def __repr__(self):
        return f"<OpenAIChat model={self.model} history_len={len(self.messages)}>"


class LMStudioChat:
    """
    本地 LMStudio 聊天客户端类，支持多轮对话历史管理。
    与 OpenAIChat 接口兼容，可作为主模型的替代方案。
    """

    def __init__(
        self,
        base_url: str = "http://localhost:4501",
        model_name: str = None,
        timeout: int = 300,
        logger: Optional[logging.Logger] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        managed: bool = True,
    ):
        """
        初始化 LMStudio 聊天客户端。

        :param base_url: LMStudio 服务地址
        :param model_name: 模型名称，若为None则使用服务器默认模型
        :param timeout: 请求超时时间（秒）
        :param logger: 日志记录器实例
        :param temperature: 生成温度
        :param max_tokens: 最大生成token数
        :param managed: 是否由 ModelScheduler 管理模型加载/卸载
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

        # 注册到 ModelScheduler
        self._scheduler = None
        if managed and self.model_name:
            from .scheduler import ModelScheduler
            self._scheduler = ModelScheduler.get_instance()
            self._scheduler.register(
                model_name=self.model_name,
                base_url=self.base_url,
                load_fn=lambda m=self.model_name, b=self.base_url: _load_lmstudio_model(b, m, "LMStudio 模型"),
                unload_fn=lambda m=self.model_name, b=self.base_url: _unload_lmstudio_model(b, m),
            )

        self.logger.info("LMStudioChat客户端初始化完成，地址：%s，模型：%s", self.base_url, self.model_name or "默认")

    def _ensure_model_loaded(self) -> bool:
        return _load_lmstudio_model(self.base_url, self.model_name, "LMStudio 模型")

    # ---- 底层 API 调用（含自动加载重试） ----

    def _call_chat_api(self, payload: dict) -> dict:
        """调用 /v1/chat/completions。由 ModelScheduler 管理模型加载。"""
        if self._scheduler:
            with self._scheduler.use(self.model_name, timeout=self.timeout):



        # ensure the lmstudio model is loaded
                return self._do_call_chat_api(payload)
        return self._do_call_chat_api(payload)

    def _do_call_chat_api(self, payload: dict) -> dict:
        """原始 HTTP 调用，含自动加载重试（managed=False 时的回退路径）"""
        url = f"{self.base_url}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}

        for attempt in range(2):



        # actually make the http call to the chat api
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
        # 详细模式：显示完整发送内容
        if DETAIL_CHATS:
            print("\n" + "=" * 60)
            print("📤 [LMStudio] 发送内容:")
            print("=" * 60)
            for i, msg in enumerate(self.messages):
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                print(f"\n[{i}] {role}:")
                print(content)
            print("=" * 60)

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

        # 详细模式：显示完整生成内容
        if DETAIL_CHATS:
            print("\n📥 [LMStudio] 生成内容:")
            print("-" * 60)
            print(assistant_message)
            print("-" * 60)

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



        # set the base url for the model api
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

    def describe_images(self, images: list[dict], prompt: str = None,
                        max_tokens: int = 1024, temperature: float = 0.1) -> str:
        """
        一次传入多张图片，返回合并描述表。

        :param images: [{"filename": "page1.png", "data_url": "data:image/png;base64,..."}, ...]
        :param prompt: 描述提示词，默认自动生成（含文件名信息）
        :param max_tokens: 最大输出 token
        :return: 格式化表格文本，包含原始文件名和描述
        """
        if not images:
            return ""

        if prompt is None:
            filenames = ", ".join([img.get("filename", f"图{i+1}") for i, img in enumerate(images)])
            prompt = (
                f"以下是 {len(images)} 张图片，文件名依次为: {filenames}。\n"
                f"请按顺序逐张描述每张图片的内容。\n"
                f"输出格式：为每张图片输出一行，格式为 '文件名: 描述内容'"
            )

        content_parts = [{"type": "text", "text": prompt}]
        for img in images:
            data_url = img.get("data_url", "")
            if data_url:
                content_parts.append({"type": "image_url", "image_url": {"url": data_url}})

        messages = [{"role": "user", "content": content_parts}]

        payload = {
            "model": self.model_name or "default",
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }

        self.logger.debug("describe_images 请求 (%d 张图)", len(images))
        result = self._call_chat_api(payload)

        if "choices" in result and result["choices"]:
            descriptions = result["choices"][0]["message"]["content"].strip()
            self.logger.info("多图描述: %s", descriptions[:120] + ("..." if len(descriptions) > 120 else ""))
            return descriptions
        else:
            raise ValueError("多图描述响应格式异常")

    def classify_image(self, data_url: str, max_tokens: int = 50,
                       temperature: float = 0.0) -> str:
        """
        判断图片类型。

        :param data_url: 图片 base64 data URL
        :return: "document" / "photo" / "mixed"
        """
        if not data_url:
            return "photo"

        prompt = (
            "请判断这张图片的类型，只回答一个单词：\n"
            "- 如果图片内容是印刷文档、手写文字、试卷、书籍、论文等 → 回答 document\n"
            "- 如果图片是风景照、人物照、实物照片、截图等非文档内容 → 回答 photo\n"
            "- 如果图片同时包含文档和嵌入的图片/照片 → 回答 mixed\n"
            "只回答 document、photo 或 mixed，不要其他内容。"
        )

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

        self.logger.debug("classify_image 请求")
        result = self._call_chat_api(payload)

        if "choices" in result and result["choices"]:
            answer = result["choices"][0]["message"]["content"].strip().lower()
            if "document" in answer:
                return "document"
            elif "mixed" in answer:
                return "mixed"
            elif "photo" in answer:
                return "photo"
            return "document"
        return "document"

    def __repr__(self):
        return f"<LMStudioChat base_url={self.base_url} model={self.model_name} history_len={len(self.messages)}>"


class EmbeddingClient:
    """
    文本嵌入客户端 — 调用本地 LMStudio /v1/embeddings。

    用法:
        ec = EmbeddingClient()
        vec = ec.embed("三角函数诱导公式")  # → list[float] (768维)
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        dims: int = 768,
        timeout: int = 60,
        logger: Optional[logging.Logger] = None,
    ):
        from config import Config

        self.base_url = (base_url or Config.LMSTUDIO_BASE_URL).rstrip("/")
        self.model_name = model_name or Config.MEMORY_EMBEDDING_MODEL
        self.dims = dims
        self.timeout = timeout
        self.logger = logger or logging.getLogger(self.__class__.__name__)
        self._http_session = requests.Session()

        # 并发加载门控: 多线程共享同一个模型时只加载一次
        self._load_lock = threading.Lock()
        self._model_ready = threading.Event()
        self._model_load_failed = False

    def embed(self, text: str) -> Optional[list[float]]:
        """对单段文本生成嵌入向量。失败时返回 None。"""
        if not text or not isinstance(text, str):
            return None
        result = self._call_embed_api([text])
        if result:
            return result[0]
        return None

    def embed_batch(self, texts: list[str]) -> Optional[list[list[float]]]:
        """批量生成嵌入向量。失败时返回 None。"""
        if not texts:
            return None
        return self._call_embed_api(texts)

    def _call_embed_api(self, texts: list[str]) -> Optional[list[list[float]]]:
        """统一调用 /v1/embeddings (并发安全的模型加载)。"""
        url = f"{self.base_url}/v1/embeddings"
        headers = {"Content-Type": "application/json"}

        def _do_request():






            # make an http request with retry logic
        # call the embedding api and return embeddings
            payload = {"model": self.model_name, "input": texts}
            self.logger.debug("embedding 请求 → %s (%d 段)", self.model_name, len(texts))
            response = self._http_session.post(url, headers=headers, json=payload, timeout=self.timeout)
            response.raise_for_status()
            result = response.json()
            if "data" not in result:
                self.logger.error("embedding 响应缺少 data 字段")
                return None
            data = sorted(result["data"], key=lambda x: x["index"])
            vectors = [item["embedding"] for item in data]
            self.logger.debug("embedding 返回 %d 条, 维度 %d", len(vectors), len(vectors[0]) if vectors else 0)
            return vectors

        # 快速路径
        if self._model_ready.is_set():
            try:
                return _do_request()
            except requests.exceptions.HTTPError as e:
                if _is_no_model_error(e.response):
                    self.logger.info("embedding 模型被卸载，标记为未就绪")
                    self._model_ready.clear()
                else:
                    self.logger.error("embedding 请求失败: %s", str(e))
                    return None

        # 门控加载: 先试请求，模型已就绪则不触发 load
        if not self._model_load_failed:
            with self._load_lock:
                if self._model_ready.is_set() or self._model_load_failed:
                    return _do_request()
                try:
                    result = _do_request()
                    self._model_ready.set()
                    return result
                except requests.exceptions.HTTPError as e:
                    if _is_no_model_error(e.response):
                        self.logger.info("embedding 模型未加载，正在加载 %s ...", self.model_name)
                        if self._ensure_model_loaded():
                            self._model_ready.set()
                            self.logger.info("embedding 模型加载完成")
                        else:
                            self.logger.error("embedding 模型加载失败，本批次不再重试")
                            self._model_load_failed = True
                    else:
                        self.logger.error("embedding 请求失败: %s", str(e))
                        return None

        return _do_request()

    def _ensure_model_loaded(self) -> bool:
        return _load_lmstudio_model(self.base_url, self.model_name, "Embedding 模型")

    def __repr__(self):
        return f"<EmbeddingClient base_url={self.base_url} model={self.model_name}>"


class LMSummaryModel:
    """摘要模型 — 支持 DeepSeek API 和本地 LMStudio 双后端，用于对话记忆压缩。"""

    SUMMARY_PROMPT = (
        "你是下方对话中标记为[助手/AI]的一方。\n"
        "现在用第一人称(我=助手)概括这段对话：\n\n"
        "规则：\n"
        "1. 先描述用户说了什么/做了什么\n"
        "2. 再写你(助手)是如何回应的\n"
        "3. 禁止编造对话中不存在的事实\n"
        "4. 使用具体动词，避免笼统的'承认/确认'\n"
        "5. 1-2 句话，总字数 ≤ 100 字\n"
        "6. 仅输出概括，无任何引导语\n\n"
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

        self.backend = backend or getattr(Config, 'MEMORY_SUMMARY_BACKEND', 'openai')
        self.model_name = model_name or Config.MEMORY_MODEL
        self.summary_length = summary_length
        self.timeout = timeout
        self.logger = logger or logging.getLogger(self.__class__.__name__)
        self._http_session = requests.Session()

        # 并发加载门控: 多线程共享同一个模型时只加载一次
        self._load_lock = threading.Lock()
        self._model_ready = threading.Event()
        self._model_load_failed = False

        # 摘要上下文: 保持最近 10 次摘要的对话+结果
        self._summary_context = deque(maxlen=10)

        if self.backend == "openai":
            self.api_key = api_key or Config.OPENAI_API_KEY
            self.base_url = Config.OPENAI_API_BASE
        else:
            self.base_url = base_url or Config.LMSTUDIO_BASE_URL
            self.api_key = None




        # call the llm with a prompt and return the response
    def _call_llm(self, prompt: str, max_length: int, backend_name: str,
                   url: str, headers: dict, is_lmstudio: bool = False) -> str:
        """统一的 LLM 调用后端 (并发安全的模型加载)。"""
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_length,
            "temperature": 0.1,
            "stream": False,
        }

        scheduler = None
        if is_lmstudio and self.model_name:
            from .scheduler import ModelScheduler
            scheduler = ModelScheduler.get_instance()
            scheduler.register(
                model_name=self.model_name,
                base_url=self.base_url,
                load_fn=lambda: _load_lmstudio_model(self.base_url, self.model_name, "摘要模型"),
                unload_fn=lambda: _unload_lmstudio_model(self.base_url, self.model_name),
            )

        def _do_request():
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
            raise ValueError(f"{backend_name} 响应格式异常")

        if scheduler:
            with scheduler.use(self.model_name, timeout=self.timeout):
                return _do_request()

        # 快速路径: 模型已就绪，直接请求
        if is_lmstudio and self._model_ready.is_set():
            try:
                return _do_request()
            except requests.exceptions.HTTPError as e:
                if self._is_no_model_error(e.response):
                    self.logger.info("摘要模型被卸载，标记为未就绪")
                    self._model_ready.clear()
                else:
                    raise

        # 门控加载: 先试请求，模型已就绪则不触发 load
        if is_lmstudio and not self._model_load_failed:
            with self._load_lock:
                if self._model_ready.is_set() or self._model_load_failed:
                    return _do_request()
                try:
                    result = _do_request()
                    self._model_ready.set()
                    return result
                except requests.exceptions.HTTPError as e:
                    if self._is_no_model_error(e.response):
                        self.logger.info("摘要模型未加载，正在加载 %s ...", self.model_name)
                        if self._auto_load_model():
                            self._model_ready.set()
                            self.logger.info("摘要模型加载完成")
                        else:
                            self.logger.error("摘要模型加载失败，本批次不再重试")
                            self._model_load_failed = True
                    else:
                        raise

        return _do_request()

    def summarize_text(self, text: str, max_length: Optional[int] = None) -> str:
        """生成摘要。根据 backend 自动选择 DeepSeek 或 LMStudio。"""
        if not text or not isinstance(text, str):
            raise ValueError("text 必须是非空字符串")

        if max_length is None:
            max_length = self.summary_length

        prompt = self.SUMMARY_PROMPT.strip() + "\n" + text
        self.logger.debug("生成摘要输入 (%d 字符)", len(text))

        if self.backend == "openai":
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
        """根据消息列表生成一条整体摘要（带最近 10 次上下文）。"""
        combined = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")
            if not isinstance(content, str):



        # auto-load a model if not already loaded
                continue
            if role == "user":
                prefix = "[用户]"
            elif role == "assistant":
                prefix = "[助手]"
            else:
                prefix = role
            combined.append(f"{prefix}:{content}")

        current_text = "\n".join(combined)

        # 拼接上下文（仅含历史对话原文+摘要结果，不含历史上下文本身）
        if self._summary_context:
            ctx_parts = ["\n先前已完成的摘要："]
            for i, (orig_text, ctx_result) in enumerate(self._summary_context, 1):
                ctx_parts.append(f"\n--- 先前摘要 {i} ---\n{orig_text}\n→ 结果为：{ctx_result}")
            ctx_parts.append("\n\n请继续对下方对话生成摘要。\n")
            full_text = "".join(ctx_parts) + current_text
        else:
            full_text = current_text

        result = self.summarize_text(full_text, max_length=max_length)

        # 存储仅当前对话文本（不含历史上下文）到历史
        self._summary_context.append((current_text, result))

        return result


class OCRModel:
    """
    deepseek-ocr 客户端。纯视觉→markdown 模型，无文本提示。

    用法:
        ocr = OCRModel()
        md = ocr.ocr(data_url)         # 单张 → markdown
        results = ocr.ocr_batch([...]) # 批量 → [{filename, markdown}]
        ocr.unload()                   # 手动卸载

    配置:
        OCR_MODEL: 模型名 (默认 "deepseek-ocr")
        OCR_BASE_URL: LMStudio 地址 (默认 "http://localhost:4502")
        OCR_UNLOAD_AFTER_USE: 用完自动卸载（managed=True 时由 Scheduler 接管）
    """

    def __init__(self, base_url: str = None, model_name: str = None,
                 auto_load: bool = True, managed: bool = True):
        from config import Config

        self.base_url = (base_url or Config.OCR_BASE_URL).rstrip("/")
        self.model_name = model_name or Config.OCR_MODEL
        self.logger = logging.getLogger(self.__class__.__name__)
        self._http_session = requests.Session()
        self._load_lock = threading.Lock()
        self._model_ready = threading.Event()

        # 注册到 ModelScheduler（按需加载，不占常驻名额）
        self._scheduler = None
        if managed and self.model_name:
            from .scheduler import ModelScheduler
            self._scheduler = ModelScheduler.get_instance()
            self._scheduler.register(
                model_name=self.model_name,
                base_url=self.base_url,
                load_fn=lambda m=self.model_name, b=self.base_url:
                    _load_lmstudio_model(b, m, "OCR 模型", timeout=300),
                unload_fn=lambda m=self.model_name, b=self.base_url:
                    _unload_lmstudio_model(b, m),
            )

        if not managed and auto_load and self.model_name:
            self._ensure_loaded()

    def ocr(self, data_url: str, max_tokens: int = 4096) -> str:
        """对单张图片执行 OCR，返回 markdown 文本。"""
        results = self.ocr_batch([{"filename": "image", "data_url": data_url}], max_tokens)
        return results[0]["markdown"] if results else ""

    def ocr_batch(self, images: list[dict], max_tokens: int = 4096) -> list[dict]:
        """
        批量 OCR。

        :param images: [{filename, data_url}, ...]
        :return: [{filename, markdown}, ...]

        若 OCR_UNLOAD_AFTER_USE=true 且 managed=False，完成所有处理后自动卸载。
        managed=True 时由 ModelScheduler 按需换入换出。
        """
        from config import Config
        results = []
        for img in images:
            filename = img.get("filename", "unknown")
            text = self._ocr_single(img.get("data_url", ""), max_tokens)
            results.append({"filename": filename, "markdown": text})
        self.logger.info("OCR 完成: %d 张 → %d 条结果", len(images), len(results))
        if not self._scheduler and Config.OCR_UNLOAD_AFTER_USE:
            self.logger.info("OCR_UNLOAD_AFTER_USE=true，卸载模型")
            self.unload()
        return results




        # run ocr on a single image
    def _ocr_single(self, data_url: str, max_tokens: int = 4096) -> str:
        if not data_url:
            return ""

        messages = [{
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": data_url}}],
        }]

        payload = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0,
            "stream": False,
        }

        url = f"{self.base_url}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}

        def _do_request():
            resp = self._http_session.post(url, headers=headers, json=payload, timeout=300)
            resp.raise_for_status()
            result = resp.json()
            if "choices" in result and result["choices"]:
                return result["choices"][0]["message"]["content"].strip()
            return ""

        # managed 路径：由 Scheduler 确保模型已加载
        if self._scheduler:
            with self._scheduler.use(self.model_name, timeout=300, immediate=True):
                return _do_request()

        # 传统路径：手动管理加载/卸载
        if self._model_ready.is_set():
            try:
                return _do_request()
            except requests.exceptions.HTTPError as e:
                if _is_no_model_error(e.response):
                    self._model_ready.clear()
                else:
                    self.logger.error("OCR 请求失败: %s", e)
                    return ""

        with self._load_lock:
            if self._model_ready.is_set():
                return _do_request()
            try:
                result = _do_request()
                self._model_ready.set()
                return result
            except requests.exceptions.HTTPError as e:
                if _is_no_model_error(e.response):
                    if self._ensure_loaded():
                        self._model_ready.set()
                        try:
                            return _do_request()
                        except Exception:
                            return ""
                else:
                    self.logger.error("OCR 请求失败: %s", e)
                    return ""

        return ""

    def _ensure_loaded(self) -> bool:
        return _load_lmstudio_model(self.base_url, self.model_name, "OCR 模型", timeout=300)

    def unload(self) -> bool:
        self._model_ready.clear()
        return _unload_lmstudio_model(self.base_url, self.model_name)

    def __repr__(self):



        # ensure a model is loaded on lmstudio
        return f"<OCRModel base_url={self.base_url} model={self.model_name}>"


class VisionModel:
    """
    通用视觉多模态模型客户端。兼容 OpenAI 格式的视觉 API（如 GLM-4.6V、GPT-4V 等）。

    用法:
        vm = VisionModel()
        desc = vm.ask(image_data_url, prompt="描述这张图片")
        desc = vm.ask(image_data_url, prompt="判一下这题", extra_body={"thinking": {"type": "enabled"}})

    配置:
        VISION_API_KEY: API 密钥
        VISION_API_BASE: API 地址 (默认 "https://open.bigmodel.cn/api/paas/v4")
        VISION_MODEL_NAME: 模型名 (默认 "glm-4.6v")
    """

    def __init__(self, api_key: str = None, base_url: str = None,
                 model_name: str = None, timeout: int = 120):
        from config import Config

        self.api_key = api_key or Config.VISION_API_KEY
        self.base_url = (base_url or Config.VISION_API_BASE).rstrip("/")
        self.model_name = model_name or Config.VISION_MODEL_NAME
        self.timeout = timeout
        self.logger = logging.getLogger(self.__class__.__name__)

        if not self.api_key:
            self.logger.warning("VISION_API_KEY 未配置，视觉模型请求将无法通过需要认证的 API")

    @staticmethod
    def encode_image(image_path: str, mime_type: str = "image/png") -> str:
        """读取本地图片并转为 Base64 data URL"""
        import base64
        if not os.path.isfile(image_path):
            raise FileNotFoundError(f"图片文件不存在: {image_path}")
        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")
        return f"data:{mime_type};base64,{image_data}"

    def ask(self, data_url: str, prompt: str = "请详细描述这张图片的内容",
            max_tokens: int = 2048, temperature: float = 0.1,
            extra_body: dict = None) -> str:
        """
        发送图片 + 文本提示到视觉模型。

        :param data_url: 图片的 Base64 data URL
        :param prompt: 文本提示
        :param max_tokens: 最大输出 token
        :param temperature: 生成温度
        :param extra_body: 额外请求体参数（如 GLM 的 thinking）
        :return: 模型回复文本
        """
        if not data_url:
            raise ValueError("data_url 不能为空")

        messages = [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": data_url}},
                {"type": "text", "text": prompt},
            ],
        }]

        payload = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        if extra_body:
            payload.update(extra_body)

        url = f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        self.logger.info("VisionModel 请求: model=%s, prompt=%s",
                         self.model_name, prompt[:60] + ("..." if len(prompt) > 60 else ""))

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            result = resp.json()
        except requests.exceptions.Timeout:
            self.logger.error("VisionModel 请求超时 (%ds)", self.timeout)
            raise
        except requests.exceptions.HTTPError as e:
            self.logger.error("VisionModel HTTP %d: %s",
                              e.response.status_code if e.response else 0,
                              e.response.text[:500] if e.response else str(e))
            raise
        except Exception as e:
            self.logger.error("VisionModel 请求失败: %s", e)
            raise

        if "choices" in result and result["choices"]:
            text = result["choices"][0]["message"]["content"].strip()
            self.logger.info("VisionModel 回复: %s", text[:80] + ("..." if len(text) > 80 else ""))
            return text
        else:
            self.logger.error("VisionModel 响应格式异常: %s", str(result)[:300])
            raise ValueError("视觉模型响应格式异常")

    def ask_raw(self, messages: list, max_tokens: int = 2048,
                temperature: float = 0.1, extra_body: dict = None) -> dict:
        """
        低级接口：直接发送自定义消息列表，返回完整 API 响应。

        :param messages: OpenAI 格式的消息列表
        :return: API 原始响应 dict
        """
        payload = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        if extra_body:
            payload.update(extra_body)

        url = f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        self.logger.debug("VisionModel ask_raw: %s", str(payload)[:200])
        resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    # ----- OCR / 文档分类（用于 VISION_OVERRIDE 模式） -----

    def classify_image(self, data_url: str, max_tokens: int = 100) -> str:
        """
        判断图片类型：document / photo / mixed。
        """
        if not data_url:
            return "document"
        prompt = (
            "这张图片是文档（试卷、合同、书本、笔记等）还是照片（风景、人物、物品实拍等）？"
            "只回答一个词：document / photo / mixed"
        )
        try:
            text = self.ask(data_url, prompt=prompt, max_tokens=max_tokens, temperature=0)
            text = text.strip().lower()
            if "mixed" in text:
                return "mixed"
            if "photo" in text or "照片" in text:
                return "photo"
            return "document"
        except Exception:
            return "document"

    def ocr_md(self, data_url: str, max_tokens: int = 4096) -> str:
        """
        将图片转为 Markdown 文本（替代 deepseek-ocr + 2md API）。
        """
        if not data_url:
            return ""
        prompt = (
            "请完整提取这张文档图片中的所有文字内容，输出为 Markdown 格式。"
            "保留原始排版结构（标题、列表、表格等），不要遗漏任何文字。"
        )
        try:
            return self.ask(data_url, prompt=prompt, max_tokens=max_tokens, temperature=0)
        except Exception as e:
            self.logger.error("ocr_md 失败: %s", e)
            return ""

    def ocr_md_batch(self, images: list[dict], max_tokens: int = 4096) -> list[dict]:
        """
        批量将图片转为 Markdown。

        :param images: [{filename, data_url}, ...]
        :return: [{filename, markdown}, ...]
        """
        results = []
        for img in images:
            filename = img.get("filename", "unknown")
            md = self.ocr_md(img.get("data_url", ""), max_tokens)
            results.append({"filename": filename, "markdown": md})
            self.logger.info("ocr_md_batch: %s → %d chars", filename, len(md))
        return results

    def __repr__(self):
        return f"<VisionModel base_url={self.base_url} model={self.model_name}>"


class GradingModel(VisionModel):
    """
    视觉判分模型 — VisionModel 的子类，专用于试卷批改场景。

    从已作答的试卷图片中自动分离题目原文、题图描述和学生答案，
    以标准 AnswerSheet 格式输出。

    用法:
        gm = GradingModel()
        sheet = gm.extract_answer_sheet(data_url)
        sheets = gm.extract_answer_sheet_batch([{filename, data_url}, ...])
    """

    def extract_answer_sheet(self, data_url: str, max_tokens: int = 8192) -> dict:
        """
        从一页已作答的试卷图片中提取所有题目和学生答案。

        :param data_url: 图片的 Base64 data URL
        :param max_tokens: 最大输出 token
        :return: {
            "pages": [{
                "page_number": 1,
                "questions": [{
                    "question_index": 0,
                    "question_text": "题目原文（含选项）",
                    "image_description": "题图描述，无图则为 null",
                    "student_answer": "学生填写的答案",
                }]
            }]
        }
        """
        if not data_url:
            return {"pages": []}

        prompt = (
            "你是一名试卷批改助手。下面是一张已作答的试卷图片。\n\n"
            "请仔细识别图片中所有的题目和学生的作答，按以下 JSON 格式输出：\n"
            "{\n"
            '  "pages": [\n'
            "    {\n"
            '      "page_number": 1,\n'
            '      "questions": [\n'
            "        {\n"
            '          "question_index": 0,\n'
            '          "question_text": "题目原文（包括所有选项 A/B/C/D）",\n'
            '          "image_description": "如果题目配有图表/图片，请描述其内容；无图则为 null",\n'
            '          "student_answer": "学生填写的答案"\n'
            "        }\n"
            "      ]\n"
            "    }\n"
            "  ]\n"
            "}\n\n"
            "要求：\n"
            "1. 题目原文和学生答案严格分开，不要混在一起\n"
            "2. 题目有配图（几何图、函数图、表格等）时在 image_description 中描述其关键信息\n"
            "3. 学生写了多个答案时以最终/最明显的答案为准\n"
            "4. 只返回 JSON，不要包含其他内容\n"
            "5. 确保题目原文完整，选择题保留 A/B/C/D 选项"
        )

        try:
            text = self.ask(data_url, prompt=prompt, max_tokens=max_tokens, temperature=0.1)
            return self._parse_answer_sheet(text)
        except Exception as e:
            self.logger.error("extract_answer_sheet 失败: %s", e)
            return {"pages": [], "error": str(e)}

    def extract_answer_sheet_batch(self, images: list[dict], max_tokens: int = 8192) -> dict:
        """
        批量处理多页答题卡，合并为一个 answer_sheet。

        :param images: [{"filename": str, "data_url": str}, ...]
        :return: {"pages": [...]}
        """
        all_pages = []
        for i, img in enumerate(images):
            filename = img.get("filename", f"page_{i}")
            data_url = img.get("data_url", "")
            if not data_url:
                continue
            page_result = self.extract_answer_sheet(data_url, max_tokens)
            pages = page_result.get("pages", [])
            for p in pages:
                p["source_file"] = filename
            all_pages.extend(pages)

        return {"pages": all_pages, "total_pages": len(all_pages)}

    @staticmethod
    def _parse_answer_sheet(text: str) -> dict:
        text = text.strip()
        if "```" in text:
            lines = text.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                if line.strip().startswith("```"):
                    if in_block:
                        break
                    in_block = True
                    continue
                if in_block:
                    json_lines.append(line)
            text = "\n".join(json_lines)
        import json as _json
        try:
            return _json.loads(text)
        except _json.JSONDecodeError:
            return {"pages": [], "error": f"JSON 解析失败: {text[:300]}"}
