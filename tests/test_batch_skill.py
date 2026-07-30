from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugins.base import HookPoint, PluginContext
from plugins.builtin.tool_plugin import ToolPlugin
from skills.loader import SkillLoader
from skills.manager import SkillManager
from skills.registry import SkillRegistry


class _FakeTask:
    def __init__(self, status="pending", result=None, error=None):
        self.status = type("Status", (), {"value": status})()
        self.result = result
        self.error = error


class _FakeTaskManager:
    def __init__(self):
        self.created = []
        self.executed = []

    def create_task(self, **kwargs):
        task_id = f"task-{len(self.created) + 1}"
        self.created.append({"task_id": task_id, **kwargs})
        return task_id

    def execute_task(self, task_id):
        self.executed.append(task_id)

    def get_task(self, task_id):
        return _FakeTask(result={"success": True}) if task_id == "task-1" else None


def test_batch_skill_loads_from_its_root_directory():
    registry = SkillRegistry()
    manager = SkillManager(skill_dirs=["skills/batch"], registry=registry)

    assert manager.scan_and_load() == 1
    assert registry.has_skill("batch")
    schema = registry.get_tools_schema()
    names = {item["function"]["name"] for item in schema}
    assert names == {"skill-batch-batch_execute", "skill-batch-batch_status"}
    actions = next(item for item in schema if item["function"]["name"].endswith("batch_execute"))
    assert actions["function"]["parameters"]["properties"]["actions"]["items"]["type"] == "object"


def test_batch_skill_receives_tool_request_context_and_submits_tasks():
    registry = SkillRegistry()
    skill = SkillLoader().load("skills/batch")
    registry.register_skill(skill)
    task_manager = _FakeTaskManager()
    plugin = ToolPlugin(skill_registry=registry)
    ctx = PluginContext(user_id=7, chat_id=11, message="批量执行")
    ctx.extra["_task_manager"] = task_manager
    ctx.original_reply = (
        '<tool>{"skill":"batch","tool":"batch_execute","params":{"actions":['
        '{"action_type":"shell","content":"pwd","label":"where"},'
        '{"action_type":"invalid","content":"skip"}]}}</tool>'
    )
    ctx.reply = ctx.original_reply

    result = plugin.on_hook(HookPoint.POST_PROCESS, ctx)

    assert result.extra["_tag_results"][0]["success"] is True
    submitted = result.extra["_tag_results"][0]["data"]
    assert submitted["submitted"] == 1
    assert submitted["failed"] == 1
    assert task_manager.executed == ["task-1"]
    assert task_manager.created[0]["user_id"] == 7
    assert task_manager.created[0]["chat_id"] == 11


def test_batch_skill_prefers_thread_local_request_context():
    from skills.batch.tools.batch_tools import BatchTools
    from skills.context import set_call_context

    task_manager = _FakeTaskManager()
    BatchTools.set_context(task_manager=task_manager)
    BatchTools._ctx["_uid"] = 1
    BatchTools._ctx["_cid"] = 2
    set_call_context(user_id=9, chat_id=13)

    result = BatchTools().batch_execute([
        {"action_type": "python", "content": "print('ok')"},
    ])

    assert result["submitted"] == 1
    assert task_manager.created[0]["user_id"] == 9
    assert task_manager.created[0]["chat_id"] == 13
