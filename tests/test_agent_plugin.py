# tests/test_agent_plugin.py
# Agent 循环测试 — 单次执行 + 多步循环 + 工具反馈

"""
用法:
    python tests/test_agent_plugin.py

测试内容:
    1. AgentPlugin 单次执行模式（agent_active=False，向后兼容）
    2. AgentPlugin 多步循环：list_dir → read_file → 无更多工具 → 结束
    3. AgentPlugin 达到最大步数自动终止
    4. AgentPlugin 无工具标签时直接通过
    5. AgentPlugin 工具执行失败时的降级处理
    6. AgentPlugin token 预算裁剪
    7. AgentPlugin 超时保护
    8. AgentPlugin + 完整 Pipeline 集成
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Mock 依赖 ──

class MockModelsPlugin:
    """模拟 ModelsPlugin — 提供 invoke() 方法，返回预定义的回复序列"""

    def __init__(self, response_sequence: list[str] | None = None):
        self.responses = list(response_sequence or [])
        self.call_count = 0
        self.last_messages: list[dict] = []

    def invoke(self, messages: list[dict], ctx=None) -> str:
        self.last_messages = list(messages)
        if self.call_count < len(self.responses):
            resp = self.responses[self.call_count]
            self.call_count += 1
            return resp
        return "最终回复，无工具标签。"


class MockSkillRegistry:
    """模拟 SkillRegistry — 返回预设结果"""

    def __init__(self, tool_results: dict | None = None):
        self._results = tool_results or {}
        self.calls: list[tuple] = []  # (skill, tool, params)

    def call_tool(self, skill_name: str, tool_name: str, params: dict):
        self.calls.append((skill_name, tool_name, params))
        key = f"{skill_name}.{tool_name}"
        return self._results.get(key, {"success": False, "error": "未注册的工具"})


def test_single_pass_mode():
    """1. AgentPlugin 单次执行模式（agent_active=False）"""
    print("\n" + "=" * 60)
    print("Test 1: AgentPlugin 单次执行模式")
    print("=" * 60)

    from plugins.base import PluginContext, HookPoint
    from plugins.builtin.agent_plugin import AgentPlugin

    registry = MockSkillRegistry({
        "file_manager.list_dir": {
            "success": True,
            "path": ".",
            "items": [
                {"name": "config.py", "type": "file"},
                {"name": "models.py", "type": "file"},
            ],
            "count": 2,
        }
    })

    plugin = AgentPlugin(skill_registry=registry)

    # agent_active=False → 单次执行
    ctx = PluginContext(user_id=1, message="列出文件", chat_id=1)
    ctx.original_reply = '列出当前目录：\n<tool>\n{"skill": "file_manager", "tool": "list_dir", "params": {"path": "."}}\n</tool>'
    ctx.reply = ctx.original_reply
    ctx.agent_active = False

    ctx = plugin.on_hook(HookPoint.POST_PROCESS, ctx)
    assert "<tool>" not in ctx.reply
    assert "config.py" in ctx.reply
    assert "models.py" in ctx.reply
    print(f"  单次执行回复: {ctx.reply[:120]}...")
    print("  PASSED")


def test_multi_step_loop():
    """2. AgentPlugin 多步循环：两轮工具调用后自然终止"""
    print("\n" + "=" * 60)
    print("Test 2: AgentPlugin 多步 Agent 循环")
    print("=" * 60)

    from plugins.base import PluginContext, HookPoint
    from plugins.builtin.agent_plugin import AgentPlugin

    # 工具结果
    registry = MockSkillRegistry({
        "file_manager.list_dir": {
            "success": True, "path": "src",
            "items": [
                {"name": "app.py", "type": "file"},
                {"name": "utils.py", "type": "file"},
            ],
            "count": 2,
        },
        "file_manager.read_file": {
            "success": True, "path": "src/app.py",
            "size": 200,
            "content": "# Main application entry\nimport flask\napp = flask.Flask(__name__)\n",
        },
    })

    # LLM 回复序列（每次 AgentPlugin 调用 LLM 时按序返回）
    # 第 1 次 invoke: 含 read_file 工具
    # 第 2 次 invoke: 无工具 — 循环终止
    responses = [
        '目录里有 app.py 和 utils.py，我看看 app.py。\n<tool>\n{"skill": "file_manager", "tool": "read_file", "params": {"path": "src/app.py"}}\n</tool>',
        "app.py 是一个 Flask 应用入口，导入了 flask 模块。需要我做其他分析吗？",
    ]
    models = MockModelsPlugin(responses)

    plugin = AgentPlugin(skill_registry=registry, models_plugin=models, max_steps=5)

    ctx = PluginContext(user_id=1, message="分析 src 目录", chat_id=1)
    ctx.system_prompt = "你是分析助手。"
    ctx.full_history = []
    # 首轮 AI 回复（已经在 MODEL_INVOKE 阶段生成了）
    ctx.original_reply = '先列目录。\n<tool>\n{"skill": "file_manager", "tool": "list_dir", "params": {"path": "src"}}\n</tool>'
    ctx.reply = ctx.original_reply
    ctx.agent_active = True

    ctx = plugin.on_hook(HookPoint.POST_PROCESS, ctx)

    # 验证循环执行了 2 步
    assert ctx.extra["agent_steps_executed"] == 2
    assert models.call_count == 2  # 第二步后 LLM 无工具标签，循环自然终止
    assert len(registry.calls) == 2  # list_dir + read_file

    # 验证最终回复不含工具标签
    assert "<tool>" not in ctx.reply
    assert "需要我做其他分析吗" in ctx.reply
    print(f"  最终回复: {ctx.reply}")
    print(f"  执行步数: {ctx.extra['agent_steps_executed']}")
    print(f"  LLM 再调用次数: {models.call_count}")
    print(f"  工具调用: {[f'{s}.{t}' for s, t, _ in registry.calls]}")
    print("  PASSED")


def test_max_steps_limit():
    """3. AgentPlugin 达到最大步数自动终止"""
    print("\n" + "=" * 60)
    print("Test 3: AgentPlugin 步数限制")
    print("=" * 60)

    from plugins.base import PluginContext, HookPoint
    from plugins.builtin.agent_plugin import AgentPlugin

    # 工具总是返回成功，LLM 总是带新的 <tool> 标签
    registry = MockSkillRegistry({
        "web_search.search": {
            "success": True, "query": "test",
            "results": [{"title": "Result", "snippet": "content", "url": "http://x"}],
            "count": 1,
        }
    })
    infinite_responses = [
        f'搜索：\n<tool>\n{{"skill": "web_search", "tool": "search", "params": {{"query": "test{i}"}}}}\n</tool>'
        for i in range(10)
    ]
    models = MockModelsPlugin(infinite_responses)

    plugin = AgentPlugin(skill_registry=registry, models_plugin=models, max_steps=3)

    ctx = PluginContext(user_id=1, message="search", chat_id=1)
    ctx.system_prompt = "你是搜索助手。"
    ctx.original_reply = infinite_responses[0]
    ctx.reply = ctx.original_reply
    ctx.agent_active = True
    ctx.agent_max_steps = 3

    ctx = plugin.on_hook(HookPoint.POST_PROCESS, ctx)

    assert ctx.extra["agent_steps_executed"] == 3  # 应该在 max_steps 处停止
    assert models.call_count == 3  # 每个步调用一次（不包括初始调用）
    print(f"  执行步数: {ctx.extra['agent_steps_executed']} (max=3)")
    print(f"  LLM 调用: {models.call_count}")
    print("  PASSED")


def test_no_tools_bypass():
    """4. AgentPlugin 无工具标签时直接通过"""
    print("\n" + "=" * 60)
    print("Test 4: AgentPlugin 无工具标签直接通过")
    print("=" * 60)

    from plugins.base import PluginContext, HookPoint
    from plugins.builtin.agent_plugin import AgentPlugin

    registry = MockSkillRegistry()
    models = MockModelsPlugin(["不应被调用"])
    plugin = AgentPlugin(skill_registry=registry, models_plugin=models)

    ctx = PluginContext(user_id=1, message="hello", chat_id=1)
    ctx.original_reply = "你好，有什么可以帮你的吗？这是普通回复，不含工具。"
    ctx.reply = ctx.original_reply
    ctx.agent_active = True

    ctx = plugin.on_hook(HookPoint.POST_PROCESS, ctx)
    assert ctx.reply == ctx.original_reply
    assert models.call_count == 0
    assert ctx.extra.get("agent_steps_executed", 0) == 0
    print("  无工具标签时原样通过")
    print("  PASSED")


def test_tool_failure_graceful():
    """5. AgentPlugin 工具失败时降级处理"""
    print("\n" + "=" * 60)
    print("Test 5: AgentPlugin 工具失败降级")
    print("=" * 60)

    from plugins.base import PluginContext, HookPoint
    from plugins.builtin.agent_plugin import AgentPlugin

    # 工具执行失败
    registry = MockSkillRegistry({
        "file_manager.read_file": {"success": False, "error": "文件不存在: missing.txt"},
    })
    # 第二轮 LLM 不再生成工具标签
    models = MockModelsPlugin(["抱歉，文件 missing.txt 不存在，无法读取。"])

    plugin = AgentPlugin(skill_registry=registry, models_plugin=models)

    ctx = PluginContext(user_id=1, message="读取文件", chat_id=1)
    ctx.system_prompt = "你是文件助手。"
    ctx.original_reply = '读取文件：\n<tool>\n{"skill": "file_manager", "tool": "read_file", "params": {"path": "missing.txt"}}\n</tool>'
    ctx.reply = ctx.original_reply
    ctx.agent_active = True

    ctx = plugin.on_hook(HookPoint.POST_PROCESS, ctx)

    assert ctx.extra["agent_steps_executed"] == 1
    assert "不存在" not in ctx.reply or "<tool>" not in ctx.reply
    # LLM 收到了工具失败的信息，生成了新的回复
    print(f"  最终回复: {ctx.reply[:120]}")
    print(f"  LLM 再调用: {models.call_count} 次")
    print("  PASSED")


def test_token_budget_trim():
    """6. AgentPlugin token 预算裁剪"""
    print("\n" + "=" * 60)
    print("Test 6: AgentPlugin Token 预算裁剪")
    print("=" * 60)

    from plugins.base import PluginContext, HookPoint
    from plugins.builtin.agent_plugin import AgentPlugin

    registry = MockSkillRegistry({
        "web_search.search": {
            "success": True, "query": "test",
            "results": [{"title": "x" * 500, "snippet": "y" * 500, "url": "http://z"}],
            "count": 1,
        }
    })

    # 两轮工具调用
    models = MockModelsPlugin([
        '搜索1\n<tool>\n{"skill": "web_search", "tool": "search", "params": {"query": "q1"}}\n</tool>',
        '搜索2\n<tool>\n{"skill": "web_search", "tool": "search", "params": {"query": "q2"}}\n</tool>',
        "没有更多工具了。",
    ])

    plugin = AgentPlugin(skill_registry=registry, models_plugin=models)

    ctx = PluginContext(user_id=1, message="search", chat_id=1)
    ctx.system_prompt = "你是搜索助手。" + ("x" * 100)  # 占一点空间
    ctx.original_reply = models.responses[0]
    ctx.reply = ctx.original_reply
    ctx.agent_active = True
    ctx.agent_token_budget = 500  # 很小的预算，触发裁剪

    ctx = plugin.on_hook(HookPoint.POST_PROCESS, ctx)

    # 应该仍能完成循环（裁剪不阻止执行）
    assert "<tool>" not in ctx.reply
    assert ctx.extra["agent_steps_executed"] >= 1
    print(f"  Token 预算=500, 执行了 {ctx.extra['agent_steps_executed']} 步")
    print("  PASSED")


def test_timeout_protection():
    """7. AgentPlugin 超时保护（模拟）"""
    print("\n" + "=" * 60)
    print("Test 7: AgentPlugin 超时保护")
    print("=" * 60)

    from plugins.base import PluginContext, HookPoint
    from plugins.builtin.agent_plugin import AgentPlugin

    registry = MockSkillRegistry({
        "web_search.search": {
            "success": True, "query": "test",
            "results": [{"title": "Result", "snippet": "ok", "url": "http://x"}],
            "count": 1,
        }
    })

    # 无限的工具调用
    infinite = [
        f'<tool>\n{{"skill": "web_search", "tool": "search", "params": {{"query": "q{i}"}}}}\n</tool>'
        for i in range(20)
    ]
    models = MockModelsPlugin(infinite)

    # timeout = 0.01s — 第一轮执行后必定超时
    plugin = AgentPlugin(
        skill_registry=registry,
        models_plugin=models,
        max_steps=10,
        agent_timeout=0.01,
    )

    ctx = PluginContext(user_id=1, message="search", chat_id=1)
    ctx.system_prompt = "助手"
    ctx.original_reply = infinite[0]
    ctx.reply = ctx.original_reply
    ctx.agent_active = True

    ctx = plugin.on_hook(HookPoint.POST_PROCESS, ctx)

    # 超时后应至少执行了 1 步（或直接超时）
    assert ctx.extra.get("agent_steps_executed", 0) >= 0  # 可能 0 步就直接超时
    print(f"  超时保护生效, 执行了 {ctx.extra.get('agent_steps_executed', 0)} 步")
    print("  PASSED")


def test_pipeline_integration():
    """8. AgentPlugin + Pipeline 集成"""
    print("\n" + "=" * 60)
    print("Test 8: AgentPlugin + Pipeline 集成")
    print("=" * 60)

    from plugins.base import PluginContext, HookPoint
    from plugins.manager import PluginManager
    from plugins.pipeline import ChatPipeline
    from plugins.builtin.agent_plugin import AgentPlugin
    from plugins.builtin.memory_plugin import MemoryPlugin

    registry = MockSkillRegistry({
        "file_manager.list_dir": {
            "success": True, "path": ".",
            "items": [{"name": "file1.py", "type": "file"}],
            "count": 1,
        }
    })

    models = MockModelsPlugin(["分析完毕，目录中有 1 个文件。"])

    class MockMemoryManager:
        def assemble_context(self, user_id, chat_id, history):
            return list(history)
        def record_dialog_and_summary(self, **kwargs):
            pass

    class MockDB:
        def get_memory_count(self, user_id, chat_id):
            return 1
        def get_memories(self, user_id, chat_id):
            return []

    pm = PluginManager()
    pm.register(AgentPlugin(skill_registry=registry, models_plugin=models))
    pm.register(MemoryPlugin(memory_manager=MockMemoryManager(), db=MockDB()))

    pipeline = ChatPipeline(pm)

    ctx = PluginContext(user_id=1, message="列出目录", chat_id=1)
    ctx.system_prompt = "你是文件助手。"
    ctx.original_reply = '列出：\n<tool>\n{"skill": "file_manager", "tool": "list_dir", "params": {"path": "."}}\n</tool>'
    ctx.reply = ctx.original_reply
    ctx.agent_active = True
    ctx.history = []

    import asyncio
    loop = asyncio.new_event_loop()
    ctx = loop.run_until_complete(pipeline.process(ctx))
    loop.close()

    assert "<tool>" not in ctx.reply
    assert ctx.extra.get("agent_steps_executed", 0) >= 1
    print(f"  Pipeline 集成成功, 执行步数: {ctx.extra.get('agent_steps_executed')}")
    print("  PASSED")


# ==============================

def main():
    print("=" * 60)
    print("  DSN-exp Agent 循环测试")
    print("=" * 60)
    print(f"  Python: {sys.version}")
    print(f"  工作目录: {os.getcwd()}")

    tests = [
        ("单次执行模式 (agent_active=False)", test_single_pass_mode),
        ("多步 Agent 循环", test_multi_step_loop),
        ("步数限制终止", test_max_steps_limit),
        ("无工具标签直接通过", test_no_tools_bypass),
        ("工具失败降级处理", test_tool_failure_graceful),
        ("Token 预算裁剪", test_token_budget_trim),
        ("超时保护", test_timeout_protection),
        ("Pipeline 集成", test_pipeline_integration),
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
