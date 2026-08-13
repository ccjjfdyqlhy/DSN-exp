# harness/conversation.py
# 通用会话管理 — 多会话历史维护 + 上下文裁剪。

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from .models.base import ChatMessage


@dataclass
class Conversation:
    """一次对话会话。"""
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    title: str = ""
    messages: list[ChatMessage] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    meta: dict = field(default_factory=dict)

    def add(self, message: ChatMessage) -> "Conversation":
        self.messages.append(message)
        return self

    def add_text(self, role: str, content: str) -> "Conversation":
        return self.add(ChatMessage(role=role, content=content))

    def history(self, *, max_messages: Optional[int] = None,
                max_chars: Optional[int] = None) -> list[ChatMessage]:
        """返回裁剪后的历史（非 system 消息受 max_messages 限制）。"""
        msgs = [m for m in self.messages if m.role != "system"]
        if max_messages is not None and len(msgs) > max_messages:
            msgs = msgs[-max_messages:]
        if max_chars is not None:
            total = 0
            kept = []
            for m in reversed(msgs):
                total += len(m.content)
                if total > max_chars and kept:
                    break
                kept.append(m)
            msgs = list(reversed(kept))
        return msgs

    def clear(self) -> None:
        self.messages.clear()

    def __len__(self) -> int:
        return len(self.messages)

    def __bool__(self) -> bool:
        # 会话对象作为实体始终为真，避免空会话被 __len__ == 0 判为假
        return True


class ConversationManager:
    """多会话管理。"""

    def __init__(self):
        self._conversations: dict[str, Conversation] = {}

    def create(self, *, title: str = "", session_id: Optional[str] = None,
               **meta) -> Conversation:
        conv = Conversation(session_id=session_id or uuid.uuid4().hex,
                            title=title, meta=meta)
        self._conversations[conv.session_id] = conv
        return conv

    def get(self, session_id: str) -> Optional[Conversation]:
        return self._conversations.get(session_id)

    def require(self, session_id: str) -> Conversation:
        conv = self._conversations.get(session_id)
        if conv is None:
            raise KeyError(f"会话不存在: {session_id}")
        return conv

    def delete(self, session_id: str) -> bool:
        return self._conversations.pop(session_id, None) is not None

    def sessions(self) -> list[Conversation]:
        return list(self._conversations.values())

    def __len__(self) -> int:
        return len(self._conversations)
