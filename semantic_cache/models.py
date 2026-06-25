from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CacheEntry:
    cache_key: str = ""
    user_id: int = 0
    intent_class: str = ""
    query_text: str = ""
    query_embedding: Optional[list[float]] = None
    reply_text: str = ""
    reply_tts_path: str = ""
    hit_count: int = 0
    score: float = 1.0
    created_at: str = ""
    last_hit_at: str = ""


@dataclass
class L1Entry:
    intent_id: str = ""
    speech_act_type: str = ""
    text: str = ""
    tts_path: str = ""
    hit_count: int = 0


@dataclass
class SearchResult:
    cache_key: str = ""
    query_text: str = ""
    reply_text: str = ""
    reply_tts_path: str = ""
    similarity: float = 0.0
    score: float = 1.0
