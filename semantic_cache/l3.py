import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Optional

from semantic_cache.models import SlotEntry

logger = logging.getLogger("L3Cache")

EXTRACTION_PATTERNS = {
    "Path": [
        re.compile(r"(?:文件|路径|目录|文件夹)\s*[:：]\s*([^\s,，。]+)"),
        re.compile(r"(/[\w/.-]+)"),
        re.compile(r"(?:打开|保存|读取|写入)\s+([^\s,，。]+)"),
    ],
    "Email": [
        re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    ],
    "URL": [
        re.compile(r"https?://[^\s,，。]+"),
    ],
    "int": [
        re.compile(r"(?:数量|个数|次数|天数|分钟|小时)\s*[:：]?\s*(\d+)"),
        re.compile(r"(\d+)\s*(?:个|件|次|天|分钟|小时)"),
    ],
    "str": [
        re.compile(r"(?:名称|名字|标题|主题)\s*[:：]\s*([^\s,，。]+)"),
        re.compile(r"(?:城市|地区|地点)\s*[:：]\s*([^\s,，。]+)"),
    ],
}

DEFAULT_TTL_SECONDS = 3600


class L3SlotRegistry:

    def __init__(self, store):
        self._store = store

    def get_slot(self, session_id: str, slot_name: str) -> Optional[dict]:
        entry = self._store.get_l3_slot(session_id, slot_name)
        if not entry:
            return None
        if entry.get("expires_at"):
            try:
                exp = datetime.fromisoformat(entry["expires_at"])
                if datetime.now() > exp:
                    self._store.delete_l3_slot(session_id, slot_name)
                    return None
            except (ValueError, TypeError):
                pass
        return entry

    def get_all_slots(self, session_id: str) -> dict[str, dict]:
        entries = self._store.list_l3_slots(session_id)
        result = {}
        now = datetime.now()
        for entry in entries:
            if entry.get("expires_at"):
                try:
                    exp = datetime.fromisoformat(entry["expires_at"])
                    if now > exp:
                        self._store.delete_l3_slot(session_id, entry["slot_name"])
                        continue
                except (ValueError, TypeError):
                    pass
            result[entry["slot_name"]] = entry
        return result

    def set_slot(self, session_id: str, slot_name: str, slot_type: str,
                 value: Any, confidence: float = 1.0,
                 source: str = "extracted", ttl_seconds: int = DEFAULT_TTL_SECONDS) -> bool:
        expires_at = ""
        if ttl_seconds > 0:
            exp = datetime.now() + timedelta(seconds=ttl_seconds)
            expires_at = exp.isoformat()

        value_json = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value

        return self._store.put_l3_slot(
            session_id=session_id,
            slot_name=slot_name,
            slot_type=slot_type,
            value_json=value_json,
            confidence=confidence,
            source=source,
            expires_at=expires_at,
        )

    def delete_slot(self, session_id: str, slot_name: str) -> bool:
        return self._store.delete_l3_slot(session_id, slot_name)

    def clear_session(self, session_id: str) -> int:
        return self._store.clear_l3_session(session_id)

    def extract_from_message(self, message: str, session_id: str,
                              known_slots: Optional[dict[str, str]] = None) -> dict[str, dict]:
        extracted = {}
        for slot_type, patterns in EXTRACTION_PATTERNS.items():
            for pattern in patterns:
                matches = pattern.findall(message)
                for match in matches:
                    if isinstance(match, tuple):
                        match = match[0] if match else ""
                    if not match or len(match) < 2:
                        continue

                    slot_name = self._infer_slot_name(match, slot_type, known_slots)
                    if slot_name and slot_name not in extracted:
                        extracted[slot_name] = {
                            "slot_name": slot_name,
                            "slot_type": slot_type,
                            "value": match,
                            "confidence": 0.8,
                            "source": "extracted",
                        }
                        self.set_slot(
                            session_id=session_id,
                            slot_name=slot_name,
                            slot_type=slot_type,
                            value=match,
                            confidence=0.8,
                            source="extracted",
                        )

        return extracted

    def _infer_slot_name(self, value: str, slot_type: str,
                          known_slots: Optional[dict[str, str]] = None) -> Optional[str]:
        if known_slots:
            for name, typ in known_slots.items():
                if typ == slot_type:
                    return name

        type_prefix_map = {
            "Path": "file",
            "Email": "email",
            "URL": "url",
            "int": "count",
            "str": "name",
        }
        prefix = type_prefix_map.get(slot_type, "param")
        return f"{prefix}_{hash(value) % 10000}"

    def cleanup_expired(self) -> int:
        return self._store.cleanup_expired_l3_slots()

    def get_slot_stats(self, session_id: str) -> dict:
        slots = self.get_all_slots(session_id)
        by_type = {}
        for s in slots.values():
            t = s.get("slot_type", "unknown")
            if t not in by_type:
                by_type[t] = 0
            by_type[t] += 1
        return {"total": len(slots), "by_type": by_type}
