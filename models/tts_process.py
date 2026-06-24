# tts_process_model.py
# TTSProcessModel — 对主模型输出进行 TTS 友好化处理，调用本地 LMStudio 模型
# 两阶段处理：本地正则预处理 + LLM 语义转换（数字/专有词汇中文化）

from __future__ import annotations

import re
import logging
import requests
from typing import Optional

from config import Config

logger = logging.getLogger(__name__)


class TTSProcessModel:
    """TTS 友好化处理模型 — 使用本地 LMStudio 后端，对主模型输出进行朗读优化。"""

    TTS_PROCESS_PROMPT = '''
你是一个专为语音合成做文本预处理的AI。你的任务是将输入文本转换为适合TTS朗读的自然形式，语言必须与原文完全一致。

规则：
0. 对于中文文本，绝对禁止输出汉语拼音或注音符号，必须输出纯中文汉字。即使是多音字、生僻字或方言词，也必须保持汉字原文。
1. 首先识别整段文本的主语言（中文 / English）。
2. 若为中文：
   - 阿拉伯数字转中文读法：整数如"123"→"一百二十三"，小数如"3.14"→"三点一四"，百分数"50%"→"百分之五十"
   - 电话号码、日期(2024-06-12)、版本号(v1.2.3)、ID编号保持原样
   - 金额："100元"→"一百元"，"3.5万"→"三点五万"
   - 中文里嵌入的缩写(API, HTTP, JSON)逐个字母读出，不要翻译成中文
   - 知名品牌转为中文通用读法（如"NVIDIA"→"英伟达"，"iPhone"→"苹果手机"）
3. 若为英文：
   - 阿拉伯数字保持原样（不要转为英文单词），TTS引擎会自动处理
   - 缩写保持大写原样以便逐个字母读出
   - 不要翻译任何内容到中文
   - 保持自然的英文标点和空格
   - 遇到英文专有术语简称（注意，特指那些不属于单词的，如AI、TTS、HTTP）全部翻译成中文对应的名称。
4. 若文本中同时包含中英双语：
   - 中文部分按规则2处理，英文部分按规则3处理
   - 不属于单词的专有术语：一致使用中文名称（如AI→人工智能，TTS→文本转语音，HTTP→超文本传输协议）
5. 保持原文的标点符号和换行结构，不要修改停顿和语气。
6. 仅输出转换后的纯文本，不要添加任何解释、说明或引导语。

需要你处理的文本：
'''

    _BOLD_RE = re.compile(r'\*\*(.+?)\*\*')
    _ITALIC_RE = re.compile(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)')
    _STRIKE_RE = re.compile(r'~~(.+?)~~')
    _CODE_INLINE_RE = re.compile(r'`([^`]+)`')
    _CODE_BLOCK_RE = re.compile(r'```[\s\S]*?```')
    _LINK_RE = re.compile(r'\[([^\]]+)\]\([^)]+\)')
    _URL_RE = re.compile(r'https?://\S+')
    _HEADING_RE = re.compile(r'^#{1,6}\s+', re.MULTILINE)
    _QUOTE_RE = re.compile(r'^>\s?', re.MULTILINE)
    _HR_RE = re.compile(r'^[-*_]{3,}\s*$', re.MULTILINE)
    _LIST_MARKER_RE = re.compile(r'^[\s]*[-*+]\s+', re.MULTILINE)
    _NUM_LIST_RE = re.compile(r'^[\s]*\d+[.)]\s+', re.MULTILINE)
    _HTML_TAG_RE = re.compile(r'<[^>]+>')

    _DIGITS_CN = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九"]

    @classmethod
    def _arabic_to_cn(cls, n: int) -> str:
        if n == 0:
            return cls._DIGITS_CN[0]
        if n <= 9:
            return cls._DIGITS_CN[n]
        if n <= 19:
            return "十" + (cls._DIGITS_CN[n - 10] if n > 10 else "")
        if n <= 99:
            tens = cls._DIGITS_CN[n // 10]
            ones = cls._DIGITS_CN[n % 10] if n % 10 else ""
            return tens + "十" + ones
        return str(n)

    @classmethod
    def _convert_num_marker(cls, match: re.Match) -> str:
        raw = match.group(0)
        num_str = re.search(r'\d+', raw).group(0)
        n = int(num_str)
        cn = cls._arabic_to_cn(n)
        return cn + "。"

    def __init__(
        self,
        base_url: str = None,
        model_name: str = None,
        timeout: int = None,
        temperature: float = None,
        max_tokens: int = None,
        logger: logging.Logger = None,
        enabled: bool = None,
    ):
        self.base_url = base_url or Config.LMSTUDIO_BASE_URL
        self.model_name = model_name or Config.TTS_PROCESS_MODEL
        self.timeout = timeout if timeout is not None else Config.TTS_PROCESS_TIMEOUT
        self.temperature = temperature if temperature is not None else Config.TTS_PROCESS_TEMPERATURE
        self.max_tokens = max_tokens if max_tokens is not None else Config.TTS_PROCESS_MAX_TOKENS
        self.logger = logger or logging.getLogger(self.__class__.__name__)
        self.enabled = enabled if enabled is not None else Config.TTS_PROCESS_ENABLED
        self._scheduler = None
        if self.enabled and self.model_name:
            from .scheduler import ModelScheduler
            from .clients import _load_lmstudio_model, _unload_lmstudio_model
            self._scheduler = ModelScheduler.get_instance()
            self._scheduler.register(
                model_name=self.model_name,
                base_url=self.base_url,
                load_fn=lambda m=self.model_name, b=self.base_url:
                    _load_lmstudio_model(b, m, "TTS 预处理模型", timeout=Config.MODEL_LOAD_TIMEOUT),
                unload_fn=lambda m=self.model_name, b=self.base_url:
                    _unload_lmstudio_model(b, m),
            )

        if self.enabled:
            self.logger.info("TTSProcessModel 已启用 | model=%s | base_url=%s", self.model_name, self.base_url)
        else:
            self.logger.info("TTSProcessModel 已禁用")

    def process_tts_text(self, text: str) -> str:
        """处理单行文本，返回 TTS 友好化文本。失败时安全回退到本地预处理结果。"""
        if not text or not isinstance(text, str):
            return text

        if not self.enabled:
            return text

        processed = self._local_preprocess(text)
        if not processed:
            return text

        if not self._needs_llm_processing(processed):
            return processed

        try:
            return self._call_lmstudio(processed)
        except Exception as e:
            self.logger.warning("TTS 预处理 LLM 调用失败，回退到本地预处理结果: %s", e)
            return processed

    # ---- 阶段一：本地正则预处理 ----

    def _needs_llm_processing(self, text: str) -> bool:
        return bool(re.search(r'\d', text)) or bool(re.search(r'[a-zA-Z]{2,}', text))

    def _local_preprocess(self, text: str) -> str:
        text = self._CODE_BLOCK_RE.sub('', text)
        text = self._CODE_INLINE_RE.sub('', text)
        text = self._LINK_RE.sub(r'\1', text)
        text = self._URL_RE.sub('', text)
        text = self._BOLD_RE.sub(r'\1', text)
        text = self._ITALIC_RE.sub(r'\1', text)
        text = self._STRIKE_RE.sub(r'\1', text)
        text = self._HEADING_RE.sub('', text)
        text = self._QUOTE_RE.sub('', text)
        text = self._HR_RE.sub('', text)
        text = self._LIST_MARKER_RE.sub('', text)
        text = self._NUM_LIST_RE.sub(self._convert_num_marker, text)
        text = self._HTML_TAG_RE.sub('', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    # ---- 阶段二：LMStudio 模型处理 ----

    def _call_lmstudio(self, text: str) -> str:
        prompt = self.TTS_PROCESS_PROMPT.strip() + "\n" + text
        url = f"{self.base_url}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "stream": False,
        }

        if self._scheduler:
            with self._scheduler.use(self.model_name, timeout=max(self.timeout, Config.MODEL_REQUEST_TIMEOUT)):
                return self._do_call_lmstudio(url, headers, payload, text)

        for attempt in range(2):
            try:
                self.logger.debug("TTS 预处理 LLM 请求 → %s", self.model_name)
                response = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
                response.raise_for_status()
                result = response.json()

                if "choices" in result and result["choices"]:
                    processed = result["choices"][0]["message"]["content"].strip()
                    if processed:
                        self.logger.debug("TTS 预处理完成: %s → %s", text[:40], processed[:60])
                        return processed
                raise ValueError("LMStudio 响应格式异常")
            except requests.exceptions.Timeout:
                self.logger.error("TTS 预处理请求超时 (%d秒)", self.timeout)
                raise
            except requests.exceptions.ConnectionError:
                self.logger.error("无法连接到 LMStudio: %s", self.base_url)
                raise
            except requests.exceptions.HTTPError as e:
                if attempt == 0 and self._is_no_model_error(e.response):
                    self.logger.info("TTS 预处理模型未加载，自动加载后重试……")
                    if self._auto_load_model():
                        continue
                self.logger.error("TTS 预处理请求失败: %s", str(e))
                raise
            except (KeyError, ValueError) as e:
                self.logger.error("TTS 预处理响应解析失败: %s", str(e))
                raise

        return text

    def _do_call_lmstudio(self, url: str, headers: dict, payload: dict, fallback: str) -> str:
        self.logger.debug("TTS 预处理 LLM 请求 → %s", self.model_name)
        response = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        response.raise_for_status()
        result = response.json()
        if "choices" in result and result["choices"]:
            processed = result["choices"][0]["message"]["content"].strip()
            if processed:
                self.logger.debug("TTS 预处理完成: %s → %s", fallback[:40], processed[:60])
                return processed
        raise ValueError("LMStudio 响应格式异常")

    def _auto_load_model(self) -> bool:
        if not self.model_name:
            self.logger.error("未配置 model_name，无法自动加载 LMStudio 模型")
            return False
        try:
            self.logger.info("正在加载 LMStudio 模型: %s", self.model_name)
            load_resp = requests.post(
                f"{self.base_url}/api/v1/models/load",
                json={"model": self.model_name},
                timeout=180,
            )
            load_resp.raise_for_status()
            result = load_resp.json()
            self.logger.info("模型加载完成 (%.1fs): %s", result.get("load_time_seconds", 0), self.model_name)
            return True
        except Exception as e:
            self.logger.error("自动加载 LMStudio 模型失败 (%s): %s", self.model_name, e)
            return False

    @staticmethod
    def _is_no_model_error(response) -> bool:
        if response is None or response.status_code != 400:
            return False
        try:
            body = response.text or ""
            return "no model" in body.lower() or "No models loaded" in body
        except Exception:
            return False
