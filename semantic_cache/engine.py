import hashlib
import json
import logging
import re
import time
from typing import Optional

from semantic_cache.models import SearchResult

logger = logging.getLogger("CacheEngine")

INTENT_KEYWORDS = {
    "scan_document":     ["扫描", "扫一下", "scan", "扫描仪", "扫文件"],
    "print_document":    ["打印", "print", "打出来", "打印文件"],
    "check_weather":     ["天气", "weather", "气温", "下雨"],
    "translate_text":    ["翻译", "translate", "翻译成", "翻一下"],
    "compose_exam":      ["组卷", "出题", "出卷子", "模拟卷", "考试题"],
    "search_web":        ["搜索", "搜索一下", "查一下", "搜一下", "帮我搜"],
    "play_music":        ["放音乐", "播放", "放歌", "play music", "来首歌"],
    "set_reminder":      ["提醒", "提醒我", "定点", "计时", "倒计时"],
    "check_schedule":    ["计划", "今日计划", "今日任务", "安排", "日程"],
    "file_operation":    ["文件", "打开文件", "保存", "文件夹", "重命名"],
    "analyze_image":     ["看图", "图片", "这张图", "识别一下", "看一下"],
    "general_question":  ["为什么", "怎么做", "是什么", "怎么", "能否"],
}


class CacheEngine:

    def __init__(self, store, l1_cache, embedding_client=None,
                 similarity_threshold: float = 0.85):
        self._store = store
        self._l1 = l1_cache
        self._embedder = embedding_client
        self._threshold = similarity_threshold

    # ── 意图分类 ──

    def classify_intent(self, message: str) -> str:
        msg_lower = message.lower()
        for intent, keywords in INTENT_KEYWORDS.items():
            for kw in keywords:
                if kw in msg_lower:
                    return intent
        return "general_question"

    # ── 缓存键生成 ──

    @staticmethod
    def build_cache_key(intent_class: str, query_text: str) -> str:
        normalized = re.sub(r"\s+", "", query_text.lower())
        hash_bytes = hashlib.sha256(
            f"{intent_class}:{normalized}".encode()
        ).digest()
        return f"{intent_class}_{hash_bytes[:12].hex()}"

    # ── L1 查询 ──

    def serve_l1(self, intent_class: str) -> Optional[dict]:
        if not self._l1.is_speech_act_only(intent_class):
            return None
        result = self._l1.lookup(intent_class, "acknowledgement")
        if result:
            logger.info("L1 命中: intent=%s", intent_class)
        return result

    # ── 语义搜索 ──

    def search(self, query_text: str, intent_class: str = "",
               top_k: int = 3) -> list[SearchResult]:
        if not self._embedder:
            return []

        query_vec = self._embedder.embed(query_text)
        if not query_vec:
            return []

        candidates = self._store.search_index(
            query_vec,
            threshold=self._threshold,
            intent_filter=intent_class,
            top_k=top_k,
        )

        results = []
        for cache_key, sim in candidates:
            entry = self._store.get_entry(cache_key)
            if not entry:
                continue
            results.append(SearchResult(
                cache_key=cache_key,
                query_text=entry.get("query_text", ""),
                reply_text=entry.get("reply_text", ""),
                reply_tts_path=entry.get("reply_tts_path", ""),
                similarity=round(sim, 4),
                score=entry.get("score", 1.0),
            ))
        return results

    # ── 缓存写入 ──

    def cache_response(self, user_id: int, query_text: str,
                       reply_text: str, intent_class: str = "",
                       tts_audio: Optional[bytes] = None) -> Optional[str]:
        if not self._embedder:
            return None

        query_vec = self._embedder.embed(query_text)
        if not query_vec:
            return None

        if not intent_class:
            intent_class = self.classify_intent(query_text)

        cache_key = self.build_cache_key(intent_class, query_text)

        tts_path = ""
        if tts_audio:
            tts_path = self._store.save_tts(cache_key, tts_audio)

        self._store.put_entry(
            cache_key=cache_key,
            user_id=user_id,
            intent_class=intent_class,
            query_text=query_text,
            query_embedding=query_vec,
            reply_text=reply_text,
            reply_tts_path=tts_path,
        )
        logger.info("缓存写入: key=%s intent=%s", cache_key, intent_class)
        return cache_key

    # ── 评分管理 ──

    def record_hit(self, cache_key: str):
        self._store.update_hit(cache_key)

    def decay_score(self, cache_key: str):
        entry = self._store.get_entry(cache_key)
        if entry:
            new_score = max(0.0, entry["score"] * 0.8)
            self._store.update_score(cache_key, new_score)
            logger.info("缓存衰减: key=%s score=%.2f", cache_key, new_score)

    def boost_score(self, cache_key: str):
        entry = self._store.get_entry(cache_key)
        if entry:
            new_score = min(1.0, entry["score"] + 0.05)
            self._store.update_score(cache_key, new_score)

    # ── 纠偏信号检测 ──

    @staticmethod
    def is_negative_signal(message: str) -> bool:
        signals = [
            "停止", "重新生成", "不对", "不是这样", "重新",
            "stop", "regenerate", "wrong", "算了", "换一个",
        ]
        msg_lower = message.lower().strip()
        return any(s in msg_lower for s in signals)

    # ── 统计 ──

    def get_stats(self) -> dict:
        return self._store.get_stats()
