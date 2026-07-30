# scripts/recorder.py
# ScriptRecorder — 录制 AI 响应/动作/状态变迁

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional

from scripts.state import ScriptState

logger = logging.getLogger("ScriptRecorder")


@dataclass
class RecordContext:
    user_id: int
    script_id: str
    chapter_id: str
    key_points_met: list[str] = field(default_factory=list)
    user_input: str = ""
    ai_reply: str = ""
    tool_calls: Optional[str] = None
    system_state: dict = field(default_factory=dict)
    replay_mode: str = "exact"


class ScriptRecorder:
    def __init__(self, state: ScriptState):
        self._state = state

    def record(self, ctx: RecordContext) -> str | None:
        recording_id = str(uuid.uuid4())
        fingerprint = self._compute_fingerprint(ctx)

        recording = {
            "id": recording_id,
            "user_id": ctx.user_id,
            "script_id": ctx.script_id,
            "chapter_id": ctx.chapter_id,
            "key_points_met": ctx.key_points_met,
            "user_input": ctx.user_input,
            "ai_reply": ctx.ai_reply,
            "tool_calls": ctx.tool_calls,
            "context_fingerprint": fingerprint,
            "replay_mode": ctx.replay_mode,
        }

        if self._state.save_recording(recording):
            logger.info("录制保存: %s (章节: %s, 关键点: %s)",
                        recording_id[:8], ctx.chapter_id, ctx.key_points_met)
            return recording_id

        logger.error("录制保存失败")
        return None

    def invalidate(self, script_id: str, reason: str = "") -> int:
        count = self._state.invalidate_recordings(script_id, reason)
        logger.info("录制失效: %s, %d 条 (%s)", script_id, count, reason)
        return count

    def _compute_fingerprint(self, ctx: RecordContext) -> str:
        data = json.dumps({
            "script_id": ctx.script_id,
            "chapter_id": ctx.chapter_id,
            "system_state": ctx.system_state,
        }, sort_keys=True)
        h = hashlib.sha256()
        h.update(data.encode("utf-8"))
        return h.hexdigest()[:16]

    def get_context_for_engine(self, engine) -> RecordContext:
        return RecordContext(
            user_id=engine._user_id if hasattr(engine, '_user_id') else 0,
            script_id=getattr(engine, 'active_script', ''),
            chapter_id=getattr(engine, 'active_chapter', ''),
            key_points_met=[k for k, v in engine._scores.items() if v > 0],
        )