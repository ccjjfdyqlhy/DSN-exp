# prompt/personality_v3/experience_importer.py
# 经历描述导入器 — 文本文件接收 + AI 概括（>1000 字）

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Optional

from .character_card import ExperienceEntry

logger = logging.getLogger("ExperienceImporter")

EXPERIENCE_SUMMARY_PROMPT = """请将以下角色经历概括为不超过 1000 字的紧凑叙述。

概括要求：
1. 保留关键人物、关键事件、情感转折、性格转变
2. 删除琐碎细节和无关的环境描写
3. 保留因果链条：什么事件导致了什么性格变化
4. 语言紧凑连贯，像在讲一个人的简史
5. 必须是中文（除非原文是其他语言）

--- 原文 ---
{text}

--- 请输出概括（不超过 1000 字）---"""

EXPERIENCE_SUMMARY_MAX = 1000


class ExperienceImporter:
    def __init__(self, summary_chat=None):
        """
        :param summary_chat: DeepSeekChat 或 LMStudioChat 实例，用于概括长文本
        """
        self._chat = summary_chat

    def set_chat(self, chat) -> None:
        self._chat = chat

    def import_file(self, filepath: str | Path) -> ExperienceEntry:
        p = Path(filepath)
        if not p.exists():
            raise FileNotFoundError(f"经历文件不存在: {p}")
        raw = p.read_text(encoding="utf-8")
        return self._process(raw, str(p))

    def import_text(self, text: str, source: str = "") -> ExperienceEntry:
        return self._process(text, source)

    def import_multiple(self, items: list[dict]) -> list[ExperienceEntry]:
        results = []
        for item in items:
            if "text" in item and item["text"]:
                results.append(self.import_text(item["text"], item.get("source", "")))
            elif "file" in item and item["file"]:
                results.append(self.import_file(item["file"]))
        return results

    def _process(self, text: str, source: str) -> ExperienceEntry:
        entry = ExperienceEntry()
        original_len = len(text)

        if "file" not in source and source:
            entry.text = text
        if source and Path(source).exists():
            entry.file = source

        entry.original_length = original_len

        if original_len <= EXPERIENCE_SUMMARY_MAX:
            entry.summary = text.strip()
            logger.info("经历文本 %d 字，直接接收", original_len)
        else:
            entry.text = text
            if self._chat:
                try:
                    entry.summary = self._summarize(text)
                    logger.info("经历文本 %d 字 → 已概括为 %d 字", original_len, len(entry.summary))
                except Exception as e:
                    logger.error("概括经历文本失败: %s — 使用截断文本", e)
                    entry.summary = text[:EXPERIENCE_SUMMARY_MAX]
            else:
                logger.warning("无概括模型可用，截断经历文本到 %d 字", EXPERIENCE_SUMMARY_MAX)
                entry.summary = text[:EXPERIENCE_SUMMARY_MAX]

        return entry

    def _summarize(self, text: str) -> str:
        prompt = EXPERIENCE_SUMMARY_PROMPT.format(text=text[:8000])
        old_temp = getattr(self._chat, 'temperature', None)
        old_max = getattr(self._chat, 'max_tokens', None)
        try:
            if hasattr(self._chat, 'temperature'):
                self._chat.temperature = 0.3
            if hasattr(self._chat, 'max_tokens'):
                self._chat.max_tokens = 1500
            reply = self._chat.send_message(prompt)
        finally:
            if old_temp is not None and hasattr(self._chat, 'temperature'):
                self._chat.temperature = old_temp
            if old_max is not None and hasattr(self._chat, 'max_tokens'):
                self._chat.max_tokens = old_max
        reply = reply.strip()
        if len(reply) > EXPERIENCE_SUMMARY_MAX:
            reply = reply[:EXPERIENCE_SUMMARY_MAX]
        return reply

    @staticmethod
    def compute_hash(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:16]
