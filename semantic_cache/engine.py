import hashlib
import json
import logging
import re
from typing import Optional

from semantic_cache.models import SearchResult, ActionGraph
from semantic_cache.l2 import L2Cache, compute_action_signature, compute_slot_hash
from semantic_cache.l3 import L3SlotRegistry

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
        self._l2 = L2Cache(store)
        self._l3 = L3SlotRegistry(store)

    @property
    def l2(self) -> L2Cache:
        return self._l2

    @property
    def l3(self) -> L3SlotRegistry:
        return self._l3

    def classify_intent(self, message: str) -> str:
        msg_lower = message.lower()
        for intent, keywords in INTENT_KEYWORDS.items():
            for kw in keywords:
                if kw in msg_lower:
                    return intent
        return "general_question"

    @staticmethod
    def build_cache_key(intent_class: str, query_text: str) -> str:
        normalized = re.sub(r"\s+", "", query_text.lower())
        hash_bytes = hashlib.sha256(
            f"{intent_class}:{normalized}".encode()
        ).digest()
        return f"{intent_class}_{hash_bytes[:12].hex()}"

    def serve_l1(self, intent_class: str) -> Optional[dict]:
        if not self._l1.is_speech_act_only(intent_class):
            return None
        result = self._l1.lookup(intent_class, "acknowledgement")
        if result:
            logger.info("L1 命中: intent=%s", intent_class)
        return result

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

    def cache_response(self, user_id: int, query_text: str,
                       reply_text: str, intent_class: str = "",
                       tts_audio: Optional[bytes] = None,
                       session_id: str = "") -> Optional[str]:
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

        self._l1.learn_from_dialog(
            query_text, reply_text, tts_audio, self.classify_intent
        )

        self._try_cache_l2(reply_text, intent_class, session_id)

        logger.info("缓存写入: key=%s intent=%s", cache_key, intent_class)
        return cache_key

    def _try_cache_l2(self, reply_text: str, intent_id: str, session_id: str = ""):
        dag = self._l2.build_dag_from_response(reply_text, intent_id)
        if not dag:
            return

        operations = [n.operation for n in dag.nodes]
        sig = compute_action_signature(operations)

        existing = self._l2.get_dag(sig)
        if not existing:
            self._l2.save_dag(sig, intent_id, dag)
            logger.info("L2 DAG 缓存: sig=%s intent=%s ops=%d",
                        sig[:12], intent_id, len(operations))

        if session_id:
            slots = self._l3.get_all_slots(session_id)
            slot_values = {}
            for name, entry in slots.items():
                try:
                    slot_values[name] = json.loads(entry.get("value_json", "null"))
                except (json.JSONDecodeError, TypeError):
                    slot_values[name] = entry.get("value_json", "")

            if slot_values:
                slot_hash = compute_slot_hash(slot_values)
                self._l2.save_result(
                    action_signature=sig,
                    slot_hash=slot_hash,
                    result_text=reply_text,
                    response_json=json.dumps({
                        "intent_id": intent_id,
                        "operations": operations,
                    }, ensure_ascii=False),
                )

    def serve_l2(self, query_text: str, intent_class: str = "",
                 session_id: str = "") -> Optional[dict]:
        if not self._embedder:
            return None

        query_vec = self._embedder.embed(query_text)
        if not query_vec:
            return None

        candidates = self._store.search_index(
            query_vec,
            threshold=self._threshold,
            intent_filter=intent_class,
            top_k=3,
        )

        for cache_key, sim in candidates:
            entry = self._store.get_entry(cache_key)
            if not entry or entry.get("score", 0) < 0.35:
                continue

            reply_text = entry.get("reply_text", "")
            dag = self._l2.build_dag_from_response(reply_text, intent_class)
            if not dag:
                continue

            operations = [n.operation for n in dag.nodes]
            sig = compute_action_signature(operations)

            stored_dag = self._l2.get_dag(sig)
            if not stored_dag:
                self._l2.save_dag(sig, intent_class, dag)
                stored_dag = dag

            if session_id:
                slots = self._l3.get_all_slots(session_id)
                slot_values = {}
                for name, slot_entry in slots.items():
                    try:
                        slot_values[name] = json.loads(slot_entry.get("value_json", "null"))
                    except (json.JSONDecodeError, TypeError):
                        slot_values[name] = slot_entry.get("value_json", "")

                slot_hash = compute_slot_hash(slot_values) if slot_values else ""
                if slot_hash:
                    result = self._l2.get_result(sig, slot_hash)
                    if result:
                        self._l2.record_hit(sig)
                        tts_path = result.get("reply_tts_path", "")
                        logger.info("L2 命中: sig=%s slot=%s sim=%.4f",
                                    sig[:12], slot_hash[:8], sim)
                        return {
                            "reply_text": result.get("result_text", ""),
                            "tts_path": tts_path,
                            "action_signature": sig,
                            "slot_hash": slot_hash,
                            "similarity": sim,
                        }

            logger.info("L2 DAG 匹配: sig=%s sim=%.4f (无槽位结果)",
                        sig[:12], sim)
            return {
                "reply_text": reply_text,
                "tts_path": entry.get("reply_tts_path", ""),
                "action_signature": sig,
                "slot_hash": "",
                "similarity": sim,
            }

        return None

    def compile_l2(self, action_signature: str, session_id: str) -> tuple[Optional[ActionGraph], str]:
        slots = self._l3.get_all_slots(session_id)
        slot_values = {}
        for name, entry in slots.items():
            try:
                slot_values[name] = json.loads(entry.get("value_json", "null"))
            except (json.JSONDecodeError, TypeError):
                slot_values[name] = entry.get("value_json", "")

        return self._l2.compile_and_check(action_signature, slot_values)

    def extract_slots_from_message(self, message: str, session_id: str) -> dict[str, dict]:
        known = {}
        for intent, keywords in INTENT_KEYWORDS.items():
            for kw in keywords:
                if kw in message.lower():
                    known["intent"] = "str"
                    break

        return self._l3.extract_from_message(message, session_id, known)

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

    @staticmethod
    def is_negative_signal(message: str) -> bool:
        signals = [
            "停止", "重新生成", "不对", "不是这样", "重新",
            "stop", "regenerate", "wrong", "算了", "换一个",
        ]
        msg_lower = message.lower().strip()
        return any(s in msg_lower for s in signals)

    def get_stats(self) -> dict:
        stats = self._store.get_stats()
        stats["l1_phrases"] = len(self._l1.get_all_phrases())
        return stats

    def cleanup(self):
        self._l3.cleanup_expired()
