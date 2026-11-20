# harness/memory/session_port.py
# Default MemoryStorePort implementation (W3.2).
#
# The port (memory/base.py) used to have zero implementations -- its only
# implementer lived in a split app behind a dead import path. This class is
# the framework's own default: conversation history from the SessionStore,
# semantic recall from an IMemoryStore. The assembler registers it as
# "memory_port" whenever an agent enables memory, so apps that speak the
# port (pipeline plugins, chat services) resolve something real from the
# Runtime instead of a dangling protocol.

from __future__ import annotations

from typing import Any, Optional

from .base import MemoryEntry, MemoryStorePort


class SessionMemoryStore:
    """MemoryStorePort over a SessionStore plus an IMemoryStore recall index."""

    def __init__(self, *,
                 session_store: Any = None,
                 recall: Optional[Any] = None,
                 embedding_client: Any = None):
        if recall is None:
            from .in_memory import InMemoryStore
            recall = InMemoryStore(embedding_client)
        self.session_store = session_store
        self.recall = recall

    # ── MemoryStorePort contract ────────────────────────
    def assemble_context(self, user_id: int, history: list,
                         cross_user_id: Any = None,
                         chat_id: Any = None) -> list:
        """History plus a recall block, as one message list."""
        if not history:
            return history
        last = next((m for m in reversed(history)
                     if getattr(m, 'content', None) or
                     (isinstance(m, dict) and m.get('content'))), None)
        text = (last.get('content') if isinstance(last, dict) else '') \
            if last is not None else ''
        hits = self.search(user_id, [text], limit=5) if text else []
        if not hits:
            return list(history)
        lines = '\n'.join(f'- {hit.text}' for hit in hits)
        return list(history) + [MemoryEntry(
            text=f'Relevant memory:\n{lines}', role='system', meta={'port': True})]

    def summarize_turn(self, user_id: int, chat_id: int, round_idx: int,
                       user_msg: str, assistant_reply: str, **kwargs: Any) -> Any:
        """Record the turn into the recall index and the session history."""
        self.recall.add_text(user_msg, role='user')
        self.recall.add_text(assistant_reply, role='assistant')
        if self.session_store is not None:
            from aicf.infra.models.base import ChatMessage

            self.session_store.save_messages([
                ChatMessage(role='user', content=user_msg),
                ChatMessage(role='assistant', content=assistant_reply),
            ])
        return round_idx

    def search(self, user_id: int, keywords: list, limit: int = 5, **kwargs: Any) -> list:
        query = ' '.join(str(k) for k in keywords or [])
        if not query.strip():
            return []
        return self.recall.search(query, k=limit)

    def add_memo(self, user_id: int, chat_id: int, text: str) -> int:
        self.recall.add_text(text, role='memo')
        return self.recall.count()

    def delete_memo(self, memo_id: int) -> bool:
        return False  # the recall index has no row ids; deletion is a store-level op


__all__ = ['SessionMemoryStore']
