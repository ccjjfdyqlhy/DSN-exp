# scripts/player.py
# ScriptPlayer — 匹配 + 回放录制内容

from __future__ import annotations

import logging
from typing import Optional

from scripts.state import ScriptState

logger = logging.getLogger("ScriptPlayer")


class ScriptPlayer:
    def __init__(self, state: ScriptState):
        self._state = state
        self._cache: dict[str, list[dict]] = {}

    def find_match(self, user_id: int, user_input: str,
                   script_id: str, chapter_id: str,
                   replay_mode: str = "exact") -> str | None:
        if not script_id or not chapter_id:
            return None

        cache_key = f"{user_id}:{script_id}:{chapter_id}"
        if cache_key not in self._cache:
            recordings = self._state.find_recording(user_id, script_id, chapter_id)
            self._cache[cache_key] = recordings

        recordings = self._cache[cache_key]
        if not recordings:
            return None

        normalized = user_input.strip().lower()

        for rec in recordings:
            rec_mode = rec.get("replay_mode", "exact")
            rec_input = rec.get("user_input", "").strip().lower()

            if rec_mode == "exact":
                if normalized == rec_input:
                    return self._replay(rec)
            elif rec_mode == "template":
                if self._template_match(normalized, rec_input):
                    return self._replay(rec)
            elif rec_mode == "hybrid":
                if normalized == rec_input or self._template_match(normalized, rec_input):
                    return self._replay(rec)

        return None

    def replay(self, recording_id: str) -> str | None:
        recordings = self._state.find_recording(0, "", "")
        for rec in recordings:
            if rec["id"] == recording_id:
                return self._replay(rec)
        return None

    def _replay(self, recording: dict) -> str:
        self._state.increment_hit_count(recording["id"])
        logger.info("回放命中: %s (命中次数: %d)",
                    recording["id"][:8], recording.get("hit_count", 0) + 1)
        return recording.get("ai_reply", "")

    def _template_match(self, user_input: str, recorded_input: str) -> bool:
        if len(user_input) < 2 or len(recorded_input) < 2:
            return False

        shared = set(user_input) & set(recorded_input)
        if not shared:
            return False

        if abs(len(user_input) - len(recorded_input)) > max(len(user_input), len(recorded_input)) * 0.5:
            return False

        overlap = len(shared) / max(len(set(user_input) | set(recorded_input)), 1)
        return overlap >= 0.6

    def clear_cache(self) -> None:
        self._cache.clear()