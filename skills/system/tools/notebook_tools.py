# skills/system/tools/notebook_tools.py


class NotebookTools:
    _ctx = {}

    @classmethod
    def set_context(cls, notebook_store=None):
        cls._ctx["notebook_store"] = notebook_store

    def __init__(self):
        pass

    def save_observation(self, content: str) -> dict:
        store = self._ctx.get("notebook_store")
        if not store:
            return {"error": "NotebookStore 未注入"}
        uid = self._ctx.get("_uid", 0)
        cid = self._ctx.get("_cid", 0)
        store.add_note(uid, content, cid)
        return {"saved": True}
