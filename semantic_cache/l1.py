import logging

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
