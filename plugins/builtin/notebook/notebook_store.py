# plugins/builtin/notebook/notebook_store.py
# 用户观察日记存储 — 基于 JSON 文件的轻量存储

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("NotebookStore")

NOTEBOOK_ROOT = Path(__file__).parent.parent.parent.parent / "notebook"


class NotebookStore:
    """用户观察日记存储。每个用户的笔记保存在 notebook/<uid>.json。"""

    def __init__(self):
        NOTEBOOK_ROOT.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._uid_last_counts: dict[int, int] = {}

    def _path_for(self, uid: int) -> Path:
        return NOTEBOOK_ROOT / f"{uid}.json"

    def add_note(self, uid: int, content: str, chat_id: int = 0) -> dict:
        """追加一条笔记，返回完整的 note_entry"""
        note = {
            "id": self._next_id(uid),
            "chat_id": chat_id,
            "content": content,
            "created_at": datetime.now().isoformat(),
        }
        with self._lock:
            entries = self._load(uid)
            entries.append(note)
            self._save(uid, entries)
        logger.info("Notebook: uid=%d 新增笔记 #%d (%d chars)", uid, note["id"], len(content))
        return note

    def get_notes(self, uid: int, limit: int = 0) -> list[dict]:
        entries = self._load(uid)
        if limit > 0:
            return entries[-limit:]
        return entries

    def count(self, uid: int) -> int:
        return len(self._load(uid))

    def note_count(self, uid: int) -> int:
        return self.count(uid)

    def _next_id(self, uid: int) -> int:
        entries = self._load(uid)
        return (max(e["id"] for e in entries) + 1) if entries else 1

    def _load(self, uid: int) -> list[dict]:
        path = self._path_for(uid)
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, Exception):
            return []

    def _save(self, uid: int, entries: list[dict]):
        path = self._path_for(uid)
        path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
