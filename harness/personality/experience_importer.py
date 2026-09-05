# prompt/personality_v3/experience_importer.py
# 经历描述导入器 — 文本文件接收 + AI 概括（>1000 字）

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from .character_card import ExperienceEntry

logger = logging.getLogger("ExperienceImporter")

EXPERIENCE_SUMMARY_PROMPT = """你是一个角色故事作者。请根据以下素材，撰写一段角色经历了这件事的叙事。

叙事要求:
1. 用第三人称或第一人称叙述，像在讲一个角色的生活片段
2. 如果素材是歌词——想象角色在什么心境下听到了这首歌，歌词中的哪些内容与角色的某些内在特质产生了共鸣。描述这种共鸣
3. 如果素材是文章/文本——描述角色读到这些内容时的感受、联想和反思
4. 如果素材是对话记录——把对话提炼为核心的事件和情感变化
5. 必须保留素材中能反映角色性格、价值观、情感特质的关键内容
6. 语言自然流畅，不超过 1000 字
7. 中文

--- 素材 ---
{text}

--- 请输出角色经历叙事（不超过 1000 字）---"""

EXPERIENCE_NARRATIVE_PROMPT = """你是一个角色故事作者。请根据以下简短的素材片段，想象并撰写一段角色接触到这些内容的经历叙事。

要求:
1. 用第三人称叙述。像在写人物传记的一段。想象角色在什么样的情况下、带着什么样的心境接触到了这段素材
2. 素材可能是一段歌词、一句话、一段文字——它们反映了角色的品味、情感或经历
3. 这段叙事将作为角色性格建模的源材料，所以要突出角色因此产生的任何情感、思考或变化
4. 150~500 字，中文

--- 素材 ---
{text}

--- 请输出叙事（150~500 字）---"""

EXPERIENCE_SUMMARY_MAX = 1000


class ExperienceImporter:
    def __init__(self, summary_chat=None):
        """
        :param summary_chat: OpenAIChat 或 LMStudioChat 实例，用于概括长文本
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

        if self._chat:
            try:
                if original_len <= EXPERIENCE_SUMMARY_MAX:
                    entry.summary = self._narrate(text)
                    logger.info("经历文本 %d 字 → 已生成叙事 %d 字", original_len, len(entry.summary))
                else:
                    entry.summary = self._summarize(text)
                    logger.info("经历文本 %d 字 → 已概括为叙事 %d 字", original_len, len(entry.summary))
            except Exception as e:
                logger.error("处理经历文本失败: %s — 使用原始文本", e)
                entry.summary = text[:EXPERIENCE_SUMMARY_MAX]
        else:
            logger.warning("无概括模型可用，存储原始文本")
            entry.summary = text.strip()

        return entry

    def _narrate(self, text: str) -> str:
        prompt = EXPERIENCE_NARRATIVE_PROMPT.format(text=text[:4000])
        return self._send_with_temp(self._chat, prompt, 0.5, 600)

    def _summarize(self, text: str) -> str:
        prompt = EXPERIENCE_SUMMARY_PROMPT.format(text=text[:8000])
        return self._send_with_temp(self._chat, prompt, 0.3, 1500)

    @staticmethod
    def _send_with_temp(chat, prompt: str, temperature: float, max_tokens: int) -> str:
        old_temp = getattr(chat, 'temperature', None)
        old_max = getattr(chat, 'max_tokens', None)
        try:
            if hasattr(chat, 'temperature'):
                chat.temperature = temperature
            if hasattr(chat, 'max_tokens'):
                chat.max_tokens = max_tokens
            if hasattr(chat, 'send_message'):
                reply = chat.send_message(prompt)
            elif hasattr(chat, 'invoke'):
                from harness.models.base import ChatMessage
                resp = chat.invoke([ChatMessage(role="user", content=prompt)], temperature=temperature, max_tokens=max_tokens)
                reply = resp.content or ""
            elif hasattr(chat, 'complete'):
                from harness.models.base import ChatMessage
                resp = chat.complete([ChatMessage(role="user", content=prompt)])
                reply = resp.content or ""
            else:
                reply = ""
            return reply.strip()
        finally:
            if old_temp is not None and hasattr(chat, 'temperature'):
                chat.temperature = old_temp
            if old_max is not None and hasattr(chat, 'max_tokens'):
                chat.max_tokens = old_max

    @staticmethod
    def compute_hash(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:16]
