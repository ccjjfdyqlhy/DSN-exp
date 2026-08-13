# skills/system/tools/utility_tools.py


class UtilityTools:
    _ctx = {}

    @classmethod
    def set_context(cls, prompt_cache=None):
        cls._ctx["prompt_cache"] = prompt_cache

    def __init__(self):
        pass

    def search_prompts(self, query: str) -> dict:
        cache = self._ctx.get("prompt_cache")
        if not cache:
            return {"error": "PromptCache 未注入"}
        uid = self._ctx.get("_uid", 0)
        cid = self._ctx.get("_cid", 0)
        results = cache.search(uid, cid, query, limit=3)
        return {"results": results}
