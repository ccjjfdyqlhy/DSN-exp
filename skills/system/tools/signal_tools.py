# skills/system/tools/signal_tools.py


class SignalTools:
    _ctx = {}

    @classmethod
    def set_context(cls, impression_manager=None):
        cls._ctx["impression_manager"] = impression_manager

    def __init__(self):
        pass

    def confirm(self) -> dict:
        return {"action": "confirm_requested"}

    def record_impression(self, category: str, content: str,
                           confidence: int = 80) -> dict:
        mgr = self._ctx.get("impression_manager")
        if mgr:
            uid = self._ctx.get("_uid", 0)
            mgr.add(uid, category, content, confidence, source="llm")
        return {"recorded": True}
