# apps/dsn_study/memory/summary.py
# LLMSummaryModel — 对话记忆摘要模型（dsn_study 版）。
#
# dsn 原版（apps/dsn/models/clients.py LMSummaryModel）自带 HTTP 客户端、
# 重试与 LMStudio 调度器对接；study 版收敛为包装 LLMService（主模型客户端
# 的 send_message 契约），提示词与接口签名与原版对齐：
#   summarize_dialog(messages, max_length) / summarize_text(text, max_length)

from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger("MemorySummary")

_SUMMARY_PROMPT = (
    "你是下方对话中标记为[助手/AI]的一方。\n"
    "现在用第一人称(我=助手)概括这段对话：\n\n"
    "规则：\n"
    "1. 先描述用户说了什么/做了什么\n"
    "2. 再写你(助手)是如何回应的\n"
    "3. 禁止编造对话中不存在的事实\n"
    "4. 使用具体动词，避免笼统的'承认/确认'\n"
    "5. 1-2 句话，总字数 ≤ {max_length} 字\n"
    "6. 仅输出概括，无任何引导语\n\n"
    "对话内容：\n"
)


class LLMSummaryModel:
    """摘要模型 — 包装 LLMService（send_message(prompt) -> str）。"""

    def __init__(self, llm=None, temperature: float = 0.3):
        # llm: LLMService；允许后置注入（boot 装配顺序灵活）
        self._llm = llm
        self._temperature = temperature

    def bind(self, llm) -> None:
        self._llm = llm

    def _check(self):
        if self._llm is None:
            raise RuntimeError("摘要模型不可用：未注入 LLM 客户端")
        return self._llm

    def summarize_dialog(self, messages: list[dict], max_length: int = 100) -> Optional[str]:
        """概括一轮对话（[{role, content}, ...]），失败返回 None（调用方静默跳过）。"""
        if not messages:
            return None
        transcript = "\n".join(
            f"[{'用户' if m.get('role') == 'user' else '助手/AI'}] {m.get('content', '')}"
            for m in messages
        )
        prompt = _SUMMARY_PROMPT.format(max_length=max_length) + transcript
        try:
            out = self._check().send_message(prompt).strip()
        except Exception:
            logger.exception("summarize_dialog 失败")
            return None
        return out or None

    def summarize_text(self, text: str, max_length: int = 100) -> Optional[str]:
        """概括一段文本。"""
        prompt = (
            f"请用不超过 {max_length} 字概括以下内容，仅输出概括：\n\n{text}"
        )
        try:
            out = self._check().send_message(prompt).strip()
        except Exception:
            logger.exception("summarize_text 失败")
            return None
        return out or None

    def __repr__(self):
        return f"<LLMSummaryModel llm={type(self._llm).__name__ if self._llm else None}>"
