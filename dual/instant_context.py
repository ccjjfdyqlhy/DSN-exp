# dual/instant_context.py
# Instant 持久上下文 — 连续对话 + 滑动窗口压缩

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from config import Config

logger = logging.getLogger("InstantContext")


class InstantContext:
    """每个 (user_id, chat_id) 对应一个持久 Instant 上下文。

    messages 布局:
      [0] = {"role":"system", "content": system_prompt}  (每次调用前刷新)
      [1:] = 连续对话消息 (user/assistant/system)

    超过 COMPRESS_THRESHOLD 条时，旧消息用 LMSummaryModel 压缩为单条 system 摘要。
    """

    def __init__(
        self,
        user_id: int,
        chat_id: int,
        model_name: str = "",
        base_url: str = "",
        summary_model=None,
    ):
        self.user_id = user_id
        self.chat_id = chat_id
        self._summary_model = summary_model
        self._lock = threading.Lock()
        self._last_access = time.time()

        # Instant 模型客户端 (复用 LMStudioChat)
        from models import LMStudioChat
        self._chat = LMStudioChat(
            base_url=base_url or Config.LMSTUDIO_BASE_URL,
            model_name=model_name or Config.INSTANT_MODEL,
            temperature=Config.INSTANT_TEMPERATURE,
            max_tokens=Config.INSTANT_MAX_TOKENS,
            timeout=Config.INSTANT_TIMEOUT,
        )

        # 消息列表
        self.messages: list[dict] = [
            {"role": "system", "content": "初始化中..."},
        ]

        # 配置
        self._max_messages = Config.INSTANT_CONTEXT_MAX_MESSAGES
        self._compress_threshold = Config.INSTANT_CONTEXT_COMPRESS_THRESHOLD

    @property
    def is_ready(self) -> bool:
        return len(self.messages) > 1

    def refresh_system_prompt(self, system_prompt: str) -> None:
        """刷新 system_prompt (每次 Instant 调用前)"""
        with self._lock:
            if self.messages and self.messages[0].get("role") == "system":
                self.messages[0] = {"role": "system", "content": system_prompt}
            else:
                self.messages.insert(0, {"role": "system", "content": system_prompt})

    def append_user(self, message: str) -> None:
        with self._lock:
            self.messages.append({"role": "user", "content": message})
            self._last_access = time.time()

    def append_assistant(self, reply: str) -> None:
        with self._lock:
            self.messages.append({"role": "assistant", "content": reply})
            self._last_access = time.time()
            self._maybe_compress_locked()

    def append_system(self, message: str) -> None:
        """追加 system 消息 (进度通知/完成通知等)"""
        with self._lock:
            self.messages.append({"role": "system", "content": message})
            self._last_access = time.time()
            self._maybe_compress_locked()

    def call(self, message: str) -> str:
        """调用 Instant 模型。messages 自动包含完整上下文。

        调用后自动追加 user + assistant 消息到 messages。
        """
        with self._lock:
            # 准备消息列表 (包含 system prompt + 历史)
            self._chat.messages = [dict(m) for m in self.messages]
            self._last_access = time.time()

        # send_message 会追加 user 消息、调用 API、追加 assistant 回复
        reply = self._chat.send_message(message)

        with self._lock:
            # 同步回我们的 messages 列表
            # _chat.messages = [old_system, ...old_history, user_msg, assistant_reply]
            self.messages = [dict(m) for m in self._chat.messages]
            self._maybe_compress_locked()

        return reply

    def call_without_append(self, message: str) -> str:
        """调用 Instant 模型但不追加到 messages (用于一次性查询)"""
        with self._lock:
            self._chat.messages = [dict(m) for m in self.messages]
            self._last_access = time.time()
        # 用 continue_conversation 不追加 user 消息
        self._chat.messages.append({"role": "user", "content": message})
        reply = self._chat.continue_conversation()
        # 丢弃 _chat.messages 的最后两条 (user + assistant)
        return reply

    def get_history(self, limit: int = 0) -> list[dict]:
        """返回消息历史 (不含 system prompt)"""
        with self._lock:
            msgs = [m for m in self.messages if m.get("role") != "system"]
            if limit > 0:
                msgs = msgs[-limit:]
            return [dict(m) for m in msgs]

    def _maybe_compress_locked(self) -> None:
        """如果消息数超过阈值，压缩旧消息。调用者需持有 _lock。"""
        if len(self.messages) <= self._compress_threshold:
            return

        if self._summary_model is None:
            # 无摘要模型：简单滑动窗口截断
            keep = self._max_messages
            system_msg = self.messages[0] if self.messages[0].get("role") == "system" else None
            recent = self.messages[-(keep + 1):]
            self.messages = [system_msg] if system_msg else []
            self.messages.extend(recent)
            logger.info("InstantContext: 滑动窗口截断到 %d 条", len(self.messages))
            return

        # 使用 LMSummaryModel 压缩旧消息
        system_msg = self.messages[0] if self.messages[0].get("role") == "system" else None
        old_messages = self.messages[1:]  # 跳过 system prompt
        keep_count = self._max_messages
        to_compress = old_messages[:-keep_count] if len(old_messages) > keep_count else []
        recent = old_messages[-keep_count:] if len(old_messages) > keep_count else old_messages

        if not to_compress:
            return

        try:
            summary = self._summary_model.summarize_dialog(to_compress)
            self.messages = [system_msg] if system_msg else []
            self.messages.append({"role": "system", "content": f"[压缩历史] {summary}"})
            self.messages.extend(recent)
            logger.info("InstantContext: 压缩 %d 条旧消息 → 1 条摘要, 剩余 %d 条",
                        len(to_compress), len(self.messages))
        except Exception as e:
            logger.warning("InstantContext: 压缩失败 %s, 回退到滑动窗口", e)
            keep = self._max_messages
            self.messages = ([system_msg] if system_msg else []) + self.messages[-(keep + 1):]
