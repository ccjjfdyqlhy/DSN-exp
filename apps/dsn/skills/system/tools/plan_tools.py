# skills/system/tools/plan_tools.py


class PlanTools:
    _ctx = {}

    @classmethod
    def set_context(cls, plan_engine=None):
        cls._ctx["plan_engine"] = plan_engine

    def __init__(self):
        pass

    def mark_plan_task(self, task_id: str, action: str) -> dict:
        eng = self._ctx.get("plan_engine")
        if not eng:
            return {"error": "PlanEngine 未注入"}
        if action == "done":
            eng.check_off(task_id)
        elif action == "skip":
            eng.skip_task(task_id)
        return {"task_id": task_id, "action": action}
