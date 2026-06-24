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

    def narrate_pre(
        self,
        user_msg: str,
        world_context: str,
        mood_label: str = "",
    ) -> str:
        """
        前置旁白 — 在 EXA 回复之前，描述他听到用户消息时的瞬间神态。

        :param user_msg: 用户的消息
        :param world_context: 世界状态描述
        :param mood_label: 当前情绪标签
        :return: 30-80 字叙事文本
        """
        if not self._system_prompt:
            return ""

        context_block = world_context
        if mood_label:
            context_block += f"\nEXA此刻的情绪色调是：{mood_label}。"

        user_prompt = (
            f"{context_block}\n\n"
            f"用户刚刚对EXA说了这段话：\"{user_msg[:200]}\"\n"
            f"EXA还没有回复，正在思考如何回应。\n\n"
            f"请你以第三人称旁白的身份，用30-80字中文描述EXA听到用户消息时的瞬间反应、"
            f"神态变化、以及周围环境的氛围。不要用「EXA想」——用动作和感官细节替代内心活动。"
            f"仅输出旁白文本，不要引号或解释。"
        )

        try:
            text = self._call_llm(user_prompt)
            if not text:
                return ""
            text = text.strip().strip("\"'「」*_~")
            return text[:200]
        except Exception as e:
            logger.error("前置旁白模型调用失败: %s", e)
            return ""

    def narrate_action(
        self,
        action_description: str,
        world_context: str,
        mood_label: str = "",
    ) -> str:
        """
        动作旁白 — EXA 执行工具 / 命令时的世界化描写。

        :param action_description: 人性化的动作描述
        :param world_context: 世界状态描述
        :param mood_label: 当前情绪标签
        :return: 20-50 字叙事文本
        """
        if not self._system_prompt:
            return ""

        context_block = world_context
        if mood_label:
            context_block += f"\nEXA此刻的情绪色调是：{mood_label}。"

        user_prompt = (
            f"{context_block}\n\n"
            f"EXA正在进行一项操作：{action_description}\n\n"
            f"请以第三人称旁白的身份，用20-50字中文描写EXA此刻执行这个操作时的动作和周围环境的细节。"
            f"不要用「EXA想」，改用动作和感官描写替代内心活动。仅输出旁白文本，不要引号、解释或标签。"
        )

        try:
            text = self._call_llm(user_prompt)
            if not text:
                return ""
            text = text.strip().strip("\"'「」*_~")
            return text[:200]
        except Exception as e:
            logger.error("动作旁白模型调用失败: %s", e)
            return ""

    def call_llm(self, prompt: str) -> str:
        """公开的 LLM 调用入口，供 ActionNarrator 等外部组件使用"""
        return self._call_llm(prompt)

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
        from config import Config
        from models import _load_lmstudio_model, _unload_lmstudio_model
        from models.scheduler import ModelScheduler

        base_url = self._base_url or "http://localhost:4501"
        url = f"{base_url}/v1/chat/completions"
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

        scheduler = ModelScheduler.get_instance()
        scheduler.register(
            model_name=self._model_name,
            base_url=base_url,
            load_fn=lambda: _load_lmstudio_model(base_url, self._model_name, "叙事模型"),
            unload_fn=lambda: _unload_lmstudio_model(base_url, self._model_name),
        )

        for attempt in range(2):
            req = _req.Request(url, data=body, headers={"Content-Type": "application/json"})
            try:
                with scheduler.use(self._model_name, timeout=Config.MODEL_REQUEST_TIMEOUT):
                    with _req.urlopen(req, timeout=30) as resp:
                        data = _json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"].strip()
            except _err.HTTPError as e:
                if attempt == 0 and self._is_no_model_error(e):
                    logger.info("叙事模型未加载，自动加载后重试……")
                    if self._auto_load_model():
                        continue
                logger.error("LMStudio 叙事调用失败: %s", e)
                return ""
            except Exception:
                return ""
        return ""

    def _auto_load_model(self) -> bool:
        import json as _json, urllib.request as _req, urllib.error as _err

        if not self._model_name:
            logger.error("未配置 model_name，无法自动加载 LMStudio 叙事模型")
            return False
        try:
            base_url = self._base_url or "http://localhost:4501"
            logger.info("正在加载 LMStudio 叙事模型: %s", self._model_name)
            load_body = _json.dumps({"model": self._model_name}).encode("utf-8")
            load_req = _req.Request(
                f"{base_url}/api/v1/models/load",
                data=load_body,
                headers={"Content-Type": "application/json"},
            )
            with _req.urlopen(load_req, timeout=180) as resp:
                result = _json.loads(resp.read().decode("utf-8"))
            logger.info("叙事模型加载完成 (%.1fs): %s",
                         result.get("load_time_seconds", 0), self._model_name)
            return True
        except Exception as e:
            logger.error("自动加载 LMStudio 叙事模型失败 (%s): %s", self._model_name, e)
            return False

    @staticmethod
    def _is_no_model_error(err) -> bool:
        if hasattr(err, "code") and err.code == 400:
            try:
                body = err.read().decode("utf-8") if hasattr(err, "read") else str(err)
                return "no model" in body.lower()
            except Exception:
                pass
        return False

    @property
    def keep_history(self) -> bool:
        return self._keep_history

    @keep_history.setter
    def keep_history(self, value: bool) -> None:
        self._keep_history = value
