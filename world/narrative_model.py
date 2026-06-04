# world/narrative_model.py
# NarrativeModel — 第二个 LLM 实例，世界叙事旁白

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("NarrativeModel")


class NarrativeModel:
    """
    叙事旁白模型 — 独立的 DeepSeekChat / LMStudioChat 实例。

    由世界状态 + 人格情绪驱动，生成第三人称旁白文本。
    """

    def __init__(
        self,
        model_type: str = "deepseek",
        model_name: str = "deepseek-v4-flash",
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.9,
        max_tokens: int = 150,
        keep_history: bool = False,
    ):
        self._model_type = model_type
        self._model_name = model_name
        self._api_key = api_key
        self._base_url = base_url
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._keep_history = keep_history
        self._system_prompt: str = ""
        self._history: list[dict] = []

    def set_system_prompt(self, text: str) -> None:
        self._system_prompt = text

    def load_system_prompt_file(self, path: str) -> None:
        try:
            with open(path, encoding="utf-8-sig") as f:
                self._system_prompt = f.read()
            logger.info("叙事模型 system prompt 已加载 (%d 字符)", len(self._system_prompt))
        except Exception as e:
            logger.error("加载叙事 prompt 失败: %s", e)

    def narrate(
        self,
        user_msg: str,
        main_reply: str,
        world_context: str,
        mood_label: str = "",
    ) -> str:
        """
        生成一段叙事旁白。

        :param user_msg: 用户的消息
        :param main_reply: 主模型的回复
        :param world_context: 由 WorldEngine.get_complete_context() 生成
        :param mood_label: 当前情绪标签
        :return: 30-80 字叙事文本
        """
        if not self._system_prompt:
            return ""

        # Build prompt
        context_block = world_context
        if mood_label:
            context_block += f"\nEXA此刻的情绪色调是：{mood_label}。"

        user_prompt = (
            f"{context_block}\n\n"
            f"用户刚刚对EXA说了这段话：\"{user_msg[:200]}\"\n"
            f"EXA给出了这样的回复：\"{main_reply[:300]}\"\n\n"
            f"请你以第三人称旁白的身份，用30-80字中文描述EXA此刻的状态。"
        )

        try:
            text = self._call_llm(user_prompt)
            if not text:
                return ""
            # Clean: strip quotes, brackets
            text = text.strip().strip("\"'「」*_~")
            if not self._keep_history:
                self._history = []
            return text[:200]
        except Exception as e:
            logger.error("叙事模型调用失败: %s", e)
            return ""

    def _call_llm(self, prompt: str) -> str:
        if self._model_type == "lmstudio":
            return self._call_lmstudio(prompt)
        return self._call_deepseek(prompt)

    def _call_deepseek(self, prompt: str) -> str:
        import json as _json, urllib.request as _req, urllib.error as _err
        api_key = self._api_key or ""
        url = self._base_url or "https://api.deepseek.com/v1/chat/completions"
        messages = [{"role": "system", "content": self._system_prompt}]
        if self._keep_history:
            messages.extend(self._history)
        messages.append({"role": "user", "content": prompt})

        body = _json.dumps({
            "model": self._model_name,
            "messages": messages,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "stream": False,
        }).encode("utf-8")

        req = _req.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        try:
            with _req.urlopen(req, timeout=30) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
        except Exception:
            return ""

    def _call_lmstudio(self, prompt: str) -> str:
        import json as _json, urllib.request as _req, urllib.error as _err
        url = f"{self._base_url or 'http://localhost:4501'}/v1/chat/completions"
        messages = [{"role": "system", "content": self._system_prompt}]
        if self._keep_history:
            messages.extend(self._history)
        messages.append({"role": "user", "content": prompt})

        body = _json.dumps({
            "model": self._model_name or "default",
            "messages": messages,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "stream": False,
        }).encode("utf-8")

        req = _req.Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            with _req.urlopen(req, timeout=30) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
        except Exception:
            return ""

    @property
    def keep_history(self) -> bool:
        return self._keep_history

    @keep_history.setter
    def keep_history(self, value: bool) -> None:
        self._keep_history = value
