# tests/test_subagent_runner.py
# SubAgentRunner 测试 — 隔离上下文 + 工具小循环 + 并发 + 释放

"""
用法:
    python tests/test_subagent_runner.py

测试内容:
    1. 无工具调用 — 直接返回文本输出
    2. 工具调用 — 执行工具后回喂，再取最终文本
    3. 上下文隔离 — 每次 run 从零构建，不串扰
    4. 最大步数保护 — 超限后仍返回最后回复
    5. 工具名无法解析 — 返回错误 trace 不抛异常
"""

from __future__ import annotations

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeSkillRegistry:
    _tool_instances = {}

    def __init__(self, result=None):
        self.result = result or {"results": ["r1", "r2"]}
        self.calls = []

    def call_tool(self, skill_name, tool_name, params):
        self.calls.append((skill_name, tool_name, params))
        if tool_name == "boom":
            raise RuntimeError("tool crashed")
        return self.result

    def get_tools_schema(self):
        return [{
            "type": "function",
            "function": {
                "name": "skill-search-search",
                "parameters": {"type": "object", "properties": {}},
            },
        }]


class FakeModels:
    """模拟 ModelsPlugin.invoke 契约：tool_calls 写入 ctx.extra"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def invoke(self, messages, ctx=None, tools=None):
        self.calls.append(list(messages))
        reply, tool_calls = self.script.pop(0)
        if tool_calls and ctx is not None:
            ctx.extra["_native_tool_calls"] = tool_calls
            ctx.extra["_last_tool_calls"] = tool_calls
        return reply


def _tc(tool_name="skill-search-search", args="{}"):
    return {"id": "call_1", "function": {"name": tool_name, "arguments": args}}


def test_no_tools():
    """1. 无工具调用 — 直接返回文本输出"""
    print("\n" + "=" * 60)
    print("Test 1: 无工具调用直接输出")
    print("=" * 60)

    from plugins.builtin.subagent_runner import SubAgentRunner

    models = FakeModels([("直接完成，不需要工具。", []), ("不应再调用", [])])
    runner = SubAgentRunner(models_plugin=models, skill_registry=FakeSkillRegistry())

    result = runner.run("你是子代理", "完成简单任务", user_id=1, chat_id=2)

    assert result.output == "直接完成，不需要工具。"
    assert result.steps == 1
    assert result.tool_trace == []
    assert result.error == ""
    assert len(models.calls) == 1
    print(f"  输出: {result.output!r}")
    print("  PASSED")


def test_tool_execution():
    """2. 工具调用 — 执行工具后回喂，再取最终文本"""
    print("\n" + "=" * 60)
    print("Test 2: 工具执行 + 结果回喂")
    print("=" * 60)

    from plugins.builtin.subagent_runner import SubAgentRunner

    script = [
        ("", [_tc("skill-search-search", '{"q": "dsn"}')]),
        ("根据搜索结果：r1、r2。", []),
    ]
    models = FakeModels(script)
    skills = FakeSkillRegistry()
    runner = SubAgentRunner(models_plugin=models, skill_registry=skills)

    result = runner.run("你是子代理", "帮我搜索 dsn", user_id=1, chat_id=2)

    assert result.output == "根据搜索结果：r1、r2。"
    assert result.steps == 2
    assert len(result.tool_trace) == 1
    assert result.tool_trace[0]["success"] is True
    assert result.tool_trace[0]["data"] == {"results": ["r1", "r2"]}
    assert skills.calls == [("search", "search", {"q": "dsn"})]

    # 第二轮消息应包含 assistant tool_calls + tool 结果
    second_msgs = models.calls[1]
    assert second_msgs[-1]["role"] == "tool"
    assert second_msgs[-1]["tool_call_id"] == "call_1"
    assert "r1" in second_msgs[-1]["content"]
    print(f"  输出: {result.output!r}, 工具调用数: {len(result.tool_trace)}")
    print("  PASSED")


def test_context_isolation():
    """3. 上下文隔离 — 每次 run 从零构建，不串扰"""
    print("\n" + "=" * 60)
    print("Test 3: 上下文隔离")
    print("=" * 60)

    from plugins.builtin.subagent_runner import SubAgentRunner

    models = FakeModels([("回答A", []), ("回答B", []), ("回答C", [])])
    runner = SubAgentRunner(models_plugin=models, skill_registry=FakeSkillRegistry())

    r1 = runner.run("系统提示A", "任务A", user_id=1, chat_id=2)
    r2 = runner.run("系统提示B", "任务B", user_id=1, chat_id=2)

    assert r1.output == "回答A"
    assert r2.output == "回答B"
    # 第二次 run 的第一条消息是新的 system prompt，绝无历史残留
    assert models.calls[1][0] == {"role": "system", "content": "系统提示B"}
    assert models.calls[1][1] == {"role": "user", "content": "任务B"}
    assert len(models.calls[1]) == 2
    print(f"  两次独立调用，无历史残留 ({len(models.calls)} 次调用)")
    print("  PASSED")


def test_max_steps_guard():
    """4. 最大步数保护 — 超限后仍返回最后回复"""
    print("\n" + "=" * 60)
    print("Test 4: 最大步数保护")
    print("=" * 60)

    from plugins.builtin.subagent_runner import SubAgentRunner

    # 模型每轮都请求工具，永不终止文本
    script = [("", [_tc()]), ("", [_tc()]), ("", [_tc()]), ("", [_tc()])]
    models = FakeModels(script)
    runner = SubAgentRunner(models_plugin=models, skill_registry=FakeSkillRegistry(),
                            max_steps=2)

    result = runner.run("你是子代理", "任务", user_id=1, chat_id=2)

    assert result.steps == 2
    assert len(result.tool_trace) == 2
    assert len(models.calls) == 2  # 未超过 max_steps 继续调用
    print(f"  步数: {result.steps}, 工具 trace: {len(result.tool_trace)}")
    print("  PASSED")


def test_unresolvable_tool():
    """5. 工具名无法解析 — 返回错误 trace 不抛异常"""
    print("\n" + "=" * 60)
    print("Test 5: 无法解析的工具名")
    print("=" * 60)

    from plugins.builtin.subagent_runner import SubAgentRunner

    script = [
        ("", [_tc("bad-name")]),
        ("完成。", []),
    ]
    models = FakeModels(script)
    runner = SubAgentRunner(models_plugin=models, skill_registry=FakeSkillRegistry())

    result = runner.run("你是子代理", "任务", user_id=1, chat_id=2)

    assert result.output == "完成。"
    assert len(result.tool_trace) == 1
    assert result.tool_trace[0]["success"] is False
    print(f"  失败 trace: {result.tool_trace[0]['error']}")
    print("  PASSED")


def test_tool_error_handled():
    """6. 工具抛异常 — 进入 error trace，小循环继续"""
    print("\n" + "=" * 60)
    print("Test 6: 工具异常处理")
    print("=" * 60)

    from plugins.builtin.subagent_runner import SubAgentRunner

    script = [
        ("", [_tc("skill-search-boom")]),
        ("工具报错了，但已处理。", []),
    ]
    models = FakeModels(script)
    runner = SubAgentRunner(models_plugin=models, skill_registry=FakeSkillRegistry())

    result = runner.run("你是子代理", "任务", user_id=1, chat_id=2)

    assert result.output == "工具报错了，但已处理。"
    assert len(result.tool_trace) == 1
    assert result.tool_trace[0]["success"] is False
    assert "tool crashed" in result.tool_trace[0]["error"]
    print("  PASSED")


def main():
    print("=" * 60)
    print("  DSN-exp SubAgentRunner 测试")
    print("=" * 60)
    print(f"  Python: {sys.version}")
    print(f"  工作目录: {os.getcwd()}")

    tests = [
        ("无工具直接输出", test_no_tools),
        ("工具执行+回喂", test_tool_execution),
        ("上下文隔离", test_context_isolation),
        ("最大步数保护", test_max_steps_guard),
        ("无法解析工具名", test_unresolvable_tool),
        ("工具异常处理", test_tool_error_handled),
    ]

    passed = 0
    failed = 0
    for name, func in tests:
        try:
            func()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"\n  FAILED: {name}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"  结果: {passed} passed, {failed} failed, {len(tests)} total")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit(main())
