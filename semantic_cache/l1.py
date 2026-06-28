import json
import logging
from typing import Optional

logger = logging.getLogger("L1Cache")

DEFAULT_PHRASES = [
    # intent_id, speech_act_type, text
    ("confirm_task",  "acknowledgement", "好的，正在为您处理"),
    ("complete_task", "closure",         "已完成，请查收"),
    ("general_error", "apology",         "抱歉，出了点问题，请稍后再试"),
    ("general_error", "instruction",     "当前服务不可用，请检查设置"),
    ("processing",    "progress",        "正在处理中，请稍候"),
    ("reject_action", "explanation",     "抱歉，我无法执行这个操作"),
    ("greeting",      "greeting",        "你好！有什么可以帮你的？"),
]

SPEECH_ACT_ONLY_INTENTS = {
    "confirm_task", "complete_task", "general_error",
    "processing", "reject_action", "greeting",
}

LEARNABLE_PHRASES = {
    "confirm_task":  ["acknowledgement", "confirmation"],
    "complete_task": ["closure", "done"],
    "general_error": ["apology", "instruction"],
    "processing":    ["progress", "waiting"],
    "reject_action": ["explanation", "refusal"],
    "greeting":      ["greeting", "hello"],
    "farewell":      ["farewell", "bye"],
    "thanks":        ["acknowledgement", "gratitude"],
}


class L1PragmaticCache:

    def __init__(self, store):
        self._store = store

    def init_builtin_phrases(self):
        for intent_id, act_type, text in DEFAULT_PHRASES:
            self._store.put_l1(intent_id, act_type, text)

    def lookup(self, intent_id: str, speech_act_type: str) -> dict | None:
        return self._store.get_l1(intent_id, speech_act_type)

    def cache_tts_for_l1(self, intent_id: str, speech_act_type: str,
                          audio_bytes: bytes) -> str:
        return self._store.save_tts_l1(intent_id, speech_act_type, audio_bytes)

    def is_speech_act_only(self, intent_id: str) -> bool:
        return intent_id in SPEECH_ACT_ONLY_INTENTS

    def learn_from_recording(self, intent_id: str, speech_act_type: str,
                              text: str, tts_audio: Optional[bytes] = None) -> bool:
        existing = self._store.get_l1(intent_id, speech_act_type)
        if existing:
            return False
        tts_path = ""
        if tts_audio:
            tts_path = self._store.save_tts_l1(intent_id, speech_act_type, tts_audio)
        return self._store.put_l1(intent_id, speech_act_type, text, tts_path)

    def learn_from_dialog(self, user_message: str, ai_reply: str,
                           tts_audio: Optional[bytes] = None,
                           intent_classifier=None) -> Optional[dict]:
        intent_id = None
        if intent_classifier:
            intent_id = intent_classifier(user_message)

        if not intent_id:
            return self._detect_phrase_intent(ai_reply)

        if intent_id not in LEARNABLE_PHRASES:
            return None

        speech_acts = LEARNABLE_PHRASES[intent_id]
        text_lower = ai_reply.strip().lower()
        text_len = len(ai_reply.strip())

        if text_len > 50 or text_len < 2:
            return None

        if any(c in text_lower for c in ["<tool>", "```", "http"]):
            return None

        speech_act = speech_acts[0]
        tts_path = ""
        if tts_audio:
            tts_path = self._store.save_tts_l1(intent_id, speech_act, tts_audio)

        success = self._store.put_l1(intent_id, speech_act, ai_reply.strip(), tts_path)
        if success:
            logger.info("L1 学习新短语: intent=%s act=%s text=%s",
                        intent_id, speech_act, ai_reply[:30])
            return {"intent_id": intent_id, "speech_act_type": speech_act,
                    "text": ai_reply.strip()}
        return None

    def _detect_phrase_intent(self, text: str) -> Optional[dict]:
        text_lower = text.strip().lower()
        text_len = len(text.strip())

        if text_len > 50 or text_len < 2:
            return None

        if any(c in text_lower for c in ["<tool>", "```", "http"]):
            return None

        greeting_patterns = ["你好", "hello", "hi", "早上好", "晚上好", "嗨"]
        if any(p in text_lower for p in greeting_patterns):
            return {"intent_id": "greeting", "speech_act_type": "greeting",
                    "text": text.strip()}

        farewell_patterns = ["再见", "bye", "下次见", "回头见", "拜拜"]
        if any(p in text_lower for p in farewell_patterns):
            return {"intent_id": "farewell", "speech_act_type": "farewell",
                    "text": text.strip()}

        confirm_patterns = ["好的", "收到", "明白", "了解", "ok", "没问题", "马上"]
        if any(p in text_lower for p in confirm_patterns):
            return {"intent_id": "confirm_task", "speech_act_type": "acknowledgement",
                    "text": text.strip()}

        complete_patterns = ["完成", "已完成", "做好了", "搞定了", "done", "查收"]
        if any(p in text_lower for p in complete_patterns):
            return {"intent_id": "complete_task", "speech_act_type": "closure",
                    "text": text.strip()}

        error_patterns = ["抱歉", "对不起", "出错", "失败", "无法", "sorry", "不可用"]
        if any(p in text_lower for p in error_patterns):
            return {"intent_id": "general_error", "speech_act_type": "apology",
                    "text": text.strip()}

        processing_patterns = ["正在处理", "请稍候", "稍等", "处理中", "进行中"]
        if any(p in text_lower for p in processing_patterns):
            return {"intent_id": "processing", "speech_act_type": "progress",
                    "text": text.strip()}

        thanks_patterns = ["谢谢", "感谢", "thanks", "thank you", "多谢"]
        if any(p in text_lower for p in thanks_patterns):
            return {"intent_id": "thanks", "speech_act_type": "acknowledgement",
                    "text": text.strip()}

        return None

    def get_all_phrases(self) -> list[dict]:
        return self._store.list_l1_all()

    def get_phrase_stats(self) -> dict:
        phrases = self._store.list_l1_all()
        intents = {}
        for p in phrases:
            iid = p.get("intent_id", "")
            if iid not in intents:
                intents[iid] = 0
            intents[iid] += 1
        return {"total_phrases": len(phrases), "by_intent": intents}
